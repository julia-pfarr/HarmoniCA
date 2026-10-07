"""CLI adapter: no shell interpolation and no invented HarmoniCA predictions."""
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import pandas as pd

COLUMNS = ['construct', 'questionnaire', 'item_id', 'item_text']
SEPARATORS = [',', ';', '\t']


def load_ui_inventory():
    root = Path(__file__).resolve().parent
    reference_path = root/'assets'/'reference_inventory.csv'
    configured = os.environ.get('HARMONICA_INVENTORY_PATH')
    persistent_path = (Path(configured).expanduser() if configured else
                       root.parent/'src'/'harmonica'/'inventory'/'harmonized_inventory.csv')
    paths = [reference_path]
    if persistent_path.resolve() != reference_path.resolve() and persistent_path.is_file():
        paths.append(persistent_path)
    frames = [pd.read_csv(path, dtype=str, keep_default_na=False) for path in paths]
    inventory = pd.concat(frames, ignore_index=True, sort=False)
    return inventory.drop_duplicates(['construct', 'questionnaire', 'item_id'], keep='last').reset_index(drop=True)


def detect_separator(data):
    """Guess the CSV separator from the header line, which (unlike item texts)
    rarely contains commas. Excel in e.g. French locales saves with ';'."""
    header = data[:65536].decode('utf-8-sig', errors='replace').splitlines()[:1]
    if not header:
        return ','
    counts = {sep: header[0].count(sep) for sep in SEPARATORS}
    best = max(SEPARATORS, key=lambda sep: counts[sep])
    return best if counts[best] else ','


def parse_items(data):
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except Exception as exc:
        raise ValueError(f'Cannot read CSV: {exc}') from exc
    df.columns = df.columns.str.strip()
    if df.columns.duplicated().any():
        raise ValueError('Column names must be unique.')
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError('Missing columns: ' + ', '.join(sorted(missing)))
    df = df[COLUMNS].copy()
    for col in COLUMNS:
        df[col] = df[col].str.strip()
    df['construct'] = df['construct'].str.lower()
    if df.empty:
        raise ValueError('The CSV contains no items.')
    if len(df) > 10000:
        raise ValueError('Please use at most 10,000 items per run.')
    bad = df.eq('').any(axis=1)
    if bad.any():
        raise ValueError('Required values are empty on CSV line(s): ' + ', '.join(str(i+2) for i in df.index[bad][:10]))
    if df.duplicated(['construct', 'questionnaire', 'item_id']).any():
        raise ValueError('Duplicate item IDs within the same questionnaire and construct. Resolve them before running.')
    return df


def _normalize(text):
    # Same normalisation as engine_worker.py and the upstream engine
    return ' '.join(str(text).strip().lower().split()).strip(' .?!"\'')


def inventory_check(df, force=False):
    """Classify items the way the engine will treat them, without running it.

    Returns a copy of `df` with a 'route' column:
      'inventory' — exact match (same construct, questionnaire, item_id and wording): reused
      'duplicate' — same wording as an inventory item under a different item_id: sent to the model
      'new'       — not in the inventory: sent to the model
    With `force`, every item is sent to the model: exact matches become 'new' (they
    are re-run, not duplicates).
    """
    inv = load_ui_inventory()
    inv_key = {(r.construct, r.questionnaire, r.item_id): _normalize(r.item_text) for r in inv.itertuples()}
    inv_text = {(r.construct, r.questionnaire, _normalize(r.item_text)) for r in inv.itertuples()}
    routes = []
    for r in df.itertuples():
        text = _normalize(r.item_text)
        if inv_key.get((r.construct, r.questionnaire, r.item_id)) == text:
            routes.append('new' if force else 'inventory')
        elif (r.construct, r.questionnaire, text) in inv_text:
            confirmed = (not force and
                         str(getattr(r, 'reuse_match', False)).strip().lower() in ('true', '1', 'yes'))
            routes.append('inventory' if confirmed else 'duplicate')
        else:
            routes.append('new')
    out = df.copy()
    out['route'] = routes
    return out


PROGRESS_PREFIX = '@@HARMONICA_PROGRESS '


def run_items_with_progress(run_model, construct, questionnaire, items, report_progress):
    """Run each independent model item and report completion immediately."""
    predictions = []
    for item in items:
        predictions.extend(run_model(construct, [item]))
        report_progress({
            'construct': construct,
            'questionnaire': questionnaire,
            'items': 1,
            'item_id': item['item_id'],
        })
    return predictions


def attach_input_metadata(results, items):
    """Carry caller-supplied definition fields through the engine output."""
    keys = ['construct', 'questionnaire', 'item_id']
    extra_columns = [column for column in items.columns if column not in results.columns and column != 'reuse_match']
    if extra_columns:
        metadata = items[keys + extra_columns]
        results = results.merge(metadata, on=keys, how='left', validate='one_to_one')
    return results


def run_harmonica(df, force=False, timeout=1800, on_progress=None):
    """Run the engine in an isolated worker process.

    `on_progress(event)` is called about twice a second while the worker runs:
    `event` is None on a plain tick (e.g. to refresh elapsed time), or a dict
    {'construct', 'questionnaire', 'items', 'item_id'} for each model item,
    followed by {'construct', 'questionnaire', 'items': 0, 'group_complete': True}
    when a questionnaire finishes.
    """
    import json
    import queue
    import sys
    import threading
    import time
    root = Path(__file__).resolve().parent
    cache = Path(os.environ.get('HARMONICA_MODELS_DIR', str(Path.home()/'.cache'/'harmonica-ui'/'models'))).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='harmonica-ui-') as directory:
        work = Path(directory)
        source, target, inventory = work/'items.csv', work/'results.csv', work/'inventory.csv'
        df.to_csv(source, index=False)
        load_ui_inventory().to_csv(inventory, index=False)
        command = [sys.executable, str(root/'engine_worker.py'), str(source), str(target), str(inventory), str(cache), '1' if force else '0']
        proc = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        lines = queue.Queue()

        def read_output():
            # Reading in a thread keeps the timeout check and progress ticks running
            for output_line in proc.stdout:
                lines.put(output_line)
            lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        log_lines, deadline, finished = [], time.monotonic() + timeout, False
        while not finished:
            if time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError(f'Run exceeded {timeout // 60} minutes. Reduce the batch or increase the timeout.')
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                line = ''
            if line is None:
                finished = True
            elif line.startswith(PROGRESS_PREFIX):
                if on_progress:
                    on_progress(json.loads(line[len(PROGRESS_PREFIX):]))
                continue
            elif line:
                log_lines.append(line)
            if on_progress:
                on_progress(None)
        proc.wait()
        log = ''.join(log_lines).strip()
        if proc.returncode:
            raise RuntimeError(f'HarmoniCA exited with code {proc.returncode}.\n{log[-12000:]}')
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError('HarmoniCA produced no result CSV.\n' + log[-12000:])
        data = target.read_bytes()
        results = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        required = {'construct','questionnaire','item_id','item_text','dimension','dimension_label','confidence'}
        if not required.issubset(results.columns):
            raise RuntimeError('The installed engine returned an incompatible output schema.')
        keys=['construct','questionnaire','item_id']
        if len(results)!=len(df) or set(map(tuple,results[keys].values)) != set(map(tuple,df[keys].values)):
            raise RuntimeError('Output items do not match submitted items. Results were rejected.')
        results = attach_input_metadata(results, df)
        data = results.to_csv(index=False).encode('utf-8')
        return data, results, log
