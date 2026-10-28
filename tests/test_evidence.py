"""Production selector contracts: source identity, data roles and exact excerpts."""
import json
import pytest
from backend.evidence import profile, resolve_documents, request_kind, patient_data_available, rank_units, units
from backend.extractive import _choose
from backend.citations import whitespace


def pro(text, filename='wellness.pdf', **metadata):
    return profile({'document_id': filename, 'filename': filename}, text, metadata)


def source(text, page=1):
    return {'document_id': 'wellness.pdf', 'filename': 'wellness.pdf', 'page_number': page, 'text': text}


def test_named_publisher_and_deselected_source():
    cdc = pro('Prevention guide', author='Centers for Disease Control and Prevention')
    asthma = pro('ASTHMA ACTION PLAN', 'asthma.pdf')
    assert resolve_documents('According to the CDC guide, what activity?', [cdc, asthma], ['asthma.pdf']) == (set(), True)
    assert resolve_documents('What does the asthma plan suggest?', [cdc, asthma], ['asthma.pdf']) == ({'asthma.pdf'}, False)
    assert resolve_documents('According to the WHO guide, what activity?', [cdc], ['wellness.pdf']) == (set(), True)


@pytest.mark.parametrize('question,kind', [
    ('What is my current weight?', 'measurement'),
    ('What is the patient’s measured A1C result?', 'measurement'),
    ('Which named medicine is filled in?', 'medication'),
    ('What exact genetic variant is confirmed?', 'variant'),
    ('What daily medication is prescribed?', 'medication'),
    ('What is the patient’s name?', 'identity'),
    ('Is the patient currently in the red zone?', 'state')])
def test_absent_recorded_data_not_inferred(question, kind):
    p = pro('For:\nDaily Medications\nMedicine\nHow much to take\nWhen to take it\nBefore exercise\n☐2 or ☐4 puffs\nNormal A1C below 5.7%. Example weight 240 pounds.')
    assert request_kind(question) == kind
    assert not patient_data_available(kind, [p])


@pytest.mark.parametrize('kind,text', [
    ('medication', 'Medication: Exampledrug 5 mg once daily'),
    ('medication', 'Daily Medications\nMedicine\nHow much to take\nWhen to take it\nExampledrug 5 mg once daily\nBefore exercise'),
    ('identity', 'Patient Name: Synthetic Person'),
    ('variant', 'Variant: c.123A>G'),
    ('state', 'Current zone: Green')])
def test_populated_values_are_not_blanket_blocked(kind, text):
    assert patient_data_available(kind, [pro(text)])


def test_recommendation_not_prescription_or_confirmed_variant():
    p = pro('Report Status: Final\nPatient ID: SAMPLE\nRecommend BTK genetic testing. Normal protein expression does not rule out XLA.')
    assert p['kind'] == 'record'
    assert not patient_data_available('medication', [p])
    assert not patient_data_available('variant', [p])


def test_zone_symptoms_preserve_negation_and_complete_bullets():
    text = 'GREEN ZONE\nDOING WELL\n• No cough, wheeze, chest tightness, or\nshortness of breath during the day or\nnight\n• Can do usual activities\nYELLOW ZONE\n• Cough or wheeze\n'
    ranked = rank_units('What symptoms and activity abilities describe the green zone?', [source(text)], [pro(text)])
    assert any('No cough' in u.text and 'night' in u.text for u in ranked)
    assert any('Can do usual activities' in u.text for u in ranked)
    assert all('GREEN ZONE' in u.context and 'YELLOW ZONE' not in u.context for u in ranked)


def test_inline_unit_not_neighboring_column():
    text = 'Daily Nutrient Goals\nCholesterol 150 mg Fiber 30 g\n'
    ranked = rank_units('What is the fiber amount in the nutrient goals?', [source(text)], [pro(text)])
    assert ranked[0].text == 'Fiber 30 g'
    assert whitespace(ranked[0].text) in whitespace(text)


def test_admin_data_is_not_evidence_for_control_measurement():
    text = 'Birth Date: 1990-08-02\nAge: 33\nMonocytes (MFI=1.22) relative to experimental control (MFI=1.53).'
    ranked = rank_units('What is the experimental control MFI?', [source(text)], [pro(text)])
    assert ranked
    assert all('1990' not in u.text and 'Age' not in u.text for u in ranked)


@pytest.mark.parametrize('reply', [
    '{"status":"answered","selections":["E999"]}',
    '{"status":"answered","selections":[],"claim":"Invented"}',
    '{"status":"insufficient_evidence","selections":["E1"]}',
    'not json'])
def test_selector_rejects_unknown_ids_and_authored_claims(reply):
    class Models:
        count = 0
        def select_evidence(self, messages, schema):
            self.count += 1
            return reply
    model = Models()
    candidates = list(units(source('The review interval is 14 days.')))
    assert _choose('What review interval?', candidates, model) is None
    assert model.count == 2


def test_selector_returns_only_server_owned_excerpt():
    class Models:
        def select_evidence(self, messages, schema):
            assert schema['properties']['selections']['items']['enum'][0] == 'E1'
            return json.dumps({'status': 'answered', 'selections': ['E1', 'E1']})
    candidates = list(units(source('At least 150 minutes per week.')))
    assert _choose('How much activity?', candidates, Models()) == [candidates[0]]


def test_record_reference_range_is_not_a_patient_result():
    p = pro('Report Status: Final\nPatient ID: DEMO\nReference range for A1C: below 5.7%\nMedication:\nRecommend genetic testing.')
    assert not patient_data_available('measurement', [p], 'What is the patient’s measured A1C result?')
    assert not patient_data_available('medication', [p])
    assert not patient_data_available('identity', [p])
    p = pro('Report Status: Final\nPatient ID: DEMO\nA1C: 6.1%\nReference range for A1C: below 5.7%')
    assert patient_data_available('measurement', [p], 'What is the patient’s measured A1C result?')


def test_prose_choice_is_not_truncated_to_first_numeric_option():
    text = 'The menus allow you to have a daily sodium level of either 2,300 mg or, by making the noted changes, 1,500 mg.'
    ranked = rank_units('What two daily sodium levels are described?', [source(text)], [pro('DASH guide')])
    assert ranked
    assert all('2,300' not in u.text or '1,500' in u.text for u in ranked)


def test_meal_columns_cannot_supply_an_exact_subtotal():
    text = 'Day 3\nFood Amount Sodium\nBreakfast Lunch Dinner\n300 500 600\n'
    assert not rank_units('What is the exact sodium total for breakfast alone on Day 3?', [source(text)], [pro('DASH guide')])


def test_publisher_name_takes_priority_over_overlapping_topic_title():
    cdc = pro('Prevention guide', author='Centers for Disease Control and Prevention')
    dash = pro('Blood pressure guide', 'dash.pdf', title='Lowering Blood Pressure with DASH')
    assert resolve_documents('According to the CDC guide, what blood pressure is normal?', [cdc, dash], ['wellness.pdf', 'dash.pdf']) == ({'wellness.pdf'}, False)
    assert resolve_documents('According to the WHO guide, what blood pressure is normal?', [cdc, dash], ['wellness.pdf', 'dash.pdf']) == (set(), True)


def test_alphanumeric_test_name_not_matched_to_variant_prefix():
    text = 'A1C: 6.1%\nReference range for A1C: below 5.7%\nVariant: c.123A>G\n'
    ranked = rank_units('What is the patient’s measured A1C result?', [source(text)], [pro('Wellness record')])
    assert ranked and ranked[0].text == 'A1C: 6.1%'
    assert all('Variant' not in u.text and 'Reference' not in u.text for u in ranked)


def test_filled_nonnumeric_label_is_eligible():
    text = 'Patient Name: Fictional Person\nCurrent zone: Green\nVariant: c.123A>G\n'
    ranked = rank_units('What current zone is recorded for the patient?', [source(text)], [pro('Wellness record')])
    assert any(u.text == 'Current zone: Green' for u in ranked)


def test_activity_goal_requires_duration_not_weight_loss_percentage():
    text = 'Physical activity supports weight loss. The weight loss goal is 5%.\nAnd gradually work up to being active at least 150 minutes per week.'
    ranked = rank_units('Summarize the activity goal.', [source(text)], [pro('Wellness guide')])
    assert ranked and all('150 minutes' in u.text for u in ranked)


def test_inline_table_continuation_keeps_heading_context():
    prefix = 'Daily Nutrient Goals Used in\nthe DASH Studies\n'
    text = 'Potassium 4,700 mg\nFiber 30 g\n'
    s = {**source(text), 'page_text': prefix + text, 'start_char': len(prefix)}
    ranked = rank_units('What daily potassium amount appears in the nutrient goals?', [s], [pro('DASH')])
    assert ranked and 'Nutrient Goals' in ranked[0].context
    assert ranked[0].text == 'Potassium 4,700 mg'


def test_inline_table_previous_cell_prose_does_not_hide_requested_value():
    text = 'Saturated fat 6% of calories Potassium 4,700 mg\n'
    ranked = rank_units('What is the potassium amount?', [source(text)], [pro('DASH')])
    assert ranked and ranked[0].text == 'Potassium 4,700 mg'


def test_measurement_evidence_prefers_complete_sentence_over_clipped_prose():
    text = 'Cells are measured by flow cytometry.\nCD20+ B cells are absent in this male patient at 0.2%.\nIntracellular protein expression is normal in monocytes\n(MFI = 1.22) relative to experimental control (MFI = 1.53).\nThis result does not rule out the condition.\n'
    ranked = rank_units('What MFI value is given for the experimental control?', [source(text)], [pro('Flow report')])
    assert ranked
    assert all('male' not in u.text for u in ranked)
    assert any(u.text == 'Intracellular protein expression is normal in monocytes (MFI = 1.22) relative to experimental control (MFI = 1.53).' for u in ranked)


@pytest.mark.parametrize('age_text', ['43-year-old', '43 year old', '43-year‑old', 'aged 43'])
def test_requested_age_matches_narrative_wording_without_an_age_label(age_text):
    text=f'A {age_text} woman presented with a painless lump in her right shoulder.'
    ranked=rank_units('What was the patient’s age?', [source(text)], [pro('Case report')])
    assert ranked and '43' in ranked[0].text
    assert ranked[0].text==text


def test_possessive_does_not_retrieve_unrelated_disease_keywords_for_age():
    text='Keywords: Hodgkin’s lymphoma; extranodal lymphoma; diagnostic biopsy.'
    assert not rank_units('What was the patient’s age?', [source(text)], [pro('Case report')])


def test_mass_location_does_not_require_a_numeric_weight():
    text='The mass was located in the lateral right shoulder.'
    ranked=rank_units('Where was the mass located?', [source(text)], [pro('Soft-tissue mass case report')])
    assert ranked and ranked[0].text==text


def test_location_question_keeps_topic_even_when_it_occurs_in_document_title():
    text='The patient presented with a mass involving the medial right knee.'
    p=pro('Soft-tissue mass case report')
    ranked=rank_units('Where was the mass located?', [source(text)], [p])
    assert ranked and 'right knee' in ranked[0].text


def test_age_question_does_not_substitute_followup_duration():
    text='The patient was followed for 3 years. The lesion measured 5 cm.'
    assert not rank_units('What was the patient’s age?', [source(text)], [pro('Case report')])
