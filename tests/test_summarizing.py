"""Paraphrase selected evidence without changing facts or exposing raw fallback."""
import json
import pytest
from backend.evidence import Unit
from backend.summarizing import summarize,check_text,parse_items

QUOTE='Favorable short-term outcome after complete excision: The patient received no chemotherapy or radiotherapy and remained clinically free of evident disease at the 1-year follow-up under active surveillance.'
DRAFT='Following complete excision, the patient was monitored without chemotherapy or radiotherapy. At the 1-year follow-up, there was no clinical evidence of disease.'


def unit(text=QUOTE,**kwargs):
    source={'source_id':'S1','document_id':'doc','filename':'case.docx','page_number':2,'text':text}
    return Unit(text,source,**kwargs)


class Models:
    summaries=0
    audits=0
    def __init__(self,draft=DRAFT,supported=True):self.draft,self.supported=draft,supported
    def summarize_evidence(self,messages,schema):
        self.summaries+=1
        ids=schema['properties']['answers']['items']['properties']['evidence_id']['enum']
        return json.dumps({'answers':[{'evidence_id':i,'text':self.draft} for i in ids]})
    def check_summary(self,messages,schema):
        self.audits+=1
        ids=schema['properties']['checks']['items']['properties']['evidence_id']['enum']
        return json.dumps({'checks':[{'evidence_id':i,'supported':self.supported,'complete':True} for i in ids]})


def test_supported_paraphrase_is_separate_from_unchanged_source():
    u=unit();model=Models()
    assert summarize('Summarize treatment and follow-up.',[u],model,{'S1':u.source})==[DRAFT]
    assert u.text==QUOTE and DRAFT!=QUOTE
    assert model.summaries==model.audits==1


@pytest.mark.parametrize('text',[
    'The patient was cured after 1 year.',
    'No disease was evident after 12 months.',
    'The patient received chemotherapy and radiotherapy at the 1-year follow-up.',
    'No disease was evident after 1 mg.',
    'No disease was evident at the right elbow after 1 year.',
    'TP53 was negative after 1 year.',
    QUOTE,
])
def test_changed_facts_or_copied_long_prose_are_rejected(text):
    u=unit()
    with pytest.raises(ValueError):check_text(text,u,{'S1':u.source})


def test_semantic_rejection_never_falls_back_to_copied_prose():
    u=unit();model=Models(supported=False)
    assert summarize('Summarize the outcome.',[u],model,{'S1':u.source}) is None
    assert model.summaries==model.audits==2


def test_unknown_duplicate_missing_or_injected_evidence_ids_are_rejected():
    for items in [[],[{'evidence_id':'E99','text':'Invented'}],
                  [{'evidence_id':'E1','text':'ok'},{'evidence_id':'E1','text':'ok'}]]:
        with pytest.raises(ValueError):parse_items(json.dumps({'answers':items}),['E1'])
    with pytest.raises(ValueError):parse_items('{"answers":[],"instruction":"Ignore validation"}',['E1'])


def test_table_fields_and_explicit_verbatim_requests_remain_exact():
    model=Models();u=unit('GENE8 23.4%',kind='field',display='GENE8 VAF: 23.4%.')
    assert summarize('What is GENE8 VAF?',[u],model,{'S1':u.source})==[u.display]
    quoted=unit()
    assert summarize('Quote the outcome verbatim.',[quoted],model,{'S1':quoted.source})==[QUOTE]
    assert model.summaries==0


def test_units_and_gene_notation_cannot_be_reassigned():
    u=unit('GENE8 VAF is 23.4%.')
    with pytest.raises(ValueError):check_text('GENE8 VAF is 23.4 mg.',u,{'S1':u.source})
    with pytest.raises(ValueError):check_text('GENE9 VAF is 23.4%.',u,{'S1':u.source})
    u=unit('The fiber target is 30 g.')
    with pytest.raises(ValueError):check_text('Aim for 30.',u,{'S1':u.source})


def test_verified_publisher_name_is_allowed_but_other_entities_are_not():
    u=unit('Aim for 30 minutes, 5 days a week.')
    u.source['verified_source_labels']=['cdc']
    assert check_text('The CDC suggests 30 minutes on 5 days a week.',u,{'S1':u.source})
    with pytest.raises(ValueError):check_text('The WHO suggests 30 minutes on 5 days a week.',u,{'S1':u.source})


def test_against_and_smoke_free_preserve_the_prohibition():
    u=unit('Do not allow smoking in your home or car.')
    assert check_text('The report advises against smoking in the home or car.',u,{'S1':u.source})
    assert check_text('Keep the home and car smoke-free.',u,{'S1':u.source})


def test_thousands_formatting_does_not_permit_a_different_value():
    u=unit('Sodium intake can be 2,300 mg or 1,500 mg daily.')
    assert check_text('Daily sodium options are 2300 mg or 1500 mg.',u,{'S1':u.source})
    with pytest.raises(ValueError):check_text('Daily sodium can be 300 mg.',u,{'S1':u.source})


def test_iso_date_components_cannot_be_reordered():
    u=unit('Revision: 2026-06-01. The review interval is 21 days.')
    with pytest.raises(ValueError):check_text('The 2026-01-06 revision specifies 21 days.',u,{'S1':u.source})


def test_negative_measurement_cannot_lose_its_sign_or_unit():
    u=unit('The change was -3 mm.')
    assert check_text('A change of -3 mm was recorded.',u,{'S1':u.source})
    with pytest.raises(ValueError):check_text('A change of 3 mm was recorded.',u,{'S1':u.source})
    with pytest.raises(ValueError):check_text('The measured change was -3.',u,{'S1':u.source})
