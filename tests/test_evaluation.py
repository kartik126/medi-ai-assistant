import json
import pytest
from scripts.evaluate import apply_reviews
from scripts.evaluate import heuristic_check
from scripts.evaluate import evaluate, heuristic_failures


def test_expected_fact_does_not_hide_forbidden_extra_claim():
    case = {'expected_status': 'answered', 'pages': [], 'facts': ['ORCHID-7'],
            'forbidden_facts': ['SECRET-999']}
    actual = {'status': 'answered', 'citations': [],
              'answer': 'The cabinet is ORCHID-7. The access code is SECRET-999.'}
    assert not heuristic_check(case, actual)


def test_review_annotates_same_saved_run(tmp_path):
    results, reviews = tmp_path / 'results.json', tmp_path / 'reviews.json'
    original = {'mode':'live', 'complete':True, 'cases':[{'id':'fact', 'heuristic_pass':True, 'actual':{'answer':'Mira'}, 'human_support_review':'pending'}]}
    results.write_text(json.dumps(original))
    reviews.write_text('{"fact":"pass"}')
    assert apply_reviews(results, reviews)
    report = json.loads(results.read_text())
    assert report['cases'][0]['actual'] == original['cases'][0]['actual']
    assert report['cases'][0]['human_support_review'] == 'pass'


def test_review_cannot_override_failed_heuristic(tmp_path):
    results, reviews = tmp_path / 'results.json', tmp_path / 'reviews.json'
    results.write_text(json.dumps({'mode':'live','complete':True,'cases':[{'id':'x','heuristic_pass':False}]}))
    reviews.write_text('{"x":"pass"}')
    assert not apply_reviews(results, reviews)


def test_incomplete_run_cannot_pass_review(tmp_path):
    results, reviews = tmp_path / 'results.json', tmp_path / 'reviews.json'
    results.write_text('{"mode":"live","complete":false,"cases":[]}')
    reviews.write_text('{}')
    with pytest.raises(ValueError):
        apply_reviews(results, reviews)


def test_value_without_qualifier_or_unit_is_not_a_complete_answer():
    case = {'expected_status': 'answered', 'required_patterns': [r'at least', r'150 minutes per week']}
    actual = {'status': 'answered', 'answer': '150.', 'citations': []}
    assert 'missing_required_pattern' in heuristic_failures(case, actual)


def test_evaluation_does_not_upload_pdfs_to_remote_endpoint(tmp_path):
    with pytest.raises(ValueError, match='restricted to the local API'):
        evaluate('https://example.com', tmp_path, tmp_path / 'result.json')


def test_wrong_document_and_unsupported_extra_number_are_detected():
    case = {'expected_status': 'answered', 'allowed_citation_files': ['a.pdf'],
            'forbidden_patterns': [r'2,114']}
    actual = {'status': 'answered', 'answer': 'The total is 2,114.',
              'citations': [{'filename': 'b.pdf', 'page_number': 1, 'quote': '2,114'}]}
    assert set(heuristic_failures(case, actual)) == {'unexpected_citation_file', 'forbidden_answer_pattern'}


def test_live_runner_retains_errors_continues_and_cleans_only_own_session(tmp_path, monkeypatch):
    import httpx
    (tmp_path / 'a.pdf').write_bytes(b'%PDF-test')
    manifest = tmp_path / 'suite.json'
    manifest.write_text(json.dumps({'name': 'test', 'documents': ['a.pdf'], 'cases': [
        {'id': name, 'question': name, 'expected_status': 'answered'} for name in ['broken', 'good']]}))
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == '/health':
            return httpx.Response(200, json={'config': {}, 'ready': True})
        if path == '/api/tags':
            return httpx.Response(200, json={'models': []})
        if path == '/sessions':
            return httpx.Response(201, json={'session_id': 'owned-session'})
        if path.endswith('/documents'):
            return httpx.Response(200, json=[{'status': 'ready', 'document': {'filename': 'a.pdf', 'document_id': 'doc'}}])
        if path.endswith('/chat'):
            question = json.loads(request.content)['question']
            if question == 'broken':
                return httpx.Response(503, json={'error': {'code': 'model_busy'}})
            return httpx.Response(200, json={'status': 'answered', 'answer': 'Fact.', 'searched_document_ids': ['doc'],
                'citations': [{'filename': 'a.pdf', 'document_id': 'doc', 'page_number': 1, 'quote': 'Fact.',
                'file_url': '/sessions/owned-session/documents/doc/file#page=1',
                'page_text_url': '/sessions/owned-session/documents/doc/pages/1'}]})
        if path.endswith('/pages/1'):
            return httpx.Response(200, json={'text': 'Fact.'})
        if request.method == 'DELETE':
            return httpx.Response(204)
        raise AssertionError(path)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    output = tmp_path / 'result.json'
    assert not evaluate('http://localhost', tmp_path, output, manifest)
    report = json.loads(output.read_text())
    assert report['complete'] and report['test_session_deleted']
    assert report['cases'][0]['http_status'] == 503
    assert report['cases'][1]['heuristic_pass']
    assert report['automatic_summary'] == {'passed': 1, 'failed': 1, 'total': 2, 'executed': 2}
    assert [p for method, p in calls if method == 'DELETE'] == ['/sessions/owned-session']
    with pytest.raises(ValueError, match='already exists'):
        evaluate('http://localhost', tmp_path, output, manifest)


def test_review_for_different_response_is_not_reported_as_approved(tmp_path):
    from scripts.summarize_evaluation import summarize, response_hash
    result = {'mode': 'live', 'complete': True, 'cases': [{'id': 'case',
        'actual': {'answer': 'Changed response'}, 'expected': {'category': 'test'},
        'heuristic_pass': True, 'seconds': 1, 'human_support_review': 'pending'}]}
    path = tmp_path / 'run.json'
    path.write_text(json.dumps(result))
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'cases': {'case': {'actual_sha256': response_hash({'answer': 'Old response'}),
        'verdict': 'pass', 'severity': 'none', 'issue': 'none', 'note': 'Old review'}}}))
    report = summarize(path, review)
    assert '**0/1** recorded' in report
    assert '| case | PASS | pending |' in report


def test_every_citation_must_resolve_to_an_allowed_physical_page():
    case={'expected_status':'answered','pages':[['report.pdf',4]],'allowed_citation_pages':[['report.pdf',4]]}
    actual={'status':'answered','answer':'A field: 12%.','citations':[
        {'filename':'report.pdf','page_number':4,'quote':'12%'},
        {'filename':'report.pdf','page_number':3,'quote':'other'}]}
    assert 'unexpected_citation_page' in heuristic_failures(case,actual)


def test_conciseness_check_does_not_count_source_card_quote_length():
    case={'expected_status':'answered','max_answer_chars':30}
    actual={'status':'answered','answer':'A field: 12%.','citations':[{'filename':'report.pdf','page_number':4,'quote':'long source '*40}]}
    assert 'answer_too_long' not in heuristic_failures(case,actual)
    actual['answer']='raw table row '*40
    assert 'answer_too_long' in heuristic_failures(case,actual)
