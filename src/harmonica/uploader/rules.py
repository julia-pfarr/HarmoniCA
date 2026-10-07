"""Validation rules for items submitted through the Data Harmonizer (no Gradio here)."""
from typing import Iterable, List

import pandas as pd

# The four columns the Harmonize tab and the command line need.
CORE_COLUMNS = ['construct', 'questionnaire', 'item_id', 'item_text']
# The Data Harmonizer asks for two more. Every item needs all six fields.
UPLOAD_COLUMNS = CORE_COLUMNS + ['answer_options', 'scoring']


class ItemsFormatError(ValueError):
    """The submitted items do not match the expected format."""


class EmptyUploadError(ItemsFormatError):
    """The submission has the right columns but no data rows."""


def check_constructs(values: Iterable[str], supported: List[str]) -> None:
    """Same rule as "Check inventory" on the Harmonize tab: constructs must be supported."""
    unknown = set(values) - set(supported) - {''}
    if unknown:
        raise ItemsFormatError(
            f"Unknown construct(s): {', '.join(sorted(unknown))}. Supported: {', '.join(supported)}"
        )


def validate_items(df: pd.DataFrame, supported_constructs: List[str]) -> pd.DataFrame:
    """Validate a table of items and return a cleaned copy.

    Rules:
      - all of UPLOAD_COLUMNS present
      - at least one non-blank row
      - ``construct`` is one of the supported constructs
      - no empty cells
      - no repeated ``item_id``
    The returned frame has exactly UPLOAD_COLUMNS, as stripped strings.
    Raises ItemsFormatError (EmptyUploadError when there are no rows).
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in UPLOAD_COLUMNS if c not in df.columns]
    if missing:
        raise ItemsFormatError(
            f"Missing column(s): {', '.join(missing)}. "
            f"Expected columns: {', '.join(UPLOAD_COLUMNS)}."
        )
    df = df[UPLOAD_COLUMNS].fillna('').astype(str).apply(lambda col: col.str.strip())
    df = df[(df != '').any(axis=1)]  # drop fully blank rows
    if df.empty:
        raise EmptyUploadError("At least one row is required. No data rows were found.")

    check_constructs(df['construct'], supported_constructs)

    problems = []
    for idx, row in df.iterrows():
        empty = [c for c in UPLOAD_COLUMNS if not row[c]]
        if empty:
            problems.append(f"Row {idx + 1}: missing {', '.join(empty)}")
    dupes = df[df.duplicated('item_id', keep=False)]['item_id'].unique()
    if len(dupes):
        problems.append(f"Duplicate item_id: {', '.join(dupes[:5])}")
    if problems:
        extra = f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""
        raise ItemsFormatError(". ".join(problems[:8]) + extra)
    return df.reset_index(drop=True)
