from io import BytesIO
from zipfile import ZipFile
import subprocess
import pytest
from backend.config import Settings
from backend.document_service import prepare_document, validate_word, render_word, converter_path
from backend.errors import AppError
from tests.word_fixtures import word_bytes


@pytest.mark.parametrize('extension,content',[('.doc',b'plain text'),('.docx',b'%PDF-1.7'),('.docx',b'PK bad zip')])
def test_word_type_and_structure_are_validated(extension,content):
    with pytest.raises(AppError):validate_word(content,extension)


def test_macro_payload_in_docx_is_rejected():
    out=BytesIO(word_bytes())
    with ZipFile(out,'a') as archive:archive.writestr('word/vbaProject.bin',b'macro')
    with pytest.raises(AppError,match='Macro-enabled'):validate_word(out.getvalue(),'.docx')


def test_missing_converter_has_actionable_error_without_affecting_pdfs():
    settings=Settings(_env_file=None,libreoffice_bin='/not/a/converter')
    with pytest.raises(AppError) as error:render_word(word_bytes(),'.docx',settings)
    assert error.value.code=='word_converter_unavailable'
    assert prepare_document(b'%PDF-same','EXISTING.PDF',settings)==b'%PDF-same'


def test_conversion_timeout_kills_only_its_own_process_group(monkeypatch):
    import backend.document_service as service
    class Process:
        pid=99999
        calls=0
        def wait(self,timeout=None):
            self.calls+=1
            if timeout is not None:raise subprocess.TimeoutExpired('converter',timeout)
            return -9
    killed=[]
    monkeypatch.setattr(service,'converter_path',lambda settings:'/converter')
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:Process())
    monkeypatch.setattr(service.os,'killpg',lambda pid,sig:killed.append(pid))
    with pytest.raises(AppError) as error:render_word(word_bytes(),'.docx',Settings(_env_file=None))
    assert error.value.code=='word_conversion_timeout' and killed==[99999]


def test_real_word_conversion_retains_explicit_pages():
    from backend.pdf_service import extract_pdf
    settings=Settings(_env_file=None)
    assert converter_path(settings),'Install LibreOffice to run the Word acceptance tests'
    rendered=render_word(word_bytes(),'.docx',settings)
    pages=extract_pdf(rendered,'converted.pdf',10)
    assert len(pages)==2
    assert '09:15' in pages[0].text and 'CEDAR-42' in pages[1].text
    assert 'Sample mass' in pages[1].text and '2.5 g' in pages[1].text
