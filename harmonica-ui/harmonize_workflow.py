"""Data helpers and guided UI for harmonizing questionnaire definitions."""
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st


ITEM_COLUMNS = [
    'construct', 'questionnaire', 'item_id', 'item_text', 'answer_options', 'scoring',
]
INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire', 'dimension',
    'dimension_label', 'confidence', 'source', 'date_added', 'model_version',
]
def persistent_inventory_path():
    configured = os.environ.get('HARMONICA_INVENTORY_PATH')
    if configured:
        return Path(configured).expanduser().resolve()
    project_inventory = Path(__file__).resolve().parent.parent / 'src' / 'harmonica' / 'inventory' / 'harmonized_inventory.csv'
    if project_inventory.is_file():
        return project_inventory
    return Path(__file__).resolve().parent / 'assets' / 'harmonized_inventory.csv'


def validate_items(frame, supported_constructs):
    frame = frame.copy()
    frame.columns = frame.columns.astype(str).str.strip()
    if frame.columns.duplicated().any():
        raise ValueError('Column names must be unique.')
    missing = [column for column in ITEM_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError('Missing required columns: ' + ', '.join(missing))
    frame = frame[ITEM_COLUMNS].fillna('').astype(str)
    for column in ITEM_COLUMNS:
        frame[column] = frame[column].str.strip()
    frame['construct'] = frame['construct'].str.lower()
    if frame.empty:
        raise ValueError('The input contains no items.')
    if len(frame) > 10000:
        raise ValueError('Please use at most 10,000 items per run.')
    empty_rows = frame.eq('').any(axis=1)
    if empty_rows.any():
        raise ValueError('Required values are empty on row(s): ' + ', '.join(str(i + 1) for i in frame.index[empty_rows][:10]))
    repeated_ids = frame['item_id'].duplicated(keep=False)
    if repeated_ids.any():
        duplicates = frame.loc[repeated_ids, 'item_id'].drop_duplicates().tolist()
        raise ValueError('Repeated item_id values: ' + ', '.join(duplicates[:10]))
    unknown = sorted(set(frame['construct']) - set(supported_constructs))
    if unknown:
        raise ValueError('Unsupported constructs: ' + ', '.join(unknown) + '. Supported: ' + ', '.join(supported_constructs))
    return frame.reset_index(drop=True)


def _normalize(text):
    return ' '.join(str(text).strip().lower().split()).strip(' .?!"\'')


def load_inventory(reference_path, persistent_path=None):
    paths = [Path(reference_path)]
    if persistent_path is not None and Path(persistent_path).resolve() != paths[0].resolve():
        paths.append(Path(persistent_path))
    frames = []
    for path in paths:
        if path.is_file():
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            if {'item_id', 'item_text', 'construct', 'questionnaire', 'dimension', 'dimension_label', 'confidence'}.issubset(frame.columns):
                frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=INVENTORY_COLUMNS)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined.drop_duplicates(['construct', 'questionnaire', 'item_id'], keep='last').reset_index(drop=True)


def classify_items(items, inventory):
    """Attach a route and matching inventory row to every validated input item."""
    exact = {}
    same_text = {}
    for row in inventory.to_dict('records'):
        key = (row['construct'], row['questionnaire'], row['item_id'])
        exact[key] = row
        text_key = (row['construct'], row['questionnaire'], _normalize(row['item_text']))
        same_text.setdefault(text_key, row)

    routed = items.copy()
    routes, matches = [], []
    for row in items.to_dict('records'):
        key = (row['construct'], row['questionnaire'], row['item_id'])
        existing = exact.get(key)
        if existing is not None and _normalize(existing['item_text']) == _normalize(row['item_text']):
            route, match = 'inventory', existing
        else:
            text_key = (row['construct'], row['questionnaire'], _normalize(row['item_text']))
            candidate = same_text.get(text_key)
            if candidate is not None and candidate['item_id'] != row['item_id']:
                route, match = 'duplicate', candidate
            else:
                route, match = 'new', {}
        routes.append(route)
        matches.append(match)
    routed['route'] = routes
    routed['matched_item_id'] = [row.get('item_id', '') for row in matches]
    routed['matched_item_text'] = [row.get('item_text', '') for row in matches]
    routed['matched_dimension_label'] = [row.get('dimension_label', '') for row in matches]
    routed['same_item?'] = [route == 'duplicate' for route in routes]
    return routed


def append_model_predictions(inventory_path, predictions, model_versions):
    """Persist only fresh model assignments, replacing stale rows with the same key."""
    path = Path(inventory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = (pd.read_csv(path, dtype=str, keep_default_na=False)
                if path.is_file() else pd.DataFrame(columns=INVENTORY_COLUMNS))
    existing = existing.reindex(columns=INVENTORY_COLUMNS, fill_value='')
    added_at = datetime.now(timezone.utc).isoformat()
    additions = []
    for row in predictions.to_dict('records'):
        additions.append({
            'item_id': row['item_id'],
            'item_text': row['item_text'],
            'construct': row['construct'],
            'questionnaire': row['questionnaire'],
            'dimension': row['dimension'],
            'dimension_label': row['dimension_label'],
            'confidence': row['confidence'],
            'source': 'model_prediction',
            'date_added': added_at,
            'model_version': model_versions.get(row['construct'], ''),
        })
    if not additions:
        return 0
    new_rows = pd.DataFrame(additions, columns=INVENTORY_COLUMNS)
    keys = ['construct', 'questionnaire', 'item_id']
    replace_keys = set(map(tuple, new_rows[keys].astype(str).to_numpy()))
    if not existing.empty:
        keep = ~existing[keys].astype(str).apply(tuple, axis=1).isin(replace_keys)
        existing = existing.loc[keep]
    combined = pd.concat([existing, new_rows], ignore_index=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent,
                                     suffix='.tmp', delete=False) as temporary:
        temporary_path = Path(temporary.name)
        combined.to_csv(temporary, index=False)
    os.replace(temporary_path, path)
    return len(new_rows)


def _set_stage(stage):
    st.session_state.workflow_stage = stage


def _stepper(stage):
    labels = ('Enter items', 'Review inventory', 'Results')
    columns = st.columns(len(labels))
    for index, (column, label) in enumerate(zip(columns, labels), start=1):
        state = 'Complete' if index < stage else 'Current' if index == stage else 'Upcoming'
        column.markdown(f'**{index}. {label}**')
        column.caption(state)


def _read_manual_queue(supported_constructs):
    if 'workflow_manual_items' not in st.session_state:
        st.session_state.workflow_manual_items = []
    st.markdown('#### Add an item')
    with st.form('workflow_manual_entry'):
        first, second, third = st.columns(3)
        construct = first.selectbox('Construct', supported_constructs, key='workflow_manual_construct')
        questionnaire = second.text_input('Questionnaire')
        item_id = third.text_input('Item ID')
        item_text = st.text_area('Item wording')
        answer_options, scoring = st.columns(2)
        options_value = answer_options.text_input('Answer options', placeholder='[0, 1, 2, 3]')
        scoring_value = scoring.text_input('Scoring', placeholder='[0, 1, 2, 3]')
        add_item = st.form_submit_button('Add item')
    if add_item:
        candidate = pd.DataFrame([{
            'construct': construct,
            'questionnaire': questionnaire,
            'item_id': item_id,
            'item_text': item_text,
            'answer_options': options_value,
            'scoring': scoring_value,
        }])
        try:
            validated = validate_items(candidate, supported_constructs)
            queued_ids = {row['item_id'] for row in st.session_state.workflow_manual_items}
            if validated.iloc[0]['item_id'] in queued_ids:
                raise ValueError('This item_id is already in the manual entry list.')
            st.session_state.workflow_manual_items.extend(validated.to_dict('records'))
            st.success('Item added.')
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.workflow_manual_items:
        queued_items = pd.DataFrame(st.session_state.workflow_manual_items, columns=ITEM_COLUMNS)
        editor_key = hashlib.sha256(queued_items.to_csv(index=False).encode()).hexdigest()[:12]
        with st.form('workflow_manual_items_form'):
            edited_items = st.data_editor(queued_items, hide_index=True, num_rows='fixed', width='stretch',
                                          key='workflow_manual_items_'+editor_key)
            save_changes = st.form_submit_button('Save item changes')
        if save_changes:
            try:
                validated = validate_items(edited_items, supported_constructs)
                st.session_state.workflow_manual_items = validated.to_dict('records')
                st.success('Manual item changes saved.')
            except ValueError as exc:
                st.error(str(exc))
        item_ids = [row['item_id'] for row in st.session_state.workflow_manual_items]
        remove_key = hashlib.sha256('\0'.join(item_ids).encode()).hexdigest()[:12]
        remove_ids = st.multiselect('Remove items', item_ids, key='workflow_manual_remove_'+remove_key)
        if remove_ids:
            st.session_state.workflow_manual_items = [row for row in st.session_state.workflow_manual_items
                                                      if row['item_id'] not in remove_ids]
            st.rerun()
    return pd.DataFrame(st.session_state.workflow_manual_items, columns=ITEM_COLUMNS)


REVIEW_COLUMNS = ['same_item?', 'construct', 'questionnaire', 'item_id', 'item_text', 'answer_options', 'scoring',
                  'matched_item_id', 'matched_item_text', 'matched_dimension_label']


def duplicate_review_editor(duplicates, key, locked=False):
    """Editable possible duplicates table, same_item? first so it is always visible.

    Used by the manual entry review and by the Inventory check step for uploaded files, so both
    sources answer the same question the same way. `duplicates` needs the matched_* columns
    from classify_items. Columns an input does not have (for example answer_options for items
    taken from the reference inventory) are left out. Returns the table with the edited same_item?.
    """
    columns = [column for column in REVIEW_COLUMNS if column in duplicates.columns]
    return st.data_editor(
        duplicates[columns], hide_index=True, width='stretch',
        disabled=True if locked else [column for column in columns if column != 'same_item?'],
        column_config={'same_item?': st.column_config.CheckboxColumn('same_item?', default=True)},
        key=key,
    )


def _review_groups(routed):
    exact = routed[routed['route'] == 'inventory']
    duplicates = routed[routed['route'] == 'duplicate']
    new_items = routed[routed['route'] == 'new']
    st.subheader(f'Already in inventory · {len(exact)}')
    if exact.empty:
        st.caption('No exact inventory matches.')
    else:
        st.dataframe(exact[ITEM_COLUMNS + ['matched_dimension_label']], hide_index=True, width='stretch')

    st.subheader(f'Possible duplicates · {len(duplicates)}')
    if duplicates.empty:
        st.caption('No same-text items under a different item_id.')
        edited_duplicates = duplicates
    else:
        edited_duplicates = duplicate_review_editor(duplicates, 'workflow_duplicate_review')
        st.caption('Keep checked to reuse the inventory assignment. Uncheck items that should be treated as new.')

    st.subheader(f'New items · {len(new_items)}')
    if new_items.empty:
        st.caption('No new items need model processing.')
    else:
        st.dataframe(new_items[ITEM_COLUMNS], hide_index=True, width='stretch')
    return edited_duplicates


def render_manual_workflow(catalog, on_continue):
    stage = st.session_state.get('workflow_stage', 1)
    stage = max(1, min(stage, 2))
    _stepper(stage)
    inventory_file = persistent_inventory_path()
    reference_file = Path(__file__).resolve().parent / 'assets' / 'reference_inventory.csv'

    if stage == 1:
        st.subheader('Add questionnaire items')
        st.caption('Provide construct, questionnaire, item_id, item_text, answer_options, and scoring for every item.')
        st.download_button('Download six-column template',
                           pd.DataFrame(columns=ITEM_COLUMNS).to_csv(index=False),
                           'harmonica_items_template.csv', 'text/csv')
        items = _read_manual_queue(catalog['CONSTRUCTS'])
        if items is None or items.empty:
            st.info('Add at least one complete item before checking the inventory.')
        if st.button('Continue to Inventory check', type='primary',
                     disabled=items is None or items.empty, key='workflow_check_inventory'):
            try:
                inventory = load_inventory(reference_file, inventory_file)
                routed = classify_items(items, inventory)
                st.session_state.workflow_items = items
                st.session_state.workflow_routed = routed
                st.session_state.workflow_inventory = inventory
                st.session_state.workflow_inventory_path = str(inventory_file)
                _set_stage(2)
                st.rerun()
            except Exception as exc:
                st.error(f'Could not check the inventory: {exc}')
        return

    if stage == 2:
        items = st.session_state.get('workflow_items')
        routed = st.session_state.get('workflow_routed')
        inventory = st.session_state.get('workflow_inventory')
        if items is None or routed is None or inventory is None:
            st.warning('Start by entering or uploading items.')
            st.button('Enter items', on_click=_set_stage, args=(1,))
            return
        st.subheader('Review inventory matches')
        edited_duplicates = _review_groups(routed)
        if not edited_duplicates.empty:
            routed.loc[routed['route'] == 'duplicate', 'same_item?'] = edited_duplicates['same_item?'].to_numpy()
            st.session_state.workflow_routed = routed
        reuse_keys = {
            (row['construct'], row['questionnaire'], row['item_id'])
            for row in routed.to_dict('records')
            if row['route'] == 'duplicate' and bool(row['same_item?'])
        }
        items = items.copy()
        items['reuse_match'] = [
            (row['construct'], row['questionnaire'], row['item_id']) in reuse_keys
            for row in items.to_dict('records')
        ]
        st.session_state.workflow_items = items
        left, right = st.columns(2)
        left.button('Back to items', on_click=_set_stage, args=(1,), key='workflow_back_to_items')
        right.button('Continue to Inventory check', type='primary', on_click=on_continue,
                     key='workflow_continue_to_check')
        return
