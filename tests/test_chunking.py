import pytest
from backend.chunking import chunk_page, normalize_page


def test_normalization_preserves_units_and_lines():
    assert normalize_page('  Mass\t 2.5 g\r\n  Delta -0.2 mg  ') == 'Mass 2.5 g\nDelta -0.2 mg'


@pytest.mark.parametrize('text', ['', 'Short page.', 'x' * 9000, 'First sentence.\n\n' * 300])
def test_chunks_cover_text_with_exact_offsets(text):
    chunks = chunk_page(text)
    covered = set()
    for c in chunks:
        assert c.text == text[c.start_char:c.end_char]
        assert len(c.text) <= 2000
        covered.update(range(c.start_char, c.end_char))
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())


def test_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_page('abc', target=100, overlap=100)


def test_explicit_sections_do_not_mix_topics():
    text = '\x88Tobacco Smoke\n' + 'Avoid indoor smoke. ' * 25 + '\n\x88Animal Dander\n' + 'Keep pets outside. ' * 25
    chunks = chunk_page(text)
    assert len(chunks) == 2
    assert 'Animal Dander' not in chunks[0].text
    assert chunks[1].text.startswith('\x88Animal Dander')
    assert all(c.text == text[c.start_char:c.end_char] for c in chunks)


def test_paragraph_not_cut_when_it_fits():
    first = 'First paragraph sentence. ' * 30
    second = 'Second paragraph sentence. ' * 30
    text = first + '\n\n' + second
    chunks = chunk_page(text, target=1000)
    assert [c.text for c in chunks] == [first.strip(), second.strip()]


def test_short_heading_stays_with_longer_body():
    text = '# Tobacco Smoke\n\n' + 'Keep the home smoke free. ' * 45
    chunks = chunk_page(text, target=1000)
    assert chunks[0].text.startswith('# Tobacco Smoke\n\nKeep the home')
    assert all(c.text == text[c.start_char:c.end_char] for c in chunks)
