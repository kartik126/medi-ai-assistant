from pathlib import Path
import subprocess,tempfile
import pytest
from tests.test_database_api import context,upload,pytestmark
from tests.word_fixtures import word_bytes
from tests.test_extractive_api import selector_for
from backend.document_service import converter_path


@pytest.fixture(scope='module')
def legacy_doc(tmp_path_factory):
    from backend.config import Settings
    root=tmp_path_factory.mktemp('legacy-word')
    source=root/'synthetic.docx';source.write_bytes(word_bytes())
    binary=converter_path(Settings(_env_file=None));assert binary
    subprocess.run([binary,'-env:UserInstallation='+(root/'profile').as_uri(),'--headless','--convert-to','doc:MS Word 97','--outdir',str(root),str(source)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
    return (root/'synthetic.doc').read_bytes()


@pytest.mark.parametrize('extension',['docx','doc'])
def test_word_upload_search_sources_and_reset(context,extension,request):
    client,sid,store,model,fixtures=context
    content=word_bytes() if extension=='docx' else request.getfixturevalue('legacy_doc')
    name='notes.'+extension
    result=client.post(f'/sessions/{sid}/documents',files=[('files',(name,content,'application/octet-stream'))]).json()[0]
    assert result['status']=='ready',result
    document=result['document'];did=document['document_id'];assert document['page_count']==2
    assert (store.directory(sid)/f'{did}.{extension}').read_bytes()==content
    assert client.get(f'/sessions/{sid}/documents/{did}/original').content==content
    pdf=client.get(f'/sessions/{sid}/documents/{did}/file')
    assert pdf.headers['content-type']=='application/pdf' and pdf.content.startswith(b'%PDF-')
    assert client.get(f'/sessions/{sid}/documents/{did}/pages/2').json()['text'].find('CEDAR-42')>=0
    model.select_evidence=selector_for('CEDAR-42')
    answer=client.post(f'/sessions/{sid}/chat',json={'question':'What is the fictional archive code?','document_ids':[did]}).json()
    assert answer['status']=='answered' and 'CEDAR-42' in answer['answer']
    assert all(c['filename']==name and c['page_number']==2 and c['file_url'].endswith('#page=2') for c in answer['citations'])
    repeated=client.post(f'/sessions/{sid}/documents',files=[('files',(name,content))]).json()[0]
    assert repeated['document']['duplicate'] and repeated['document']['document_id']==did
    other=client.post('/sessions').json()['session_id']
    try:assert client.get(f'/sessions/{other}/documents/{did}/original').status_code==404
    finally:client.delete(f'/sessions/{other}')
    assert client.delete(f'/sessions/{sid}').status_code==204
    assert not store.directory(sid).exists()


def test_mixed_pdf_word_and_invalid_file_preserve_successes(context):
    client,sid,store,model,fixtures=context
    results=client.post(f'/sessions/{sid}/documents',files=[
        ('files',('guide.pdf',(fixtures/'training-a.pdf').read_bytes())),
        ('files',('notes.docx',word_bytes())),('files',('broken.docx',b'not word'))]).json()
    assert [r['status'] for r in results]==['ready','ready','error']
    assert len(store.documents(sid))==2


def test_word_page_limit_and_conversion_failure_preserve_existing(context,monkeypatch):
    client,sid,store,model,fixtures=context
    existing=upload(client,sid,fixtures).json()[0]['document']['document_id']
    store.settings.max_total_pages=5
    result=client.post(f'/sessions/{sid}/documents',files=[('files',('too-many.docx',word_bytes()))]).json()[0]
    assert result['error_code']=='page_limit'
    assert len(store.documents(sid))==1
    assert list(store.directory(sid).glob('*.docx'))==[]
    assert client.get(f'/sessions/{sid}/documents/{existing}/file').status_code==200


def test_failed_word_transaction_removes_original_and_pdf(context,monkeypatch):
    client,sid,store,model,fixtures=context
    original=Path.replace
    def fail(self,target):
        if str(target).endswith('.docx'):raise OSError('Simulated original finalization failure')
        return original(self,target)
    monkeypatch.setattr(Path,'replace',fail)
    result=client.post(f'/sessions/{sid}/documents',files=[('files',('notes.docx',word_bytes()))])
    assert result.status_code==503
    assert store.documents(sid)==[] and list(store.directory(sid).glob('*'))==[]


def test_cleanup_retains_valid_word_pairs_and_unrelated_notes(context):
    from uuid import uuid4
    client,sid,store,model,fixtures=context
    result=client.post(f'/sessions/{sid}/documents',files=[('files',('notes.docx',word_bytes()))]).json()[0]
    did=result['document']['document_id'];directory=store.directory(sid)
    orphan=directory/f'{uuid4()}.docx';orphan.write_bytes(b'orphan')
    unrelated=directory/'my-notes.docx';unrelated.write_bytes(b'preserve')
    store.cleanup()
    assert (directory/f'{did}.docx').read_bytes()==word_bytes()
    assert (directory/f'{did}.pdf').exists() and not orphan.exists()
    assert unrelated.read_bytes()==b'preserve'
