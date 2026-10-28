import json
import pytest
from backend.citations import validate_claims
from backend.answering import grounded_answer, ambiguous, empty_daily_medication_section
from backend.citations import quote_candidates, resolve_quote_ids, whitespace

SOURCE = {'source_id': 'S1', 'text': 'The review interval is 14 days.\nMass: 2.5 g.', 'filename': 'a.pdf',
          'page_number': 2, 'chunk_id': 'chunk', 'document_id': 'doc'}

BLANK_MEDICATION_FORM = 'Daily Medications\nMedicine\nHow much to take\nWhen to take it\nBefore exercise\n\uf071________\n\uf0712 or \uf0714 puffs\n5 minutes before exercise'


def payload(quote='review interval is 14 days.', source='S1'):
    return {'status': 'answered', 'claims': [{'text': 'Review every 14 days.', 'evidence': [{'source_id': source, 'quote': quote}]}]}


def test_valid_normalized_quote():
    assert validate_claims(json.dumps(payload('14 days. Mass: 2.5 g.')), {'S1': SOURCE})['status'] == 'answered'


@pytest.mark.parametrize('claim', ['Review every 21 days.', 'The access code is SECRET-999.'])
def test_claim_numbers_and_codes_require_quoted_support(claim):
    data = payload()
    data['claims'][0]['text'] = claim
    with pytest.raises(ValueError, match='absent from quoted evidence'):
        validate_claims(json.dumps(data), {'S1': SOURCE})


@pytest.mark.parametrize('data', [payload(source='S9'), payload(quote='21 days'), {'status':'answered','claims':[]},
    {'status':'insufficient_evidence','claims':payload()['claims']}, {'status':'answered','claims':{},},
    {'status':'answered','claims':[{'text':'x','evidence':[]}]}, {'status':'answered','claims':[], 'answer':'uncited'},
    {'status': 'wrong', 'claims': []}])
def test_reject_invalid(data):
    with pytest.raises(ValueError):
        validate_claims(json.dumps(data), {'S1': SOURCE})


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.system_prompts = []
    def generate(self, messages):
        self.calls += 1
        self.system_prompts.append(messages[0]['content'])
        return next(self.responses)


def test_blank_medication_form_abstains_before_generation():
    model = Model([])
    source = {**SOURCE, 'text': BLANK_MEDICATION_FORM}
    result = grounded_answer('What is the patient’s prescribed daily medication?', [source], model, 'session')
    assert result['status'] == 'insufficient_evidence'
    assert result['reason'] == 'unfilled_form'
    assert 'section is blank' in result['answer']
    assert model.calls == 0
    assert result['citations'][0]['quote'] in source['text']


def test_filled_medication_section_is_not_treated_as_empty():
    filled = BLANK_MEDICATION_FORM.replace('When to take it\n', 'When to take it\nExampleMed, fictional dose, daily\n')
    assert empty_daily_medication_section('What is the prescribed daily medication?', [{**SOURCE, 'text': filled}]) is None


def test_form_guard_does_not_block_general_guidance_question():
    assert empty_daily_medication_section('What does the form say about exercise?', [{**SOURCE, 'text': BLANK_MEDICATION_FORM}]) is None


def test_absence_statement_is_abstention_not_cited_answer():
    data = payload()
    data['claims'][0]['text'] = 'The asthma symptoms are not mentioned in the provided evidence.'
    result = grounded_answer('What are the asthma symptoms?', [SOURCE], Model([json.dumps(data)]), 'session')
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []


def test_one_repair_then_abstention():
    model = Model(['bad', 'bad'])
    result = grounded_answer('Review?', [SOURCE], model, 'session')
    assert model.calls == 2
    assert result['status'] == 'insufficient_evidence'
    assert result['citations'] == []
    assert result['reason'] == 'citation_validation_failed'


def test_successful_repair_and_server_provenance():
    model = Model(['bad', json.dumps(payload())])
    result = grounded_answer('Review?', [SOURCE], model, 'session')
    assert model.calls == 2
    assert result['status'] == 'answered'
    assert '[S1]' in result['answer']
    citation = result['citations'][0]
    assert citation['filename'] == 'a.pdf' and citation['page_number'] == 2
    assert citation['file_url'] == '/sessions/session/documents/doc/file#page=2'


def test_numeric_claim_repair_requests_value_bearing_quote():
    source = {**SOURCE, 'text': 'Gradually work toward at least 150 minutes per week. One example is 30 minutes, 5 days a week.'}
    bad = payload('One example is 30 minutes, 5 days a week.')
    bad['claims'][0]['text'] = 'Gradually work toward at least 150 minutes per week.'
    good = json.loads(json.dumps(bad))
    good['claims'][0]['evidence'][0]['quote'] = 'Gradually work toward at least 150 minutes per week.'
    model = Model([json.dumps(bad), json.dumps(good)])
    result = grounded_answer('How much activity each week?', [source], model, 'session')
    assert result['status'] == 'answered' and model.calls == 2
    assert 'A claimed number or code was missing' in model.system_prompts[1]
    assert '150 minutes per week' in result['citations'][0]['quote']


def test_repair_feedback_never_echoes_untrusted_exception_text():
    class Broken(Model):
        def generate(self, messages):
            if not self.calls:
                self.calls += 1
                raise ValueError('UNTRUSTED_EXCEPTION_INSTRUCTION')
            assert 'UNTRUSTED_EXCEPTION_INSTRUCTION' not in messages[0]['content']
            return json.dumps(payload())
    assert grounded_answer('Review?', [SOURCE], Broken([]), 'session')['status'] == 'answered'


def test_id_repair_resolves_exact_server_excerpt():
    source = {**SOURCE, 'text': 'Gradually work toward at least 150 minutes per week. One example is 30 minutes, 5 days a week.'}
    bad = payload('One example is 30 minutes, 5 days a week.')
    bad['claims'][0]['text'] = 'Work toward at least 150 minutes per week.'
    class IdModel(Model):
        def generate_with_schema(self, messages, schema):
            data = json.loads(messages[1]['content'])
            assert data['sources'][0]['quotes']['Q1'] == 'Gradually work toward at least 150 minutes per week.'
            assert 'quote_id' in schema['properties']['claims']['items']['properties']['evidence']['items']['required']
            assert schema['properties']['claims']['items']['properties']['evidence']['items']['properties']['source_id']['enum'] == ['S1']
            return json.dumps({'status': 'answered', 'claims': [{'text': 'Work toward at least 150 minutes per week.',
                'evidence': [{'source_id': 'S1', 'quote_id': 'Q1'}]}]})
    result = grounded_answer('How much activity?', [source], IdModel([json.dumps(bad)]), 'session')
    assert result['status'] == 'answered'
    assert result['citations'][0]['quote'] == 'Gradually work toward at least 150 minutes per week.'


def test_unknown_quote_id_is_rejected():
    raw = json.dumps({'status': 'answered', 'claims': [{'text': 'x', 'evidence': [{'source_id': 'S1', 'quote_id': 'Q999'}]}]})
    with pytest.raises(ValueError, match='Unknown repair quote ID'):
        resolve_quote_ids(raw, quote_candidates([SOURCE]))


def test_candidate_excerpts_remain_contiguous_and_bounded():
    source = {**SOURCE, 'text': 'Heading\n' + 'word ' * 350 + 'End.\nNext sentence.'}
    excerpts = quote_candidates([source])['S1']
    assert excerpts
    for text in excerpts.values():
        assert len(text) <= 600 and text in whitespace(source['text'])


def test_empty_context_does_not_generate():
    model = Model([])
    assert grounded_answer('Question', [], model, 's')['status'] == 'insufficient_evidence'
    assert model.calls == 0
    assert grounded_answer('Question', [], model, 's')['reason'] == 'no_sources'


@pytest.mark.parametrize('question', ['What about that?', 'Tell me more.', 'Explain it', 'why?'])
def test_ambiguous_followups(question):
    assert ambiguous(question)


def test_standalone_question():
    assert not ambiguous('What is the review interval?')
