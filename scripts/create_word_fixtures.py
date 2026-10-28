"""Create explicitly synthetic Word acceptance fixtures, preserving existing files."""
from pathlib import Path
import argparse
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import get_settings
from backend.document_service import converter_path
from tests.word_fixtures import word_bytes


def create(directory):
    directory.mkdir(parents=True, exist_ok=True)
    modern=directory/'word-modern.docx'
    if modern.exists() and modern.read_bytes()!=word_bytes():raise ValueError('Refusing to replace different existing DOCX')
    if not modern.exists():modern.write_bytes(word_bytes())
    settings=get_settings();binary=converter_path(settings)
    if not binary:raise RuntimeError('Install LibreOffice first')
    legacy=directory/'word-legacy.doc'
    if not legacy.exists():
        with tempfile.TemporaryDirectory(prefix='medical-word-fixtures-') as tmp:
            root=Path(tmp);source=root/'word-legacy.docx';source.write_bytes(word_bytes())
            subprocess.run([binary,'-env:UserInstallation='+(root/'profile').as_uri(),'--headless',
                            '--convert-to','doc:MS Word 97','--outdir',str(root),str(source)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
            legacy.write_bytes((root/'word-legacy.doc').read_bytes())
    return modern,legacy


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('data/word-corpus'))
    create(parser.parse_args().output)
