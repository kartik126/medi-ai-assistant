"""Real PostgreSQL integration checks. Never use the application database."""
import os
from contextlib import nullcontext
from urllib.parse import urlparse
from uuid import uuid4
import pytest
pytest.importorskip('psycopg')
pytest.importorskip('pgvector')
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.db import Database, migrate
from backend.main import create_app
from scripts.create_demo_fixtures import create_fixtures

URL = os.getenv('TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Set TEST_DATABASE_URL to a dedicated *_test database for pgvector integration checks')


class FakeModels:
    """Deterministic injection, used ONLY by tests; no runtime mock mode."""
    fail = False
    current_identity = 'test-model@revision-1'
    def serialized(self): return nullcontext()
    def identity(self): return self.current_identity
    def embed(self, texts, query=False):
        from backend.errors import AppError
        if self.fail: raise AppError('model_timeout', 'Test timeout', 504)
        return [[1., 0., 0.] for text in texts]
    def generate(self, messages): return '{"status":"insufficient_evidence","claims":[]}'
    def readiness(self): return {'ready': True}
    def close(self): pass


@pytest.fixture
def context(tmp_path):
    assert urlparse(URL).path.rstrip('/').endswith('_test'), 'TEST_DATABASE_URL database name must end in _test'
    migrate(URL)
    db = Database(URL)
    settings = Settings(_env_file=None, database_url=URL, data_dir=tmp_path / 'store')
    models = FakeModels()
    app = create_app(settings, db, models)
    with TestClient(app) as client:
        sid = client.post('/sessions').json()['session_id']
        yield client, sid, app.state.store, models, create_fixtures(tmp_path / 'fixtures')
        client.delete(f'/sessions/{sid}')


def upload(client, sid, fixtures, name='training-a.pdf'):
    return client.post(f'/sessions/{sid}/documents', files=[('files', (name, (fixtures / name).read_bytes(), 'application/pdf'))])


def test_duplicate_and_page_provenance(context):
    client, sid, store, model, fixtures = context
    result = upload(client, sid, fixtures).json()[0]['document']
    repeated = upload(client, sid, fixtures).json()[0]['document']
    assert repeated['duplicate']
    assert result['document_id'] == repeated['document_id']
    did = result['document_id']
    assert 'ORCHID-7' in client.get(f'/sessions/{sid}/documents/{did}/pages/4').json()['text']
    with store.db.connection() as conn:
        count = conn.execute('SELECT count(*) AS n FROM documents WHERE session_id=%s', (sid,)).fetchone()['n']
        assert count == 1


def test_partial_batch_and_foreign_session(context):
    client, sid, store, model, fixtures = context
    response = client.post(f'/sessions/{sid}/documents', files=[('files', ('a.pdf', (fixtures/'training-a.pdf').read_bytes(), 'application/pdf')), ('files', ('bad.pdf', b'%PDF-1.7\nbad', 'application/pdf'))])
    assert [r['status'] for r in response.json()] == ['ready', 'error']
    did = response.json()[0]['document']['document_id']
    other = client.post('/sessions').json()['session_id']
    try:
        for path in [f'/sessions/{other}/documents/{did}/file', f'/sessions/{other}/documents/{did}/pages/1']:
            assert client.get(path).status_code == 404
        assert client.post(f'/sessions/{other}/chat', json={'question':'Who is the coordinator?', 'document_ids':[did]}).status_code == 404
    finally:
        client.delete(f'/sessions/{other}')


def test_transaction_rollback_and_pdf_cleanup(context, monkeypatch):
    client, sid, store, model, fixtures = context
    import backend.storage as storage
    def fail(*args, **kwargs): raise RuntimeError('Simulated vector adaptation failure')
    monkeypatch.setattr(storage.np, 'array', fail)
    with pytest.raises(RuntimeError):
        store.ingest(sid, 'a.pdf', (fixtures / 'training-a.pdf').read_bytes())
    assert store.documents(sid) == []
    assert list(store.directory(sid).glob('*')) == []
    with store.db.connection() as conn:
        assert store.session(conn, sid)['embedding_identity'] is None
        for table in ['pages', 'chunks']:
            from psycopg import sql
            assert conn.execute(sql.SQL('SELECT count(*) AS n FROM {} WHERE session_id=%s').format(sql.Identifier(table)), (sid,)).fetchone()['n'] == 0


def test_model_failure_preserves_ready_documents(context):
    client, sid, store, model, fixtures = context
    upload(client, sid, fixtures)
    model.fail = True
    result = upload(client, sid, fixtures, 'training-b.pdf').json()[0]
    assert result['error_code'] == 'model_timeout'
    assert len(store.documents(sid)) == 1


def test_embedding_mismatch(context):
    client, sid, store, model, fixtures = context
    document = upload(client, sid, fixtures).json()[0]['document']
    model.current_identity = 'test-model@revision-2'
    response = client.post(f'/sessions/{sid}/chat', json={'question':'What is the room?', 'document_ids':[document['document_id']]})
    assert response.status_code == 409


def test_clear_cascades_and_removes_files(context):
    client, sid, store, model, fixtures = context
    upload(client, sid, fixtures)
    assert client.delete(f'/sessions/{sid}').status_code == 204
    assert not store.directory(sid).exists()
    with store.db.connection() as conn:
        for table in ['sessions', 'documents', 'pages', 'chunks']:
            from psycopg import sql
            assert conn.execute(sql.SQL('SELECT count(*) AS n FROM {} WHERE session_id=%s').format(sql.Identifier(table)), (sid,)).fetchone()['n'] == 0


def test_exact_retrieval_respects_document_selection(context):
    client, sid, store, model, fixtures = context
    from backend.retrieval import retrieve
    first = upload(client, sid, fixtures).json()[0]['document']
    second = upload(client, sid, fixtures, 'training-b.pdf').json()[0]['document']
    with store.db.connection() as conn:
        rows = retrieve(conn, sid, [first['document_id']], [1.,0.,0.], model.identity(), store.settings)
        assert rows and all(str(r['document_id']) == first['document_id'] for r in rows)
        assert retrieve(conn, uuid4(), [first['document_id']], [1.,0.,0.], model.identity(), store.settings) == []


def test_invalid_and_empty_questions(context):
    client, sid, *_ = context
    assert client.post(f'/sessions/{sid}/chat', json={'question':' ', 'document_ids':[]}).status_code == 422
    result = client.post(f'/sessions/{sid}/chat', json={'question':'Who is the coordinator?', 'document_ids':[]})
    assert result.json()['status'] == 'insufficient_evidence'
    assert client.get('/health').json()['database']['ready']


def test_answer_citations_resolve_to_stored_physical_page(context, monkeypatch):
    import json
    client, sid, store, model, fixtures = context
    document = upload(client, sid, fixtures).json()[0]['document']

    def answer(messages):
        sources = json.loads(messages[1]['content'])['sources']
        source = next(s for s in sources if 'ORCHID-7' in s['text'])
        return json.dumps({'status': 'answered', 'claims': [{
            'text': 'The archive cabinet code is ORCHID-7.',
            'evidence': [{'source_id': source['source_id'],
                          'quote': 'The archive cabinet code is ORCHID-7.'}]}]})

    monkeypatch.setattr(model, 'generate', answer)
    result = client.post(f'/sessions/{sid}/chat', json={
        'question': 'What is the archive cabinet code?',
        'document_ids': [document['document_id']]}).json()
    assert result['status'] == 'answered'
    citation = result['citations'][0]
    assert citation['filename'] == 'training-a.pdf'
    assert citation['page_number'] == 4
    assert citation['quote'] in client.get(citation['page_text_url']).json()['text']
    original = client.get(citation['file_url'])
    assert original.status_code == 200
    assert original.content == (fixtures / 'training-a.pdf').read_bytes()


def test_rejected_pdfs_preserve_ready_document(context):
    import pymupdf
    client, sid, store, model, fixtures = context
    upload(client, sid, fixtures)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), 'Synthetic locked text')
        encrypted = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                               owner_pw='owner', user_pw='secret')
    response = client.post(f'/sessions/{sid}/documents', files=[
        ('files', ('scan.pdf', (fixtures / 'scanned-only.pdf').read_bytes(), 'application/pdf')),
        ('files', ('locked.pdf', encrypted, 'application/pdf')),
    ])
    assert [r['error_code'] for r in response.json()] == ['no_text', 'encrypted_pdf']
    assert len(store.documents(sid)) == 1
    assert len(list(store.directory(sid).glob('*.pdf'))) == 1


def test_session_lock_rejects_competing_mutation(context):
    from backend.errors import AppError
    client, sid, store, model, fixtures = context
    with store.db.session_lock(sid):
        with pytest.raises(AppError) as error:
            store.ingest(sid, 'a.pdf', (fixtures / 'training-a.pdf').read_bytes())
        assert error.value.code == 'session_busy'
    assert upload(client, sid, fixtures).json()[0]['status'] == 'ready'


def test_migration_is_idempotent(context):
    _, _, store, *_ = context
    with store.db.connection() as conn:
        before = conn.execute('SELECT * FROM schema_migrations ORDER BY name').fetchall()
    migrate(URL)
    with store.db.connection() as conn:
        assert conn.execute('SELECT * FROM schema_migrations ORDER BY name').fetchall() == before


@pytest.mark.parametrize('second_answered', [True, False])
def test_multipart_chat_keeps_citations_and_exposes_partial_failure(context, monkeypatch, second_answered):
    import json
    import numpy as np
    client, sid, store, model, fixtures = context
    first = upload(client, sid, fixtures).json()[0]['document']
    second = upload(client, sid, fixtures, 'training-b.pdf').json()[0]['document']
    with store.db.connection() as conn:
        for chunk in conn.execute('SELECT chunk_id,text FROM chunks WHERE session_id=%s', (sid,)).fetchall():
            vector = [1., 0., 0.] if 'Mira' in chunk['text'] else ([0., 1., 0.] if 'violet' in chunk['text'] else [0., 0., 1.])
            conn.execute('UPDATE chunks SET embedding=%s WHERE chunk_id=%s',
                         (np.array(vector, dtype=np.float32), chunk['chunk_id']))
    monkeypatch.setattr(model, 'embed', lambda texts, query=False:
                        [[1., 0., 0.] if 'coordinator' in text else [0., 1., 0.] for text in texts])
    calls = []
    def generate(messages):
        data = json.loads(messages[1]['content'])
        calls.append(data)
        is_first = 'coordinator' in data['question']
        if not is_first and not second_answered:
            return '{"status":"insufficient_evidence","claims":[]}'
        quote = 'The fictional training coordinator is Mira.' if is_first else 'The badge printer color is violet.'
        source = next(s for s in data['sources'] if quote in s['text'])
        return json.dumps({'status': 'answered', 'claims': [{'text': quote,
            'evidence': [{'source_id': source['source_id'], 'quote': quote}]}]})
    monkeypatch.setattr(model, 'generate', generate)
    result = client.post(f'/sessions/{sid}/chat', json={
        'question': 'Summarize the first handbook coordinator and summarize the second handbook printer color.',
        'document_ids': [first['document_id'], second['document_id']]}).json()
    assert len(calls) == 2
    assert sum(len(s['text']) for call in calls for s in call['sources']) <= store.settings.max_context_chars
    assert sum(len(call['sources']) for call in calls) <= store.settings.max_context_chunks
    assert result['status'] == ('answered' if second_answered else 'insufficient_evidence')
    if second_answered:
        assert {c['document_id'] for c in result['citations']} == {first['document_id'], second['document_id']}
        assert len({c['source_id'] for c in result['citations']}) == 2
    else:
        assert result['reason'] == 'insufficient_evidence'
        assert 'Mira' in result['answer'] and 'not provide enough evidence' in result['answer']


def test_out_of_selection_retrieval_fails_before_generation(context, monkeypatch):
    client, sid, store, model, fixtures = context
    first = upload(client, sid, fixtures).json()[0]['document']
    second = upload(client, sid, fixtures, 'training-b.pdf').json()[0]['document']
    monkeypatch.setattr('backend.answering.retrieve', lambda *args, **kwargs:
                        [{'document_id': second['document_id']}])
    def should_not_generate(*args):
        raise AssertionError('Out-of-selection evidence must not reach generation')
    monkeypatch.setattr(model, 'generate', should_not_generate)
    response = client.post(f'/sessions/{sid}/chat', json={
        'question': 'Who is the coordinator?', 'document_ids': [first['document_id']]})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'retrieval_scope_error'
