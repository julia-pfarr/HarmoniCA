"""
Tests for the Gradio app's core logic (harmonica/app.py): detect(),
run_harmonization(), and browse_inventory(). These call the plain Python
functions directly — no Gradio server is started.
"""
from pathlib import Path

import pandas as pd
import pytest
from unittest.mock import patch

gr = pytest.importorskip("gradio")

import harmonica.app as app
from harmonica.harmonica import HarmoniCA

INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire',
    'dimension', 'dimension_label', 'confidence',
    'source', 'date_added', 'model_version',
]


def _fake_run_model(calls):
    def _run(self, construct, items):
        calls.append([it['item_id'] for it in items])
        return [
            {
                'item_id': it['item_id'],
                'item_text': it['item_text'],
                'dimension': 1,
                'dimension_label': 'Test Dim',
                'confidence': 0.9,
            }
            for it in items
        ]
    return _run


@pytest.fixture(autouse=True)
def fresh_hca(tmp_path, monkeypatch):
    """Point the app at a fresh, isolated HarmoniCA instance + inventory for each test."""
    inventory_path = tmp_path / 'inventory.csv'
    pd.DataFrame([
        {
            'item_id': 'PHQ-9_01', 'item_text': 'Little interest or pleasure in doing things.',
            'construct': 'depression', 'questionnaire': 'PHQ-9',
            'dimension': 4, 'dimension_label': 'Activity & interest deficits',
            'confidence': 0.9, 'source': 'expert_consensus',
            'date_added': '2026-01-01', 'model_version': 'ft',
        },
    ], columns=INVENTORY_COLUMNS).to_csv(inventory_path, index=False)

    monkeypatch.setattr(app, 'DEFAULT_INVENTORY', inventory_path)
    hca = HarmoniCA(models_dir=str(tmp_path / 'models'), inventory_path=str(inventory_path))
    monkeypatch.setattr(app, '_hca', hca)
    return hca


@pytest.fixture
def items_csv(tmp_path):
    path = tmp_path / 'items.csv'
    pd.DataFrame([
        {'construct': 'depression', 'questionnaire': 'PHQ-9', 'item_id': 'PHQ-9_01',
         'item_text': 'Little interest or pleasure in doing things.'},
        {'construct': 'depression', 'questionnaire': 'PHQ-9', 'item_id': 'PHQ9_2',
         'item_text': 'Feeling down, depressed, or hopeless.'},
    ]).to_csv(path, index=False)
    return path


def test_detect_reports_cached_and_new_items(items_csv):
    state, summary, review_df, review_visible, _run_btn_update = app.detect(str(items_csv))

    assert len(state['groups']) == 1
    assert '1 item(s) already in the inventory' in summary
    assert '1 new item(s)' in summary
    assert len(review_df) == 0
    assert dict(review_visible)['visible'] is False


def test_detect_surfaces_id_mismatch_candidates(tmp_path):
    items_path = tmp_path / 'items.csv'
    pd.DataFrame([
        {'construct': 'depression', 'questionnaire': 'PHQ-9', 'item_id': 'PHQ9_1',
         'item_text': 'Little interest or pleasure in doing things.'},
    ]).to_csv(items_path, index=False)

    _state, summary, review_df, review_visible, _ = app.detect(str(items_path))

    assert len(review_df) == 1
    assert review_df.iloc[0]['your_item_id'] == 'PHQ9_1'
    assert review_df.iloc[0]['matched_inventory_item_id'] == 'PHQ-9_01'
    assert bool(review_df.iloc[0]['same_item?']) is True
    assert dict(review_visible)['visible'] is True
    assert '1 possible duplicate(s)' in summary


def test_detect_raises_on_missing_columns(tmp_path):
    bad_path = tmp_path / 'bad.csv'
    pd.DataFrame([{'construct': 'depression', 'item_id': 'x'}]).to_csv(bad_path, index=False)

    with pytest.raises(gr.Error):
        app.detect(str(bad_path))


def test_detect_raises_without_file():
    with pytest.raises(gr.Error):
        app.detect(None)


def test_run_harmonization_reuses_cached_and_runs_model_for_new(items_csv):
    calls = []
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(calls)):
        state, *_ = app.detect(str(items_csv))
        results_df, out_path = app.run_harmonization(
            state, pd.DataFrame(columns=app.REVIEW_COLUMNS), force_rerun=False
        )

    assert calls == [['PHQ9_2']]  # only the genuinely new item hit the model
    by_id = dict(zip(results_df['item_id'], results_df['dimension']))
    assert by_id['PHQ-9_01'] == 4  # served from inventory
    assert by_id['PHQ9_2'] == 1    # freshly predicted
    assert Path(out_path).exists()


def test_run_harmonization_respects_review_decisions(tmp_path):
    items_path = tmp_path / 'items.csv'
    pd.DataFrame([
        {'construct': 'depression', 'questionnaire': 'PHQ-9', 'item_id': 'PHQ9_1',
         'item_text': 'Little interest or pleasure in doing things.'},
    ]).to_csv(items_path, index=False)

    calls = []
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(calls)):
        state, _, review_df, _, _ = app.detect(str(items_path))

        # User unchecks "same_item?" -> should run through the model instead of reusing
        review_df['same_item?'] = False
        results_df, _ = app.run_harmonization(state, review_df, force_rerun=False)

    assert calls == [['PHQ9_1']]
    assert results_df.iloc[0]['dimension'] == 1  # freshly predicted, not the inventory's 4


def test_run_harmonization_without_detect_raises():
    with pytest.raises(gr.Error):
        app.run_harmonization(None, None, False)


def test_browse_inventory_filters_by_construct(fresh_hca):
    inv, count = app.browse_inventory('depression', '', '')
    assert count == '1 item(s)'
    assert len(inv) == 1

    inv, count = app.browse_inventory('anxiety', '', '')
    assert count == '0 item(s)'


def test_browse_inventory_filters_by_text(fresh_hca):
    inv, _count = app.browse_inventory('All', '', 'little interest')
    assert len(inv) == 1

    inv, _count = app.browse_inventory('All', '', 'nonexistent phrase')
    assert len(inv) == 0
