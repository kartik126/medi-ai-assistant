"""Verify UI selection at the HTTP boundary, without running model inference."""
from pathlib import Path
import httpx
from streamlit.testing.v1 import AppTest


def test_selection_sent_to_chat_and_preserved_with_answer(monkeypatch):
    docs = [dict(document_id=name, filename=name + ('.docx' if name == 'cdc' else '.pdf'), indexed_page_count=1,
                 page_count=1, warning_pages=[]) for name in ['asthma', 'cdc', 'dash']]
    calls = []
    def request(self, method, path, **kwargs):
        if path == '/health':
            data = {'ready': True, 'config': {}}
        elif path.endswith('/documents'):
            data = docs
        elif path.endswith('/chat'):
            calls.append(kwargs['json'])
            data = {'status': 'insufficient_evidence', 'answer': 'No evidence.', 'citations': [], 'timings': {}, 'searched_document_ids': kwargs['json']['document_ids']}
        else:
            raise AssertionError((method, path))
        return httpx.Response(200, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.session_state['sid'] = 'test-session'
    app.session_state['messages'] = []
    app.run()
    assert len(app.sidebar.multiselect) == 0
    assert {kind.lstrip('.') for kind in app.sidebar.get('file_uploader')[0].proto.type} == {'pdf', 'doc', 'docx'}
    assert app.multiselect[0].label == 'Documents to use for answers'
    app.multiselect[0].set_value(['cdc']).run()
    app.chat_input[0].set_value('What are the asthma plan green-zone symptoms?').run()
    assert not app.exception
    assert calls[-1]['document_ids'] == ['cdc']
    assert app.session_state['messages'][-1]['document_ids'] == ['cdc']
    assert app.session_state['messages'][-1]['document_names'] == ['cdc.docx']
    # A later selection change must not relabel a historical answer.
    app.multiselect[0].set_value(['dash']).run()
    assert app.session_state['messages'][-1]['document_names'] == ['cdc.docx']
    # Changes to the upload list must not silently expand the chosen scope.
    docs.append(dict(document_id='new', filename='new.pdf', indexed_page_count=1,
                     page_count=1, warning_pages=[]))
    app.run()
    assert app.multiselect[0].value == ['dash']
    assert not app.exception


def test_all_uploaded_pdfs_are_searched_by_default(monkeypatch):
    calls = []
    docs = [dict(document_id=name, filename=name + '.pdf', indexed_page_count=1,
                 page_count=1, warning_pages=[]) for name in ['cdc', 'dash']]
    def request(self, method, path, **kwargs):
        if path == '/health':
            data = {'ready': True, 'config': {}}
        elif path.endswith('/documents'):
            data = docs
        else:
            calls.append(kwargs['json']['document_ids'])
            data = {'answer': 'Supported result.', 'citations': [], 'timings': {},
                    'searched_document_ids': calls[-1]}
        return httpx.Response(200, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.session_state['sid'] = 'test-session'
    app.session_state['messages'] = []
    app.run()
    assert app.multiselect[0].value == ['cdc', 'dash']
    assert not app.chat_input[0].disabled
    assert not app.radio and not app.selectbox
    app.chat_input[0].set_value('Compare both documents.').run()
    assert calls == [['cdc', 'dash']]
    docs.append(dict(document_id='new', filename='new.pdf', indexed_page_count=1,
                     page_count=1, warning_pages=[]))
    app.run()
    assert app.multiselect[0].value == ['cdc', 'dash', 'new']
    app.multiselect[0].set_value([]).run()
    docs.append(dict(document_id='fourth', filename='fourth.pdf', indexed_page_count=1,
                     page_count=1, warning_pages=[]))
    app.run()
    assert app.multiselect[0].value == [] and app.chat_input[0].disabled
    assert not app.exception


import pytest


@pytest.mark.parametrize('failure', ['wrong_echo', 'foreign_citation'])
def test_ui_rejects_response_outside_submitted_selection(monkeypatch, failure):
    def request(self, method, path, **kwargs):
        if path == '/health':
            data = {'ready': True, 'config': {}}
        elif path.endswith('/documents'):
            data = [dict(document_id='cdc', filename='cdc.pdf', indexed_page_count=1,
                         page_count=1, warning_pages=[])]
        else:
            data = {'answer': 'UNSAFE RESULT', 'timings': {},
                    'searched_document_ids': ['asthma'] if failure == 'wrong_echo' else ['cdc'],
                    'citations': [{'document_id': 'asthma'}]}
        return httpx.Response(200, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.session_state['sid'] = 'test-session'
    app.session_state['messages'] = []
    app.run()
    app.multiselect[0].set_value(['cdc']).run()
    app.chat_input[0].set_value('Question').run()
    assert not app.exception
    assert any('not displayed' in error.value for error in app.error)
    assert not any(message['role'] == 'assistant' for message in app.session_state['messages'])
    assert not any('UNSAFE RESULT' in element.value for element in app.text)


def test_session_url_resumes_documents_without_creating_session(monkeypatch):
    sid = '00000000-0000-4000-8000-000000000001'
    calls = []
    def request(self, method, path, **kwargs):
        calls.append((method, path))
        if path == '/health':
            data = {'ready': True, 'config': {}}
        elif path == f'/sessions/{sid}/documents':
            data = [dict(document_id='cdc', filename='cdc.pdf', indexed_page_count=1,
                         page_count=1, warning_pages=[])]
        else:
            raise AssertionError((method, path))
        return httpx.Response(200, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.query_params['session'] = sid
    app.run()
    assert not app.exception
    assert app.session_state['sid'] == sid
    assert app.multiselect[0].options == ['cdc.pdf']
    assert all(method == 'GET' for method, _ in calls)


def test_old_answer_with_foreign_citation_is_not_redisplayed(monkeypatch):
    def request(self, method, path, **kwargs):
        data = {'ready': True, 'config': {}} if path == '/health' else [
            dict(document_id='cdc', filename='cdc.pdf', indexed_page_count=1, page_count=1, warning_pages=[])]
        return httpx.Response(200, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.session_state['sid'] = 'test-session'
    app.session_state['messages'] = [{'role': 'assistant', 'document_ids': ['cdc'], 'document_names': ['cdc.pdf'],
        'result': {'answer': 'OLD UNSAFE ANSWER', 'citations': [{'document_id': 'asthma'}]}}]
    app.run()
    assert not app.exception
    assert any('has been hidden' in warning.value for warning in app.warning)
    assert not any('OLD UNSAFE ANSWER' in element.value for element in app.text)


def test_cleared_session_can_recover_without_restarting_browser(monkeypatch):
    new_sid = '00000000-0000-4000-8000-000000000002'
    def request(self, method, path, **kwargs):
        status = 200
        if path == '/health':
            data = {'ready': True, 'config': {}}
        elif path == '/sessions/cleared-session/documents':
            status, data = 404, {'error': {'message': 'Session unavailable. Start a new session.'}}
        elif path == '/sessions' and method == 'POST':
            data = {'session_id': new_sid}
        elif path == f'/sessions/{new_sid}/documents':
            data = []
        else:
            raise AssertionError((method, path))
        return httpx.Response(status, json=data, request=httpx.Request(method, 'http://localhost' + path))
    monkeypatch.setattr(httpx.Client, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))
    app.session_state['sid'] = 'cleared-session'
    app.session_state['messages'] = []
    app.run()
    restart = next(button for button in app.button if button.label == 'Start a new session')
    restart.click().run()
    assert not app.exception
    assert app.session_state['sid'] == new_sid
    assert app.multiselect[0].label == 'Documents to use for answers'
    assert app.chat_input[0].disabled
    assert any('Start with your documents' in element.value for element in app.markdown)
