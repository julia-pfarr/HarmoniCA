import pandas as pd
import pytest

from backend import (UPLOAD_COLUMNS, apply_reuse_decisions, attach_input_metadata, decisions_from_review,
                     inventory_check, parse_items, run_items_with_progress)
import harmonize_workflow as workflow


CONSTRUCTS = ['depression', 'anxiety']


def item(item_id, item_text, questionnaire='PHQ-9', construct='depression'):
    return {
        'construct': construct,
        'questionnaire': questionnaire,
        'item_id': item_id,
        'item_text': item_text,
        'answer_options': '[0, 1, 2, 3]',
        'scoring': '[0, 1, 2, 3]',
    }


def test_validate_items_requires_six_nonempty_columns_and_unique_ids():
    valid = workflow.validate_items(pd.DataFrame([item('PHQ_1', 'Feeling low')]), CONSTRUCTS)
    assert list(valid.columns) == workflow.ITEM_COLUMNS
    assert valid.loc[0, 'construct'] == 'depression'

    with pytest.raises(ValueError, match='Missing required columns'):
        workflow.validate_items(pd.DataFrame([{'construct': 'depression'}]), CONSTRUCTS)

    repeated = pd.DataFrame([item('same', 'First'), item('same', 'Second', questionnaire='Other')])
    with pytest.raises(ValueError, match='Repeated item_id'):
        workflow.validate_items(repeated, CONSTRUCTS)


def test_classify_items_separates_exact_matches_duplicates_and_new_items():
    items = pd.DataFrame([
        item('PHQ-9_01', 'Little interest or pleasure in doing things.'),
        item('PHQ9_1', 'LITTLE interest or pleasure in doing things'),
        item('PHQ-9_99', 'A genuinely new question'),
    ])
    inventory = pd.DataFrame([
        {'item_id': 'PHQ-9_01', 'item_text': 'Little interest or pleasure in doing things.',
         'construct': 'depression', 'questionnaire': 'PHQ-9', 'dimension': '4',
         'dimension_label': 'Activity & interest', 'confidence': '0.9'},
    ])

    routed = workflow.classify_items(items, inventory)

    assert routed['route'].tolist() == ['inventory', 'duplicate', 'new']
    assert routed.loc[1, 'matched_item_id'] == 'PHQ-9_01'
    assert bool(routed.loc[1, 'same_item?']) is True


def test_append_model_predictions_writes_only_new_assignments_and_replaces_key(tmp_path):
    path = tmp_path / 'harmonized_inventory.csv'
    pd.DataFrame([{
        'item_id': 'existing', 'item_text': 'Known', 'construct': 'depression', 'questionnaire': 'PHQ-9',
        'dimension': '1', 'dimension_label': 'Mood', 'confidence': '0.8', 'source': 'expert_consensus',
        'date_added': '', 'model_version': '',
    }], columns=workflow.INVENTORY_COLUMNS).to_csv(path, index=False)
    prediction = pd.DataFrame([{
        'item_id': 'new', 'item_text': 'New wording', 'construct': 'depression', 'questionnaire': 'PHQ-9',
        'dimension': '2', 'dimension_label': 'Cognition', 'confidence': '0.7',
    }])

    assert workflow.append_model_predictions(path, prediction, {'depression': 'ft'}) == 1
    saved = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert set(saved['item_id']) == {'existing', 'new'}
    assert saved.loc[saved.item_id == 'new', 'source'].iloc[0] == 'model_prediction'
    assert saved.loc[saved.item_id == 'new', 'model_version'].iloc[0] == 'ft'

    prediction.loc[0, 'dimension'] = '3'
    assert workflow.append_model_predictions(path, prediction, {'depression': 'ft'}) == 1
    saved = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert (saved['item_id'] == 'new').sum() == 1
    assert saved.loc[saved.item_id == 'new', 'dimension'].iloc[0] == '3'


def test_run_items_with_progress_reports_each_completed_item():
    calls = []
    events = []
    items = [{'item_id': 'a'}, {'item_id': 'b'}]

    def fake_run_model(construct, batch):
        calls.append((construct, [item['item_id'] for item in batch]))
        return [{'item_id': batch[0]['item_id'], 'dimension': 1}]

    predictions = run_items_with_progress(fake_run_model, 'depression', 'PHQ-9', items, events.append)

    assert calls == [('depression', ['a']), ('depression', ['b'])]
    assert [event['item_id'] for event in events] == ['a', 'b']
    assert [event['items'] for event in events] == [1, 1]
    assert predictions == [{'item_id': 'a', 'dimension': 1}, {'item_id': 'b', 'dimension': 1}]


def test_attach_input_metadata_preserves_scoring_columns():
    results = pd.DataFrame([{
        'construct': 'depression', 'questionnaire': 'PHQ-9', 'item_id': 'a',
        'item_text': 'Feeling low', 'dimension': '1', 'dimension_label': 'Mood', 'confidence': '0.8',
    }])
    items = pd.DataFrame([{
        **item('a', 'Feeling low'), 'answer_options': '[0, 1, 2, 3]', 'scoring': '[3, 2, 1, 0]',
    }])

    enriched = attach_input_metadata(results, items)

    assert enriched.loc[0, 'answer_options'] == '[0, 1, 2, 3]'
    assert enriched.loc[0, 'scoring'] == '[3, 2, 1, 0]'


def test_inventory_check_respects_manual_same_item_decision():
    text = "I feel tense or 'wound up'."
    items = pd.DataFrame([
        {**item('HADS_01_alt', text, 'HADS', 'anxiety'), 'reuse_match': True},
        {**item('HADS_01_other', text, 'HADS', 'anxiety'), 'reuse_match': False},
    ])

    routed = inventory_check(items)
    forced = inventory_check(items, force=True)

    assert routed['route'].tolist() == ['inventory', 'duplicate']
    assert forced['route'].tolist() == ['duplicate', 'duplicate']


def csv_bytes(rows, columns=None):
    return pd.DataFrame(rows, columns=columns).to_csv(index=False).encode()


def test_uploaded_files_need_all_six_columns_and_no_empty_cells():
    ok = parse_items(csv_bytes([item('PHQ_1', 'Feeling low')]), UPLOAD_COLUMNS)
    assert list(ok.columns) == UPLOAD_COLUMNS

    four_columns = csv_bytes([{k: v for k, v in item('PHQ_1', 'Feeling low').items()
                               if k not in ('answer_options', 'scoring')}])
    with pytest.raises(ValueError, match='answer_options, scoring'):
        parse_items(four_columns, UPLOAD_COLUMNS)

    blank_scoring = csv_bytes([{**item('PHQ_1', 'Feeling low'), 'scoring': ''}])
    with pytest.raises(ValueError, match='empty'):
        parse_items(blank_scoring, UPLOAD_COLUMNS)


def test_reference_items_still_need_only_the_first_four_columns():
    four_columns = csv_bytes([{k: v for k, v in item('PHQ_1', 'Feeling low').items()
                               if k not in ('answer_options', 'scoring')}])
    assert len(parse_items(four_columns)) == 1


def test_possible_duplicates_are_reused_unless_unchecked():
    text = "I feel tense or 'wound up'."
    items = pd.DataFrame([
        item('HADS_01_alt', text, 'HADS', 'anxiety'),
        item('HADS_01_other', text, 'HADS', 'anxiety'),
        item('HADS_99', 'A genuinely new question', 'HADS', 'anxiety'),
    ])
    keys = lambda row: ('anxiety', 'HADS', row)

    default = apply_reuse_decisions(items, {})
    assert default['reuse_match'].tolist() == [True, True, True]
    assert inventory_check(default)['route'].tolist() == ['inventory', 'inventory', 'new']

    decided = apply_reuse_decisions(items, {keys('HADS_01_other'): False})
    assert decided['reuse_match'].tolist() == [True, False, True]
    assert inventory_check(decided)['route'].tolist() == ['inventory', 'duplicate', 'new']


def test_decisions_are_read_from_the_review_table():
    review = pd.DataFrame([
        {'same_item?': True, 'construct': 'anxiety', 'questionnaire': 'HADS', 'item_id': 'a'},
        {'same_item?': False, 'construct': 'anxiety', 'questionnaire': 'HADS', 'item_id': 'b'},
    ])
    assert decisions_from_review(review) == {('anxiety', 'HADS', 'a'): True, ('anxiety', 'HADS', 'b'): False}
    assert decisions_from_review(None) == {}
