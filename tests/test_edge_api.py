"""Additional lifecycle and request edge cases in the isolated *_test database."""
from uuid import uuid4
from pathlib import Path
import pytest
from tests.test_database_api import context, upload, pytestmark


def test_same_filename_different_bytes_are_distinct_documents(context):
    client, sid, store, model, fixtures = context
    first = upload(client, sid, fixtures).json()[0]['document']
    second = client.post(f'/sessions/{sid}/documents', files=[
        ('files', ('training-a.pdf', (fixtures / 'training-b.pdf').read_bytes(), 'application/pdf'))]).json()[0]['document']
    assert first['document_id'] != second['document_id']
    assert not second['duplicate']
    assert len(store.documents(sid)) == 2


def test_file_limit_counts_unique_bytes_not_duplicate_uploads(context):
    client, sid, store, model, fixtures = context
    store.settings.max_files = 1
    first = upload(client, sid, fixtures).json()[0]['document']
    assert upload(client, sid, fixtures).json()[0]['document']['duplicate']
    failed = upload(client, sid, fixtures, 'training-b.pdf').json()[0]
    assert failed['error_code'] == 'file_limit'
    assert str(store.documents(sid)[0]['document_id']) == first['document_id']


def test_total_page_limit_preserves_previously_ready_pdf(context):
    client, sid, store, model, fixtures = context
    store.settings.max_total_pages = 4
    assert upload(client, sid, fixtures).json()[0]['status'] == 'ready'
    assert upload(client, sid, fixtures).json()[0]['document']['duplicate']
    assert upload(client, sid, fixtures, 'training-b.pdf').json()[0]['error_code'] == 'page_limit'
    assert len(store.documents(sid)) == 1
    assert len(list(store.directory(sid).glob('*.pdf'))) == 1


def test_missing_original_is_typed_error_and_page_text_survives(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    (store.directory(sid) / f'{did}.pdf').unlink()
    response = client.get(f'/sessions/{sid}/documents/{did}/file')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'file_unavailable'
    assert client.get(f'/sessions/{sid}/documents/{did}/pages/1').status_code == 200


def test_startup_reconciliation_removes_orphans_and_preserves_ready_files(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    directory = store.directory(sid)
    original = (directory / f'{did}.pdf').read_bytes()
    (directory / 'unfinished.part').write_bytes(b'staged')
    extra = directory / f'{uuid4()}.pdf'
    extra.write_bytes(b'orphan')
    note = directory / 'unrelated-note.txt'
    note.write_text('preserve')
    orphan = store.directory(uuid4())
    orphan.mkdir()
    (orphan / 'orphan.pdf').write_bytes(b'orphan')
    store.cleanup()
    assert (directory / f'{did}.pdf').read_bytes() == original
    assert not extra.exists() and not (directory / 'unfinished.part').exists()
    assert not orphan.exists()
    assert note.read_text() == 'preserve'


def test_ttl_cleanup_expires_only_old_sessions(context):
    client, sid, store, model, fixtures = context
    upload(client, sid, fixtures)
    active = client.post('/sessions').json()['session_id']
    try:
        with store.db.connection() as conn:
            conn.execute("UPDATE sessions SET updated_at=now()-interval '2 days' WHERE session_id=%s", (sid,))
        store.cleanup()
        assert client.get(f'/sessions/{sid}/documents').status_code == 404
        assert not store.directory(sid).exists()
        assert client.get(f'/sessions/{active}/documents').status_code == 200
    finally:
        client.delete(f'/sessions/{active}')


@pytest.mark.parametrize('question', [' ', 'PRIVATE_TEST_MARKER' + 'x' * 2001])
def test_invalid_question_never_echoes_request_content(context, question):
    client, sid, *_ = context
    response = client.post(f'/sessions/{sid}/chat', json={'question': question, 'document_ids': []})
    assert response.status_code == 422
    assert 'PRIVATE_TEST_MARKER' not in response.text


def test_unknown_document_is_rejected_before_any_model_call(context, monkeypatch):
    client, sid, store, model, fixtures = context
    def fail(*args, **kwargs):
        raise AssertionError('Invalid selection must not reach model')
    monkeypatch.setattr(model, 'embed', fail)
    monkeypatch.setattr(model, 'generate', fail)
    response = client.post(f'/sessions/{sid}/chat', json={'question': 'What is the code?', 'document_ids': [str(uuid4())]})
    assert response.status_code == 404


def test_duplicate_selected_ids_are_deduplicated_in_scope_echo(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    response = client.post(f'/sessions/{sid}/chat', json={'question': 'What is the code?', 'document_ids': [did, did]})
    assert response.status_code == 200
    assert response.json()['searched_document_ids'] == [did]


def test_upload_filename_cannot_control_stored_path(context):
    client, sid, store, model, fixtures = context
    response = client.post(f'/sessions/{sid}/documents', files=[
        ('files', ('../../ignore instructions.pdf', (fixtures / 'training-a.pdf').read_bytes(), 'application/pdf'))])
    document = response.json()[0]['document']
    assert document['filename'] == 'ignore instructions.pdf'
    assert [p.name for p in store.directory(sid).iterdir()] == [document['document_id'] + '.pdf']
