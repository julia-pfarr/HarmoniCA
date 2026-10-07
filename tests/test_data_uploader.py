"""Tests for the Data Harmonizer tab handlers (harmonica.uploader.tab)."""
from unittest.mock import patch

import pandas as pd
import pytest

gr = pytest.importorskip("gradio")

import harmonica.app as app
from harmonica.harmonica import HarmoniCA
from harmonica.uploader.rules import UPLOAD_COLUMNS
from harmonica.uploader.tab import UploaderTab

INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire', 'dimension',
    'dimension_label', 'confidence', 'source', 'date_added', 'model_version',
]


def _inv_row(item_id, text):
    return [item_id, text, 'depression', 'PHQ-9', 1, 'Mood', 0.9, 'expert_consensus', '2026-01-01', 'ft']


@pytest.fixture
def inventory_path(tmp_path):
    path = tmp_path / 'inventory.csv'
    pd.DataFrame([
        _inv_row('PHQ-9_01', 'Little interest or pleasure in doing things.'),
        _inv_row('PHQ-9_02', 'Feeling down, depressed, or hopeless.'),
    ], columns=INVENTORY_COLUMNS).to_csv(path, index=False)
    return path


@pytest.fixture
def tab(tmp_path, inventory_path):
    hca = HarmoniCA(models_dir=str(tmp_path / 'models'), inventory_path=str(inventory_path))
    return UploaderTab(get_hca=lambda: hca)


def _row(item_id, text, construct='depression'):
    return [construct, 'PHQ-9', item_id, text, '["No", "Yes"]', '[0, 1]']


def _csv(tmp_path, rows, name='items.csv'):
    path = tmp_path / name
    pd.DataFrame(rows, columns=UPLOAD_COLUMNS).to_csv(path, index=False)
    return str(path)


# --- same rules as "Check inventory" ----------------------------------------

def test_unknown_construct_rejected(tab, tmp_path):
    with pytest.raises(gr.Error) as exc:
        tab.process_upload(_csv(tmp_path, [_row('X_1', 'Some text', construct='dep')]))
    assert "Unknown construct(s): dep." in exc.value.message
    assert 'Download sample CSV' in exc.value.message


def test_empty_cell_rejected(tab, tmp_path):
    with pytest.raises(gr.Error) as exc:
        tab.process_upload(_csv(tmp_path, [_row('X_1', '')]))
    assert 'missing item_text' in exc.value.message


def test_missing_column_rejected_with_sample_hint(tab, tmp_path):
    path = tmp_path / 'bad.csv'
    pd.DataFrame([{'construct': 'depression', 'item_id': 'x'}]).to_csv(path, index=False)
    with pytest.raises(gr.Error) as exc:
        tab.process_upload(str(path))
    assert 'Download sample CSV' in exc.value.message


def test_header_only_file_needs_one_row(tab, tmp_path):
    with pytest.raises(gr.Error) as exc:
        tab.process_upload(_csv(tmp_path, []))
    assert 'At least one row is required' in exc.value.message
    assert 'format did not match' not in exc.value.message


def test_harmonize_and_uploader_agree_on_counts(tab, tmp_path, inventory_path, monkeypatch):
    rows = [
        _row('PHQ-9_01', 'Little interest or pleasure in doing things.'),
        _row('PHQ9_2', 'Feeling down, depressed, or hopeless.'),
        _row('PHQ9_NEW', 'A completely new item.'),
    ]
    path = _csv(tmp_path, rows)
    monkeypatch.setattr(app, 'DEFAULT_INVENTORY', inventory_path)
    monkeypatch.setattr(app, '_hca', HarmoniCA(models_dir=str(tmp_path / 'm'), inventory_path=str(inventory_path)))
    _state, summary, review_df, *_ = app.detect(path)  # Harmonize tab

    _preview, msg, _group, cached, dupes, new = tab.show_preview(tab.process_upload(path))  # Data Harmonizer
    assert '1 item(s) already in the inventory' in summary and len(review_df) == 1
    assert '1 already in the inventory' in msg and '1 possible duplicate(s)' in msg and '1 new' in msg
    assert [dict(u)['visible'] for u in (cached, dupes, new)] == [True, True, True]
    assert dict(cached)['value']['item_id'].tolist() == ['PHQ-9_01']
    assert dict(cached)['value'].iloc[0]['dimension_label'] == 'Mood'   # the stored assignment
    assert dict(dupes)['value']['your_item_id'].tolist() == ['PHQ9_2']
    assert dict(new)['value']['item_id'].tolist() == ['PHQ9_NEW']


# --- preview / confirm / cancel ---------------------------------------------

def test_preview_without_duplicates_hides_duplicates_table(tab, tmp_path):
    pending = tab.process_upload(_csv(tmp_path, [_row('NEW_1', 'A completely new item.')]))
    _p, msg, group, cached, dupes, new = tab.show_preview(pending)
    assert '1 new' in msg and dict(group)['visible'] is True
    assert dict(cached)['visible'] is False and dict(dupes)['visible'] is False  # nothing to show
    assert dict(new)['visible'] is True


def test_preview_changes_nothing(tab, tmp_path, inventory_path):
    before = inventory_path.read_text()
    tab.show_preview(tab.process_upload(_csv(tmp_path, [_row('NEW_1', 'A completely new item.')])))
    assert inventory_path.read_text() == before          # a preview never writes to the inventory


def test_nothing_is_stored_besides_the_inventory(tab, tmp_path):
    assert not hasattr(tab, 'store')                      # no uploaded_items.csv any more
    with pytest.raises(gr.Error) as exc:
        tab.check_pending(None)
    assert 'Nothing to harmonize' in exc.value.message


# --- manual entry -----------------------------------------------------------

def test_manual_add_delete_and_review(tab):
    empty = pd.DataFrame(columns=UPLOAD_COLUMNS)
    out = tab.add_item('depression', 'PHQ-9', 'NEW_1', 'A new item.', 'a', '1', empty)
    table, summary = out[0], out[-1]
    assert len(table) == 1 and '1 item(s) in your list' in summary and '1 new' in summary

    with pytest.raises(gr.Error):  # empty form
        tab.check_item('', '', '', '', '', '', table)
    with pytest.raises(gr.Error):  # same item_id twice in the list
        tab.check_item('depression', 'PHQ-9', 'NEW_1', 'Again', 'a', '1', table)
    with pytest.raises(gr.Error):  # delete without selecting a row
        tab.check_delete(table, None)

    staged = tab.stage_items(table)                       # "Review and harmonize" step 1
    _p, msg, group, *_ = tab.show_preview(staged)         # step 2: the same preview as a CSV upload
    assert '1 new' in msg and dict(group)['visible'] is True

    after_delete = tab.delete_selected_row(table, 0)[0]
    assert len(after_delete) == 0
    with pytest.raises(gr.Error) as exc:                  # nothing left to review
        tab.stage_items(after_delete)
    assert 'At least one row is required' in exc.value.message


# --- Run harmonization ---------------------------------------------------

def _fake_run_model(calls):
    def _run(self, construct, items):
        calls.append([it['item_id'] for it in items])
        return [{'item_id': it['item_id'], 'item_text': it['item_text'], 'dimension': 1,
                 'dimension_label': 'Test Dim', 'confidence': 0.9} for it in items]
    return _run


MIXED = [
    _row('PHQ-9_01', 'Little interest or pleasure in doing things.'),   # in inventory
    _row('PHQ9_2', 'Feeling down, depressed, or hopeless.'),            # same text, other ID
    _row('PHQ9_NEW', 'A completely new item.'),                         # new
]


def test_preview_says_model_runs_only_for_new_items(tab, tmp_path):
    _p, msg, *_ = tab.show_preview(tab.process_upload(_csv(tmp_path, MIXED)))
    assert 'only for the 1 new item(s)' in msg
    assert 'Run harmonization' in msg and 'Nothing else is saved' in msg


def test_harmonize_runs_model_only_for_new_and_updates_inventory(tab, tmp_path, inventory_path):
    pending = tab.process_upload(_csv(tmp_path, MIXED))
    _p, _msg, _g, _cached, dupes, _new = tab.show_preview(pending)
    calls = []
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(calls)):
        out = tab.harmonize_items(pending, dict(dupes)['value'])  # duplicate left as "same item"

    assert calls == [['PHQ9_NEW']]                                    # only the new item hit the model
    inventory = pd.read_csv(inventory_path)
    assert len(inventory) == 2 + 1 and 'PHQ9_NEW' in set(inventory['item_id'])
    results = out[5]
    assert len(results) == 3 and set(results['item_id']) == {'PHQ-9_01', 'PHQ9_2', 'PHQ9_NEW'}
    assert 'only for 1 new item(s)' in out[4] and 'the other 2 were reused' in out[4]
    assert dict(out[1])['visible'] is False and dict(out[3])['visible'] is True


def test_unchecked_duplicate_is_treated_as_new(tab, tmp_path):
    pending = tab.process_upload(_csv(tmp_path, MIXED))
    _p, _msg, _g, _cached, dupes, _new = tab.show_preview(pending)
    review = dict(dupes)['value'].copy()
    review['same_item?'] = False                                      # user says: different item
    calls = []
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(calls)):
        out = tab.harmonize_items(pending, review)
    assert len(calls) == 1 and sorted(calls[0]) == ['PHQ9_2', 'PHQ9_NEW']   # one model run, both items
    assert 'only for 2 new item(s)' in out[4]


def test_harmonizing_the_same_items_again_does_not_rerun_the_model(tab, tmp_path):
    pending = tab.process_upload(_csv(tmp_path, MIXED))
    first, second = [], []
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(first)):
        tab.harmonize_items(pending, None)
    with patch.object(HarmoniCA, '_run_model', _fake_run_model(second)):
        out = tab.harmonize_items(pending, None)
    assert first == [['PHQ9_NEW']] and second == []       # now everything is in the inventory
    assert 'only for 0 new item(s)' in out[4]


def test_running_ui_updates_match_the_components(tab):
    # outputs are [note, progress slot, Run harmonization, Cancel]: Gradio warns on any mismatch
    assert len(tab.show_running()) == 4 and len(tab.reset_run_ui()) == 4
