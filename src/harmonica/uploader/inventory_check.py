"""Compare items with the inventory. Shared by the Harmonize tab and the Data Harmonizer."""
from dataclasses import dataclass, field
from typing import List

import pandas as pd

DUPLICATE_COLUMNS = [
    'questionnaire', 'your_item_id', 'your_item_text',
    'matched_inventory_item_id', 'matched_item_text', 'dimension_label',
]
# Display order in the uploader: the checkbox first, so it is always visible without scrolling.
DUPLICATE_TABLE_COLUMNS = ['same_item?'] + DUPLICATE_COLUMNS


CACHED_COLUMNS = ['questionnaire', 'construct', 'item_id', 'item_text',
                  'dimension', 'dimension_label', 'confidence']
# answer_options / scoring are shown for information only (the model reads item_text alone).
NEW_COLUMNS = ['questionnaire', 'construct', 'item_id', 'item_text', 'answer_options', 'scoring']


@dataclass
class InventoryReport:
    groups: List[dict] = field(default_factory=list)       # one per (construct, questionnaire)
    review_rows: List[dict] = field(default_factory=list)  # possible duplicates
    cached_rows: List[dict] = field(default_factory=list)  # exact item_id match (existing assignment)
    new_rows: List[dict] = field(default_factory=list)     # not in the inventory at all

    @property
    def n_cached(self) -> int:
        return len(self.cached_rows)

    @property
    def n_new(self) -> int:
        return len(self.new_rows)

    @property
    def n_duplicates(self) -> int:
        return len(self.review_rows)

    def summary(self) -> str:
        return (
            f"{self.n_cached} already in the inventory (exact ID match), "
            f"{self.n_duplicates} possible duplicate(s) under a different item_id, "
            f"{self.n_new} new."
        )

    def cached_table(self) -> pd.DataFrame:
        return pd.DataFrame(self.cached_rows, columns=CACHED_COLUMNS)

    def new_table(self) -> pd.DataFrame:
        return pd.DataFrame(self.new_rows, columns=NEW_COLUMNS)

    def duplicates_table(self) -> pd.DataFrame:
        # Same columns as the review table on the Harmonize tab, with same_item? first
        # (default True = reuse the inventory assignment).
        return pd.DataFrame(self.review_rows, columns=DUPLICATE_TABLE_COLUMNS)


def check_items_against_inventory(items_df: pd.DataFrame, hca) -> InventoryReport:
    """The "Check inventory" rules, applied per (construct, questionnaire):

      - exact item_id match in the inventory: already in the inventory
      - same text under a different item_id: possible duplicate
      - everything else: new
    Pure lookup: nothing is written to the inventory.
    """
    report = InventoryReport()
    for (construct, questionnaire), group in items_df.groupby(['construct', 'questionnaire']):
        items = group[['item_id', 'item_text']].to_dict('records')
        extras = {  # answer_options / scoring per item, when the caller passed them
            row['item_id']: {c: row.get(c, '') for c in ('answer_options', 'scoring')}
            for row in group.to_dict('records')
        }
        report.groups.append({'questionnaire': questionnaire, 'construct': construct, 'items': items})

        cached, missing = hca._check_inventory(questionnaire, construct, items)
        for row in cached:
            report.cached_rows.append({'questionnaire': questionnaire, 'construct': construct, **row})

        candidates = hca._find_id_mismatch_candidates(questionnaire, construct, missing)
        candidate_ids = {it['item_id'] for it, _ in candidates}
        for it in missing:
            if it['item_id'] not in candidate_ids:
                report.new_rows.append({'questionnaire': questionnaire, 'construct': construct,
                                        'item_id': it['item_id'], 'item_text': it['item_text'],
                                        **extras[it['item_id']]})

        for it, inv_row in candidates:
            report.review_rows.append({
                'questionnaire': questionnaire,
                'your_item_id': it['item_id'],
                'your_item_text': it['item_text'],
                'matched_inventory_item_id': inv_row['item_id'],
                'matched_item_text': inv_row['item_text'],
                'dimension_label': inv_row['dimension_label'],
                'same_item?': True,
            })
    return report
