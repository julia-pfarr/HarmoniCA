"""CLI adapter: no shell interpolation and no invented HarmoniCA predictions."""
import ast
import io
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import pandas as pd

COLUMNS = ['construct', 'questionnaire', 'item_id', 'item_text']   # what the harmonization engine reads
SCORING_COLUMNS = ['answer_options', 'scoring']                       # needed for the score transformation
ITEM_COLUMNS = COLUMNS + SCORING_COLUMNS
SEPARATORS = [',', ';', '\t']
RESPONSE_OPTIONS_PATH = Path(__file__).resolve().parent/'assets'/'questionnaire_response_options.csv'


def engine_dir():
    """Folder of the HarmoniCA engine package (installed, or found through HARMONICA_SOURCE_DIR).

    The inventory and the default model folder live there, exactly as for the command-line tool.
    """
    import importlib.util
    spec = importlib.util.find_spec('harmonica')
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError('The HarmoniCA engine was not found. Install it (pip install -e . in the repository root) '
                                'or set HARMONICA_SOURCE_DIR to the repository\'s src folder.')
    return Path(list(spec.submodule_search_locations)[0])


def inventory_file():
    return engine_dir()/'inventory'/'harmonized_inventory.csv'


def read_inventory(dedupe=False):
    """The engine's inventory, as text. `dedupe` keeps the last row per (construct, questionnaire, item_id)."""
    inv = pd.read_csv(inventory_file(), dtype=str, keep_default_na=False)
    return inv.drop_duplicates(['construct', 'questionnaire', 'item_id'], keep='last') if dedupe else inv


def load_response_options():
    """Answer options and scoring of the inventory questionnaires that have them (one row per item)."""
    options = pd.read_csv(RESPONSE_OPTIONS_PATH, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    return options[['construct', 'questionnaire', 'item_id'] + SCORING_COLUMNS].drop_duplicates(['construct', 'questionnaire', 'item_id'])


def scoring_problem(scoring):
    """Why a scoring value cannot be used, or None when it is fine.

    The score transformation only reads `scoring` (to get each item's maximum score), so that is what is validated.
    answer_options is documentation of the answer choices and only has to be filled in.
    """
    try:
        scores = ast.literal_eval(scoring)
    except (ValueError, SyntaxError):
        return 'scoring must be a list of numbers, for example [0, 1, 2, 3]'
    if not isinstance(scores, list) or not scores:
        return 'scoring must be a non-empty list of numbers, for example [0, 1, 2, 3]'
    for value in scores:
        try:
            if math.isfinite(float(value)):
                return None
        except (TypeError, ValueError):
            continue
    return 'scoring needs at least one numeric value'


def detect_separator(data):
    """Guess the CSV separator from the header line, which (unlike item texts)
    rarely contains commas. Excel in e.g. French locales saves with ';'."""
    header = data[:65536].decode('utf-8-sig', errors='replace').splitlines()[:1]
    if not header:
        return ','
    counts = {sep: header[0].count(sep) for sep in SEPARATORS}
    best = max(SEPARATORS, key=lambda sep: counts[sep])
    return best if counts[best] else ','


def parse_items(data, scoring='required'):
    """Read and validate an items CSV.

    scoring='required' (uploaded files): answer_options and scoring must be present, filled and valid.
    scoring='optional' (inventory items are combined in): the two columns may be empty, but are valid when filled.
    """
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except Exception as exc:
        raise ValueError(f'Cannot read CSV: {exc}') from exc
    df.columns = df.columns.str.strip()
    if df.columns.duplicated().any():
        raise ValueError('Column names must be unique.')
    required = ITEM_COLUMNS if scoring == 'required' else COLUMNS
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError('Missing columns: ' + ', '.join(sorted(missing, key=ITEM_COLUMNS.index)))
    for col in SCORING_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df[ITEM_COLUMNS].copy()
    for col in ITEM_COLUMNS:
        df[col] = df[col].str.strip()
    df['construct'] = df['construct'].str.lower()
    if df.empty:
        raise ValueError('The CSV contains no items.')
    if len(df) > 10000:
        raise ValueError('Please use at most 10,000 items per run.')
    empty = df[required].eq('')
    if empty.values.any():
        where = [f"{col} (CSV line(s) {', '.join(str(i + 2) for i in df.index[empty[col]][:10])})" for col in required if empty[col].any()]
        raise ValueError('Required values are empty in ' + '; '.join(where))
    if df.duplicated(['construct', 'questionnaire', 'item_id']).any():
        raise ValueError('Duplicate item IDs within the same questionnaire and construct. Resolve them before running.')
    problems = []
    for line, scores in enumerate(df.scoring, start=2):
        problem = scoring_problem(scores) if scores else None
        if problem:
            problems.append(f'line {line}: {problem}')
    if problems:
        raise ValueError('Invalid scoring on ' + '; '.join(problems[:5]) + (f' (and {len(problems) - 5} more)' if len(problems) > 5 else ''))
    return df


def _normalize(text):
    # Same normalisation as engine_worker.py and the upstream engine
    return ' '.join(str(text).strip().lower().split()).strip(' .?!"\'')


def inventory_check(df):
    """Classify items the way the engine will treat them, without running it.

    Returns a copy of `df` with a 'route' column:
      'inventory' — exact match (same construct, questionnaire, item_id and wording): reused
      'duplicate' — same wording as an inventory item under a different item_id: reused only if the user
                    confirms it is the same item
      'new'       — not in the inventory: sent to the model
    Both kinds of match also get the inventory item in 'matched_item_id', 'matched_item_text' and
    'matched_dimension_label', so a UI can show what each item was matched to.
    """
    inv = read_inventory()
    inv_key, inv_text = {}, {}
    for r in inv.itertuples():
        inv_key[(r.construct, r.questionnaire, r.item_id)] = r
        # First row per wording, like the engine's candidate lookup
        inv_text.setdefault((r.construct, r.questionnaire, _normalize(r.item_text)), r)
    routes, matched = [], []
    for r in df.itertuples():
        text = _normalize(r.item_text)
        found = inv_key.get((r.construct, r.questionnaire, r.item_id))
        if found is not None and _normalize(found.item_text) == text:
            routes.append('inventory')
        elif (r.construct, r.questionnaire, text) in inv_text:
            routes.append('duplicate')
            found = inv_text[(r.construct, r.questionnaire, text)]
        else:
            routes.append('new')
            found = None
        matched.append((found.item_id, found.item_text, found.dimension_label) if found is not None else ('', '', ''))
    out = df.copy()
    out['route'] = routes
    out[['matched_item_id', 'matched_item_text', 'matched_dimension_label']] = matched
    return out


PROGRESS_PREFIX = '@@HARMONICA_PROGRESS '


def run_harmonica(df, timeout=1800, on_progress=None, decisions=None):
    """Run the engine in an isolated worker process.

    `on_progress(event)` is called about twice a second while the worker runs:
    `event` is None on a plain tick (e.g. to refresh elapsed time), or a dict
    {'construct', 'questionnaire', 'items'} each time a questionnaire finishes.

    Returns (results CSV bytes, results, engine log, new_rows): `new_rows` are the model predictions the engine added to its
    private inventory copy, in the inventory's file format (what the command-line tool would append to the real inventory).

    `decisions` carries the user's answers about items we think are already in the inventory:
    {'same_items': [[construct, questionnaire, item_id], ...]} are items with a different item ID that the user confirmed
    as the same item (their inventory assignment is reused), {'rerun_items': [[...], ...]} are exact matches the user
    said are not the same, so the model must run on them.
    """
    import json
    import queue
    import sys
    import threading
    import time
    root = Path(__file__).resolve().parent
    cache = Path(os.environ.get('HARMONICA_MODELS_DIR') or engine_dir()/'models').expanduser().resolve()   # same default as the command line
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='harmonica-ui-') as directory:
        work = Path(directory)
        source, target, inventory = work/'items.csv', work/'results.csv', work/'inventory.csv'
        df.to_csv(source, index=False)
        shutil.copyfile(inventory_file(), inventory)      # a private copy: the original inventory is never edited here
        command = [sys.executable, str(root/'engine_worker.py'), str(source), str(target), str(inventory), str(cache)]
        if decisions:
            (work/'decisions.json').write_text(json.dumps(decisions), encoding='utf-8')
            command.append(str(work/'decisions.json'))
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
        added = target.with_name('new_inventory_rows.csv')
        new_rows = pd.read_csv(added, dtype=str, keep_default_na=False) if added.is_file() else pd.DataFrame()
        return data, results, log, new_rows
