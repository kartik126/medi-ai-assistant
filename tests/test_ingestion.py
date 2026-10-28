import pymupdf
import pytest
from backend.pdf_service import extract_pdf
from backend.errors import AppError
from scripts.create_demo_fixtures import create_fixtures


@pytest.fixture
def fixtures(tmp_path):
    return create_fixtures(tmp_path)


def test_physical_pages_and_empty_page(fixtures):
    pages = extract_pdf((fixtures / 'training-a.pdf').read_bytes(), 'training-a.pdf', 300)
    assert len(pages) == 4
    assert pages[2].warning == 'empty'
    assert pages[2].text == ''
    assert 'ORCHID-7' in pages[3].text and pages[3].page_number == 4
    assert '2.5 g' in pages[1].text


def test_scan_is_actionable(fixtures):
    with pytest.raises(AppError, match='OCR') as error:
        extract_pdf((fixtures / 'scanned-only.pdf').read_bytes(), 'scan.pdf', 300)
    assert error.value.code == 'no_text'


def test_page_limit(fixtures):
    with pytest.raises(AppError) as error:
        extract_pdf((fixtures / 'training-a.pdf').read_bytes(), 'a.pdf', 2)
    assert error.value.status == 413


@pytest.mark.parametrize('data,name', [(b'abc', 'a.pdf'), (b'%PDF-1.7\nbroken', 'a.pdf'), (b'%PDF-1.7\nbroken', 'a.exe')])
def test_invalid_pdfs(data, name):
    with pytest.raises(AppError):
        extract_pdf(data, name, 300)


def test_encrypted_pdf():
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), 'Private synthetic text')
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='secret')
    with pytest.raises(AppError) as error:
        extract_pdf(data, 'locked.pdf', 300)
    assert error.value.code == 'encrypted_pdf'


def test_short_meaningful_page_is_retained():
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), '2.5 g')
        data = doc.tobytes()
    pages = extract_pdf(data, 'short.pdf', 300)
    assert pages[0].text == '2.5 g'
    assert pages[0].warning == 'low_text_review'


def test_native_column_order_preserves_contiguous_evidence():
    # Native PDF stream is column-major; spatial sorting interleaves these lines.
    with pymupdf.open() as doc:
        page = doc.new_page(width=792, height=612)
        for x, title, lines in [
            (30, 'Dust Mites', ['Use mattress covers.', 'Reduce indoor humidity.']),
            (290, 'Animal Dander', ['Keep pets outdoors.', 'Limit pet access.']),
            (550, 'Tobacco Smoke', ['Ask family members to quit smoking.',
                                    'Do not allow smoking in your home or car.'])]:
            page.insert_text((x, 100), title, fontsize=9)
            page.insert_text((x, 150), '\n'.join(lines), fontsize=9)
        content = doc.tobytes()
    text = extract_pdf(content, 'columns.pdf', 300)[0].text
    assert 'Tobacco Smoke\nAsk family members to quit smoking.\nDo not allow smoking in your home or car.' in text


def test_single_column_retains_spatial_sorting():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 150), 'Second paragraph.')
        page.insert_text((50, 50), 'First paragraph.')
        content = doc.tobytes()
    text = extract_pdf(content, 'single.pdf', 300)[0].text
    assert text.index('First paragraph.') < text.index('Second paragraph.')
