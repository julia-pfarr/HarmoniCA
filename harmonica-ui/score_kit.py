"""The downloadable score transformation kit, and helpers for the Score transformation page."""
import io
import zipfile
from pathlib import Path

import pandas as pd

KIT_DIR = Path(__file__).resolve().parent/'assets'/'score-transformation'
KIT_FILES = ['README.txt', 'run_score_transformation.py', 'requirements.txt', 'LICENSE.txt',
             'research_code/score_transformation.py', 'research_code/create_item_dimension_mapping.py']
KIT_FOLDER = 'harmonica_score_transformation'


def build_kit_zip():
    """The research code plus the wrapper that runs it on a harmonized CSV, as ZIP bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in KIT_FILES:
            archive.write(KIT_DIR/name, f'{KIT_FOLDER}/{name}')
    return buffer.getvalue()


def _scoring(result):
    return result['scoring'].fillna('').astype(str).str.strip() if 'scoring' in result else pd.Series('', index=result.index)


def scorable(result):
    """Items that can be scored: assigned to a dimension (not -1) and with scoring."""
    dimension = pd.to_numeric(result['dimension'], errors='coerce')
    return result[dimension.notna() & (dimension != -1) & (_scoring(result) != '')]


def responses_template(result):
    """Header-only responses CSV (participant_id plus one column per scorable item), as bytes."""
    columns = ['participant_id'] + list(dict.fromkeys(scorable(result)['item_id']))
    return (','.join(columns) + '\n').encode()


def unscored_questionnaires(result):
    """Questionnaires with items that cannot be scored: (construct, questionnaire, items without scoring, items)."""
    dimension = pd.to_numeric(result['dimension'], errors='coerce')
    candidates = result[dimension.notna() & (dimension != -1)]
    has_scoring = _scoring(candidates) != ''
    rows = []
    for (construct, questionnaire), group in candidates.assign(has_scoring=has_scoring).groupby(['construct', 'questionnaire']):
        missing = int((~group.has_scoring).sum())
        if missing:
            rows.append((construct, questionnaire, missing, len(group)))
    return rows
