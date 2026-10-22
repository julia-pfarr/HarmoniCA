"""
Tests that keep the command line and the web app in line:

* every assignment the engine returns says where it comes from (per-item `source`);
* the CLI writes the same columns, in the same order, as the web app, carries
  `answer_options` / `scoring` through, normalises the input the same way, and can decide
  possible duplicates without prompting (`--duplicates`).

`_run_model` is mocked, so no ML dependencies or network access are needed.
"""
import json
import sys

import pandas as pd
import pytest
from unittest.mock import patch

from harmonica import harmonize as hz
from harmonica.harmonica import HarmoniCA

INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire',
    'dimension', 'dimension_label', 'confidence',
    'source', 'date_added', 'model_version',
]
INVENTORY_ROW = {
    'item_id': 'PHQ-9_01', 'item_text': 'Little interest or pleasure in doing things.',
    'construct': 'depression', 'questionnaire': 'PHQ-9', 'dimension': 4,
    'dimension_label': 'Activity & interest deficits', 'confidence': 0.9,
    'source': 'expert_consensus', 'date_added': '2026-01-01', 'model_version': 'ft',
}


def _fake_run_model(self, construct, items):
    return [{'item_id': it['item_id'], 'item_text': it['item_text'], 'dimension': 2,
             'dimension_label': 'NewDim', 'confidence': 0.99} for it in items]


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / 'inventory.csv'
    pd.DataFrame([INVENTORY_ROW], columns=INVENTORY_COLUMNS).to_csv(path, index=False)
    return path


@pytest.fixture
def hca(tmp_path, inventory):
    return HarmoniCA(models_dir=str(tmp_path / 'models'), inventory_path=str(inventory))


# ---------------------------------------------------------------- per-item source in the engine

def test_each_assignment_says_where_it_comes_from(hca):
    items = [{'item_id': 'PHQ-9_01', 'item_text': INVENTORY_ROW['item_text']},
             {'item_id': 'PHQ-9_02', 'item_text': 'Feeling down, depressed, or hopeless.'}]
    with patch.object(HarmoniCA, '_run_model', _fake_run_model):
        result = hca.harmonize(questionnaire='PHQ-9', construct='depression', items=items)
    assert result['source'] == 'mixed'                                    # the group-level value stays
    assert {a['item_id']: a['source'] for a in result['assignments']} == {'PHQ-9_01': 'inventory', 'PHQ-9_02': 'model'}


def test_source_for_inventory_only_and_model_only_groups(hca):
    with patch.object(HarmoniCA, '_run_model', _fake_run_model):
        only_inventory = hca.harmonize(questionnaire='PHQ-9', construct='depression',
                                       items=[{'item_id': 'PHQ-9_01', 'item_text': INVENTORY_ROW['item_text']}])
        only_model = hca.harmonize(questionnaire='NEW', construct='anxiety',
                                   items=[{'item_id': 'N_1', 'item_text': 'A new statement'}])
    assert [a['source'] for a in only_inventory['assignments']] == ['inventory']
    assert [a['source'] for a in only_model['assignments']] == ['model']


def test_confirmed_duplicate_counts_as_inventory(hca):
    items = [{'item_id': 'MY_1', 'item_text': INVENTORY_ROW['item_text']}]        # same wording, other ID
    same = hca.harmonize(questionnaire='PHQ-9', construct='depression', items=items,
                         confirm_match=lambda user, ref: True)
    assert [a['source'] for a in same['assignments']] == ['inventory']
    with patch.object(HarmoniCA, '_run_model', _fake_run_model):
        new = hca.harmonize(questionnaire='PHQ-9', construct='depression', items=items,
                            confirm_match=lambda user, ref: False)
    assert [a['source'] for a in new['assignments']] == ['model']


def test_enter_at_the_duplicate_prompt_means_same_item(hca):
    items = [{'item_id': 'MY_1', 'item_text': INVENTORY_ROW['item_text']}]
    with patch('builtins.input', return_value=''):
        result = hca.harmonize(questionnaire='PHQ-9', construct='depression', items=items)
    assert result['source'] == 'inventory'


# ---------------------------------------------------------------- CLI alignment

def _fake_harmonize(self, questionnaire, construct, items, force_rerun=False, confirm_match=None):
    """Like the engine: one source per item; calls confirm_match for items found under another ID."""
    out = []
    for it in items:
        reuse = bool(confirm_match and confirm_match(it, {'item_id': 'INV_1'}))
        out.append({'item_id': it['item_id'], 'item_text': it['item_text'], 'dimension': 1, 'dimension_label': 'Dim',
                    'confidence': 0.9, 'source': 'inventory' if reuse else 'model',
                    'probability_distribution': {'1': 0.9, '2': 0.1}})
    return {'assignments': out, 'source': 'mixed', 'questionnaire': questionnaire, 'construct': construct}


def _run_cli(argv, harmonize=_fake_harmonize):
    with patch.object(sys, 'argv', argv), patch.object(HarmoniCA, 'harmonize', harmonize):
        hz.main()


@pytest.fixture
def items_csv(tmp_path):
    path = tmp_path / 'items.csv'
    pd.DataFrame([
        {'construct': 'Depression ', 'questionnaire': 'PHQ-9', 'item_id': 'PHQ-9_01', 'item_text': ' Little interest ',
         'answer_options': '["No", "Yes"]', 'scoring': '[0, 1]'},
        {'construct': 'anxiety', 'questionnaire': 'GAD-7', 'item_id': 'GAD7_01', 'item_text': 'Feeling nervous',
         'answer_options': '["No", "Yes"]', 'scoring': '[0, 1]'},
    ]).to_csv(path, index=False)
    return path


def test_cli_columns_match_the_web_app_and_scoring_is_passed_through(items_csv, inventory, tmp_path):
    _run_cli(['harmonize.py', '--items', str(items_csv), '--inventory', str(inventory)])
    out = pd.read_csv(tmp_path / 'items_harmonized.csv', dtype=str, keep_default_na=False)
    assert list(out.columns) == ['construct', 'questionnaire', 'item_id', 'item_text', 'dimension', 'dimension_label',
                                 'confidence', 'source', 'probability_distribution', 'answer_options', 'scoring']
    assert out['scoring'].tolist() == ['[0, 1]', '[0, 1]']
    assert json.loads(out.loc[0, 'probability_distribution']) == {'1': 0.9, '2': 0.1}


def test_cli_normalises_the_input_like_the_web_app(items_csv, inventory, tmp_path):
    _run_cli(['harmonize.py', '--items', str(items_csv), '--inventory', str(inventory)])
    out = pd.read_csv(tmp_path / 'items_harmonized.csv', dtype=str, keep_default_na=False)
    assert set(out['construct']) == {'depression', 'anxiety'}             # 'Depression ' -> 'depression'
    assert out.loc[out.item_id == 'PHQ-9_01', 'item_text'].item() == 'Little interest'


def test_cli_without_scoring_columns_has_no_scoring_columns(tmp_path, inventory):
    path = tmp_path / 'plain.csv'
    pd.DataFrame([{'construct': 'anxiety', 'questionnaire': 'GAD-7', 'item_id': 'G1', 'item_text': 'Nervous'}]).to_csv(path, index=False)
    _run_cli(['harmonize.py', '--items', str(path), '--inventory', str(inventory)])
    out = pd.read_csv(tmp_path / 'plain_harmonized.csv')
    assert 'scoring' not in out.columns and 'answer_options' not in out.columns


@pytest.mark.parametrize('mode, expected', [('same', 'inventory'), ('new', 'model')])
def test_duplicates_option_decides_without_prompting(items_csv, inventory, tmp_path, mode, expected):
    with patch('builtins.input', side_effect=AssertionError('must not prompt')):
        _run_cli(['harmonize.py', '--items', str(items_csv), '--inventory', str(inventory), '--duplicates', mode])
    out = pd.read_csv(tmp_path / 'items_harmonized.csv')
    assert set(out['source']) == {expected}


def test_cli_still_works_with_an_engine_that_reports_one_source_per_questionnaire(items_csv, inventory, tmp_path):
    def old_style(self, questionnaire, construct, items, force_rerun=False):
        return {'assignments': [{'item_id': it['item_id'], 'item_text': it['item_text'], 'dimension': 1,
                                 'dimension_label': 'Dim', 'confidence': 0.9} for it in items],
                'source': 'model', 'questionnaire': questionnaire, 'construct': construct}
    _run_cli(['harmonize.py', '--items', str(items_csv), '--inventory', str(inventory)], harmonize=old_style)
    out = pd.read_csv(tmp_path / 'items_harmonized.csv')
    assert set(out['source']) == {'model'}
