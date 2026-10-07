"""Run harmonization on checked items. Shared by the Harmonize tab and the Data Harmonizer,
so both apply the same rules: items already in the inventory are reused, the model runs only
for the rest, and the new predictions are added to the inventory."""
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

RESULT_COLUMNS = ['questionnaire', 'construct', 'item_id', 'dimension', 'dimension_label', 'confidence', 'source']


def write_results_csv(out_df: pd.DataFrame) -> str:
    """Write the harmonization results to a temporary harmonized_results.csv (for the download box)."""
    path = Path(tempfile.mkdtemp()) / 'harmonized_results.csv'
    out_df.to_csv(path, index=False)
    return str(path)


def decisions_from_review(review_df) -> Dict[Tuple[str, str], bool]:
    """Turn the "possible duplicates" table into {(questionnaire, item_id): same_item?}."""
    decisions = {}
    if review_df is not None and len(review_df) > 0:
        for _, row in review_df.iterrows():
            decisions[(row['questionnaire'], row['your_item_id'])] = bool(row['same_item?'])
    return decisions


def run_groups(hca, groups: List[dict], decisions: Dict[Tuple[str, str], bool],
               force_rerun: bool = False, on_group=None) -> pd.DataFrame:
    """Harmonize every (construct, questionnaire) group. Writes new items to the inventory.

    on_group(index, total, group) is called just before each group runs (used for progress bars).
    """
    all_results = []
    for i, g in enumerate(groups):
        if on_group:
            on_group(i, len(groups), g)
        questionnaire, construct, items = g['questionnaire'], g['construct'], g['items']

        def confirm_match(user_item, inv_row, _q=questionnaire):
            return decisions.get((_q, user_item['item_id']), True)

        result = hca.harmonize(
            questionnaire=questionnaire, construct=construct, items=items,
            force_rerun=force_rerun, confirm_match=confirm_match,
        )
        group_df = pd.DataFrame(result['assignments'])
        group_df.insert(0, 'questionnaire', questionnaire)
        group_df.insert(1, 'construct', construct)
        group_df['source'] = result['source']
        all_results.append(group_df)
    return pd.concat(all_results, ignore_index=True)
