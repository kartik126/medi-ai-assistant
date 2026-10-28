"""Actual production answering branch exercised against isolated PostgreSQL."""
import json
from tests.test_database_api import context, upload, pytestmark


def selector_for(needle):
    def select(messages, schema):
        excerpts = json.loads(messages[-1]['content'])['excerpts']
        chosen = next((x['id'] for x in excerpts if needle in x['text']), None)
        return json.dumps({'status': 'answered' if chosen else 'insufficient_evidence', 'selections': [chosen] if chosen else []})
    return select


def test_production_path_exact_excerpt_and_physical_page(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    model.select_evidence = selector_for('ORCHID-7')
    result = client.post(f'/sessions/{sid}/chat', json={'question': 'What is the archive cabinet code?', 'document_ids': [did]}).json()
    assert result['status'] == 'answered'
    assert result['searched_document_ids'] == [did]
    assert 'ORCHID-7' in result['answer']
    for citation in result['citations']:
        assert citation['document_id'] == did
        assert citation['page_number'] == 4
        assert citation['quote'] in client.get(f'/sessions/{sid}/documents/{did}/pages/4').json()['text']


def test_production_path_wrong_named_source_never_calls_selector(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    def unexpected(*args):
        raise AssertionError('No model call for absent source')
    model.select_evidence = unexpected
    result = client.post(f'/sessions/{sid}/chat', json={'question': 'According to the CDC guide, what is the activity goal?', 'document_ids': [did]}).json()
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []


def test_production_path_model_cannot_author_answer(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    model.select_evidence = lambda *args: json.dumps({'status': 'answered', 'selections': ['Invented claim']})
    result = client.post(f'/sessions/{sid}/chat', json={'question': 'What is the review interval?', 'document_ids': [did]}).json()
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []


def test_production_path_incomplete_multipart_selection_abstains(context):
    client, sid, store, model, fixtures = context
    did = upload(client, sid, fixtures).json()[0]['document']['document_id']
    model.select_evidence = selector_for('ORCHID-7')
    result = client.post(f'/sessions/{sid}/chat', json={
        'question': 'What is the archive cabinet code and what is the fictional calibration card mass?',
        'document_ids': [did]}).json()
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []


def test_production_path_comparison_requires_each_document(context):
    client, sid, store, model, fixtures = context
    first = upload(client, sid, fixtures).json()[0]['document']['document_id']
    second = upload(client, sid, fixtures, 'training-b.pdf').json()[0]['document']['document_id']
    model.select_evidence = selector_for('14 days')
    result = client.post(f'/sessions/{sid}/chat', json={
        'question': 'Compare the review intervals in both handbooks.',
        'document_ids': [first, second]}).json()
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []


import pytest

@pytest.mark.parametrize('question,expected,needle', [
    ('What is the GENE8 variant allele frequency?', 'GENE8 variant allele frequency: 23.4%.', '23.4%'),
    ('What is the GENE9 gain fold change?', 'GENE9 gain fold change: 4.2.', '4.2')])
def test_table_answer_separates_field_value_from_evidence(context,question,expected,needle):
    from tests.test_table_answers import table_pdf
    client,sid,store,model,fixtures=context
    uploaded=client.post(f'/sessions/{sid}/documents', files=[('files',('table.pdf',table_pdf(),'application/pdf'))]).json()[0]
    did=uploaded['document']['document_id']
    model.select_evidence=selector_for(needle)
    result=client.post(f'/sessions/{sid}/chat',json={'question':question,'document_ids':[did]}).json()
    assert result['status']=='answered'
    assert result['answer'].startswith(expected)
    assert len(result['answer'])<100 and 'Transcript' not in result['answer']
    assert result['citations']
    for citation in result['citations']:
        assert citation['filename']=='table.pdf' and citation['page_number']==4
        assert citation['file_url'].endswith('#page=4')
        page=client.get(citation['page_text_url']).json()['text']
        from backend.citations import whitespace
        assert whitespace(citation['quote']) in whitespace(page)
        assert 'Gene' in citation['quote'] and needle in citation['quote']


def test_missing_original_table_never_falls_back_to_raw_rows(context):
    from tests.test_table_answers import table_pdf
    client,sid,store,model,fixtures=context
    did=client.post(f'/sessions/{sid}/documents',files=[('files',('table.pdf',table_pdf(),'application/pdf'))]).json()[0]['document']['document_id']
    (store.directory(sid)/f'{did}.pdf').unlink()
    model.select_evidence=selector_for('23.4%')
    result=client.post(f'/sessions/{sid}/chat',json={'question':'What is the GENE8 VAF?','document_ids':[did]}).json()
    assert result['status']=='insufficient_evidence'
    assert 'Gene Alteration' not in result['answer']
    assert result['citations']==[]


@pytest.mark.parametrize('age',[47,62])
def test_narrative_patient_age_and_lesion_location_are_both_answerable(context,age):
    import pymupdf
    client,sid,store,model,fixtures=context
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,60),f'Case presentation\nA {age}-year-old woman presented with a painless mass\ninvolving the lateral aspect of the right shoulder.\nFollow-up continued for 3 years.')
        content=pdf.tobytes()
    did=client.post(f'/sessions/{sid}/documents',files=[('files',('Soft tissue mass case report.pdf',content,'application/pdf'))]).json()[0]['document']['document_id']
    model.select_evidence=selector_for(f'{age}-year-old')
    result=client.post(f'/sessions/{sid}/chat',json={
        'question':'What was the patient’s age, and where was the mass located?',
        'document_ids':[did]}).json()
    assert result['status']=='answered'
    assert f'{age}-year-old' in result['answer'] and 'right shoulder' in result['answer']
    assert result['citations'] and all(c['page_number']==1 and c['document_id']==did for c in result['citations'])


@pytest.mark.parametrize('supported',[True,False])
def test_checked_summary_changes_answer_but_preserves_source_quote(context,supported):
    import pymupdf
    from tests.test_summarizing import QUOTE,DRAFT,Models
    from backend.citations import whitespace
    client,sid,store,model,fixtures=context
    with pymupdf.open() as pdf:
        page=pdf.new_page();page.insert_textbox(pymupdf.Rect(50,50,560,500),QUOTE,fontsize=11)
        content=pdf.tobytes()
    did=client.post(f'/sessions/{sid}/documents',files=[('files',('outcome.pdf',content,'application/pdf'))]).json()[0]['document']['document_id']
    model.select_evidence=selector_for('no chemotherapy')
    summarizer=Models(supported=supported)
    model.summarize_evidence=summarizer.summarize_evidence
    model.check_summary=summarizer.check_summary
    result=client.post(f'/sessions/{sid}/chat',json={'question':'Summarize chemotherapy, radiotherapy and follow-up outcome.','document_ids':[did]}).json()
    if supported:
        assert result['status']=='answered'
        assert result['answer'].startswith(DRAFT) and QUOTE not in result['answer']
    else:
        assert result['status']=='insufficient_evidence' and QUOTE not in result['answer']
    assert result['citations']
    assert all(whitespace(c['quote'])==QUOTE and c['page_number']==1 and c['document_id']==did for c in result['citations'])
