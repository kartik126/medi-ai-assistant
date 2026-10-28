import pytest
from backend.measurements import (size_question, size_excerpt, timed_size_units,
                                  dimension_keys)
from backend.evidence import rank_units
from backend.citations import whitespace
from tests.test_summarizing import Models, unit
from backend.summarizing import summarize
from backend.retrieval import select_context


@pytest.mark.parametrize('question,expected',[
    ('What different mass measurements were reported, and when?',True),
    ('What were the lesion dimensions?',True),
    ('How large was the tumor?',True),
    ('What was the patient’s age, and where was the mass located?',False),
    ('Why was the core biopsy inconclusive?',False),
    ('What were the body mass measurements?',False),
    ('What is the calibration card mass?',False),
])
def test_dimension_intent_does_not_replace_other_mass_intents(question,expected):
    assert size_question(question) is expected


def test_exact_windows_keep_timing_and_exclude_surgical_margins():
    text=('At 9 months after presentation, the patient underwent excision. '
          'Intraoperatively, the mass measured approximately 8 × 6 cm. '
          'The lesion was removed with an attempted 2-cm margin.')
    source={'text':text,'document_id':'a','page_number':3}
    result=list(timed_size_units(source))
    assert len(result)==1 and result[0].text==text[:text.index(' The lesion')]
    assert whitespace(result[0].text) in whitespace(text)
    assert not size_excerpt('The scar measured 8 cm.')
    assert not size_excerpt('A 2-cm surgical margin was attempted around the lesion.')


def test_lesion_synonym_and_clinical_range_survive_ranking():
    text=('The mass clinically measured approximately 3 × 2 cm. '
          'On examination, the lesion measured approximately 3 × 2 cm to 4 × 2 cm.')
    source={'text':text,'document_id':'a','filename':'case.pdf','page_number':2}
    ranked=rank_units('What different mass measurements were reported, and when?',[source],[])
    assert len(ranked)==2 and any('to 4 × 2 cm' in u.text for u in ranked)
    assert dimension_keys('A 7-cm mass.')==dimension_keys('A 7 cm mass.')
    assert dimension_keys('6.1 × 4.2 × 2.9 cm')!=dimension_keys('4.2 × 6.1 × 2.9 cm')


@pytest.mark.parametrize('draft',[
    'At 6 months after presentation, the mass measured approximately 6.1 × 4.2 cm.',
    'The mass measured approximately 6.1 × 4.2 × 2.9 cm.',
    'At 6 months after presentation, the mass measured 6.1 × 4.2 × 2.9 cm.',
])
def test_dimension_timing_or_approximation_omission_is_rejected(draft):
    u=unit('At 6 months after presentation, the mass measured approximately 6.1 × 4.2 × 2.9 cm.')
    model=Models(draft=draft)
    assert summarize('What different mass measurements were reported, and when?',[u],model,{'S1':u.source}) is None
    assert model.audits==0


def test_complete_measurement_summary_is_audited():
    u=unit('At 6 months after presentation, the mass measured approximately 6.1 × 4.2 × 2.9 cm.')
    draft='Approximately 6.1 × 4.2 × 2.9 cm was reported for the mass at 6 months after presentation.'
    model=Models(draft=draft)
    assert summarize('What different mass measurements were reported, and when?',[u],model,{'S1':u.source})==[draft]
    assert model.audits==1


def test_nonmeasurement_documents_do_not_consume_size_context_budget():
    real={'text':'The mass measured 7 cm.','document_id':'a','page_number':1,
          'start_char':0,'end_char':23,'similarity':.5}
    unrelated={**real,'document_id':'b','text':'Mass measurements were discussed at review.','similarity':.9}
    chosen=select_context([unrelated,real],question='What different mass measurements were reported, and when?')
    assert len(chosen)==1 and chosen[0]['document_id']=='a'
