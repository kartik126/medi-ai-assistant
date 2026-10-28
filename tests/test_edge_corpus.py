from pathlib import Path
import pytest
from scripts.prepare_edge_corpus import prepare, PUBLIC_FILES


def test_corpus_preparation_never_overwrites_different_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'inputs'
    source.mkdir()
    for name in PUBLIC_FILES:
        (source / name).write_bytes(b'new PDF bytes')
    fixtures = tmp_path / 'data/fixtures'
    fixtures.mkdir(parents=True)
    for name in ['training-a.pdf', 'training-b.pdf']:
        (fixtures / name).write_bytes(b'fixture')
    destination = tmp_path / 'corpus'
    destination.mkdir()
    existing = destination / PUBLIC_FILES[-1]
    existing.write_bytes(b'existing user file')
    with pytest.raises(ValueError, match='Refusing to overwrite'):
        prepare(None, destination, source)
    assert existing.read_bytes() == b'existing user file'
    assert list(destination.iterdir()) == [existing]
