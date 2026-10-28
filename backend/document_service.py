"""PDF and Word intake; Word pagination is a saved local LibreOffice PDF."""
from io import BytesIO
from pathlib import Path
import os
import shutil
import signal
import subprocess
import tempfile
from threading import Lock
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree
from backend.errors import AppError

EXTENSIONS = {'.pdf', '.doc', '.docx'}
MIME_TYPES = {'.pdf': 'application/pdf', '.doc': 'application/msword',
               '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
_CONVERSION_LOCK = Lock()


def converter_path(settings):
    configured = getattr(settings, 'libreoffice_bin', None)
    if configured:
        return configured if Path(configured).is_file() and os.access(configured, os.X_OK) else None
    return shutil.which('soffice') or shutil.which('libreoffice') or next(
        (str(p) for p in [Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')]
         if p.is_file() and os.access(p, os.X_OK)), None)


def validate_word(content, extension):
    if extension == '.doc':
        if not content.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) or 'WordDocument'.encode('utf-16-le') not in content:
            raise AppError('invalid_word', 'Upload a valid Word .doc file, or save it as .docx and retry.')
        return
    try:
        with ZipFile(BytesIO(content)) as package:
            entries = package.infolist()
            if len(entries) > 5000 or sum(e.file_size for e in entries) > 100*1024**2:
                raise AppError('word_expansion_limit', 'Word document exceeds the expanded-content limit.', 413)
            if any(e.flag_bits & 1 for e in entries):
                raise AppError('encrypted_word', 'Unlock this Word document before uploading.')
            names = package.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate package entries')
            if any('vbaproject' in n.lower() for n in names):
                raise AppError('unsupported_word', 'Macro-enabled Word files are unsupported. Save a macro-free .docx copy.')
            content_types = package.read('[Content_Types].xml')
            if b'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' not in content_types:
                raise ValueError('Not a Word document')
            root = ElementTree.fromstring(package.read('word/document.xml'))
            if root.tag != '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document':
                raise ValueError('Invalid Word XML')
    except AppError:
        raise
    except (BadZipFile, KeyError, ValueError, ElementTree.ParseError, RuntimeError) as exc:
        raise AppError('invalid_word', 'Word document is corrupt, encrypted or not a valid .docx. Save an unlocked .docx copy and retry.') from exc


def render_word(content, extension, settings):
    validate_word(content, extension)
    binary = converter_path(settings)
    if not binary:
        raise AppError('word_converter_unavailable', 'Word uploads need local LibreOffice. Install it, or export your document as PDF.', 503)
    if not _CONVERSION_LOCK.acquire(timeout=5):
        raise AppError('word_converter_busy', 'Another Word document is being converted. Retry shortly.', 503)
    try:
        with tempfile.TemporaryDirectory(prefix='medical-word-') as directory:
            root = Path(directory)
            source = root / ('input'+extension)
            source.write_bytes(content)
            profile = root / 'profile'
            (profile/'user').mkdir(parents=True)
            (profile/'user'/'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop><prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
</oor:items>''')
            command = [binary, '-env:UserInstallation='+profile.as_uri(), '--headless', '--nologo',
                       '--nodefault', '--norestore', '--convert-to', 'pdf:writer_pdf_Export',
                       '--outdir', str(root), str(source)]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                status = process.wait(timeout=settings.word_conversion_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise AppError('word_conversion_timeout', 'Word conversion timed out. Export a PDF locally and retry.', 504) from exc
            target = root / 'input.pdf'
            if status != 0 or not target.is_file():
                raise AppError('word_conversion_failed', 'Word conversion failed. Save an unlocked .docx or export a PDF and retry.')
            if target.stat().st_size > settings.max_file_mb*1024**2:
                raise AppError('converted_size_limit', 'Converted document exceeds the PDF size limit.', 413)
            pdf = target.read_bytes()
            if not pdf.startswith(b'%PDF-'):
                raise AppError('word_conversion_failed', 'Word conversion did not produce a valid PDF.')
            return pdf
    finally:
        _CONVERSION_LOCK.release()


def prepare_document(content, filename, settings):
    extension = Path(filename).suffix.lower()
    if extension not in EXTENSIONS:
        raise AppError('unsupported_file', 'Upload a PDF, Word .doc or Word .docx file.')
    return content if extension == '.pdf' else render_word(content, extension, settings)
