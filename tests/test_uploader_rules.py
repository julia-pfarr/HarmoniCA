"""Gradio-free tests for the rules and the inventory check of the uploader."""
import pandas as pd
import pytest

from harmonica.harmonica import HarmoniCA
from harmonica.harmonica.config import CONSTRUCTS
from harmonica.uploader.inventory_check import check_items_against_inventory
from harmonica.uploader.rules import (
    UPLOAD_COLUMNS, EmptyUploadError, ItemsFormatError, check_constructs, validate_items,
)

INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire', 'dimension',
    'dimension_label', 'confidence', 'source', 'date_added', 'model_version',
]


def row(item_id='X_1', text='Some text', construct='depression'):
    return [construct, 'Q', item_id, text, 'a', '1']


def frame(*rows):
    return pd.DataFrame(list(rows), columns=UPLOAD_COLUMNS)


# --- rules -----------------------------------------------------------------

def test_valid_rows_are_returned_clean():
    out = validate_items(frame([' depression ', 'Q', 'X_1', ' text ', 'a', '1']), CONSTRUCTS)
    assert out.loc[0, 'construct'] == 'depression' and out.loc[0, 'item_text'] == 'text'


def test_missing_column():
    with pytest.raises(ItemsFormatError, match='Missing column'):
        validate_items(pd.DataFrame([{'construct': 'depression'}]), CONSTRUCTS)


def test_no_rows():
    with pytest.raises(EmptyUploadError):
        validate_items(frame(), CONSTRUCTS)
    with pytest.raises(EmptyUploadError):
        validate_items(frame(['', '', '', '', '', '']), CONSTRUCTS)


def test_unknown_construct_matches_harmonize_wording():
    with pytest.raises(ItemsFormatError, match=r"Unknown construct\(s\): dep\."):
        validate_items(frame(row(construct='dep')), CONSTRUCTS)
    with pytest.raises(ItemsFormatError, match=r"Unknown construct\(s\): dep\."):
        check_constructs(['dep'], CONSTRUCTS)  # the function used by detect() on the Harmonize tab


@pytest.mark.parametrize('bad_col', range(len(UPLOAD_COLUMNS)))
def test_every_empty_cell_is_rejected(bad_col):
    r = row()
    r[bad_col] = ''
    with pytest.raises(ItemsFormatError, match='missing'):
        validate_items(frame(r, row('X_2')), CONSTRUCTS)


def test_any_text_allowed_in_answer_options_and_scoring():
    out = validate_items(frame(['depression', 'Q', 'X_1', 't', 'Never, Always', '0,1']), CONSTRUCTS)
    assert out.loc[0, 'answer_options'] == 'Never, Always'


def test_duplicate_item_id_in_file():
    with pytest.raises(ItemsFormatError, match='Duplicate item_id'):
        validate_items(frame(row('X_1'), row('X_1')), CONSTRUCTS)


# --- inventory check (shared with Harmonize) -------------------------------

@pytest.fixture
def hca(tmp_path):
    inv = tmp_path / 'inv.csv'
    pd.DataFrame([
        ['PHQ-9_01', 'Little interest or pleasure in doing things.', 'depression', 'PHQ-9', 4, 'x', .9, 'e', '', ''],
        ['PHQ-9_02', 'Feeling down, depressed, or hopeless.', 'depression', 'PHQ-9', 1, 'y', .8, 'e', '', ''],
    ], columns=INVENTORY_COLUMNS).to_csv(inv, index=False)
    return HarmoniCA(models_dir=str(tmp_path / 'm'), inventory_path=str(inv))


def test_report_counts_and_does_not_write_inventory(hca):
    before = hca.inventory_path.read_text()
    items = pd.DataFrame({
        'construct': 'depression', 'questionnaire': 'PHQ-9',
        'item_id': ['PHQ-9_01', 'PHQ9_2', 'NEW'],
        'item_text': ['Little interest or pleasure in doing things.',
                      'Feeling down, depressed, or hopeless.', 'A brand new item.'],
        'answer_options': '["No", "Yes"]', 'scoring': '[0, 1]',
    })
    report = check_items_against_inventory(items, hca)
    assert (report.n_cached, report.n_duplicates, report.n_new) == (1, 1, 1)
    assert '1 already in the inventory' in report.summary()
    assert report.duplicates_table().iloc[0]['matched_inventory_item_id'] == 'PHQ-9_02'
    assert report.cached_table()['item_id'].tolist() == ['PHQ-9_01']
    assert report.cached_table().iloc[0]['dimension_label'] == 'x'      # assignment already stored
    assert report.new_table()['item_id'].tolist() == ['NEW']
    assert report.new_table().columns.tolist()[-2:] == ['answer_options', 'scoring']
    assert report.new_table().iloc[0]['scoring'] == '[0, 1]'            # carried over from the upload
    assert hca.inventory_path.read_text() == before
    # callers that only pass the four core columns (the Harmonize tab) still work
    bare = check_items_against_inventory(items[['construct', 'questionnaire', 'item_id', 'item_text']], hca)
    assert bare.new_table().iloc[0]['scoring'] == ''
