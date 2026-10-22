"""
HarmoniCA — command-line entry point.

Usage examples
--------------
# Assign items from a CSV file:
python harmonize.py --items items.csv

# items.csv must have columns: construct, questionnaire, item_id, item_text
# Additional columns are ignored. Multiple questionnaires and constructs are supported.
# Results are written to items_harmonized.csv (next to items.csv) unless --output is given,
# and always contain only the questionnaires present in items.csv.
# If an item's text matches an inventory item already assigned under a different
# item_id (e.g. your 'PHQ9_1' vs the inventory's 'PHQ-9_01'), you'll be prompted
# on the terminal to confirm whether it's the same item before its cached
# assignment is reused (Enter = same item). Use --duplicates same|new to decide
# for all such items without being asked.
# Optional columns answer_options and scoring are carried into the results file,
# which is what the web app's score transformation needs.

# Programmatic use:
from harmonica import HarmoniCA

hca = HarmoniCA(models_dir='models', inventory_path='inventory/harmonized_inventory.csv')
result = hca.harmonize(
    questionnaire='PHQ-9',
    construct='depression',
    items=[
        {'item_id': 'PHQ9_01', 'item_text': 'Little interest or pleasure in doing things'},
        {'item_id': 'PHQ9_02', 'item_text': 'Feeling down, depressed, or hopeless'},
    ]
)
for a in result['assignments']:
    print(f"{a['item_id']}: Dim {a['dimension']} — {a['dimension_label']} (conf={a['confidence']:.2f})")
"""

import argparse
import json
import pandas as pd
from pathlib import Path

from harmonica.harmonica import HarmoniCA

DEFAULT_MODELS_DIR    = Path(__file__).parent / 'models'
DEFAULT_INVENTORY     = Path(__file__).parent / 'inventory' / 'harmonized_inventory.csv'

ITEM_COLUMNS    = ['construct', 'questionnaire', 'item_id', 'item_text']
PASSTHROUGH     = ['answer_options', 'scoring']          # kept in the results when the input has them
OUTPUT_COLUMNS  = ['construct', 'questionnaire', 'item_id', 'item_text',
                   'dimension', 'dimension_label', 'confidence', 'source']


def read_items(path):
    """Read an items CSV the same way the web app does: as text, trimmed, construct in lower case."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    df.columns = df.columns.str.strip()
    missing = set(ITEM_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Items CSV is missing required columns: {missing}")
    for col in ITEM_COLUMNS + [c for c in PASSTHROUGH if c in df.columns]:
        df[col] = df[col].str.strip()
    df['construct'] = df['construct'].str.lower()
    return df


def main():
    parser = argparse.ArgumentParser(
        description='Assign questionnaire items to construct dimensions using HarmoniCA.'
    )
    parser.add_argument('--items', '-i', required=True,
                        help='CSV file with columns: construct, questionnaire, item_id, item_text')
    parser.add_argument('--output', '-o', default=None,
                        help='Output CSV path (default: <items>_harmonized.csv next to the input file)')
    parser.add_argument('--force-rerun', action='store_true',
                        help='Ignore inventory and always run the model')
    parser.add_argument('--duplicates', choices=['ask', 'same', 'new'], default='ask',
                        help='Items whose text matches an inventory item under a different item_id: '
                             "'ask' on the terminal (default; Enter = same item), or treat all as the "
                             "'same' item (reuse the inventory assignment) or as 'new' (run the model)")
    parser.add_argument('--models-dir', default=str(DEFAULT_MODELS_DIR))
    parser.add_argument('--inventory', default=str(DEFAULT_INVENTORY))
    parser.add_argument('--device', default=None, choices=['cpu', 'cuda'],
                        help='Device for the fine-tuned models (default: cuda if available, else cpu)')
    parser.add_argument('--scoring-bundle', metavar='ZIP',
                        help='Export an offline scoring ZIP; items CSV must also contain answer_options and scoring lists')

    args = parser.parse_args()

    # Load items
    items_df = read_items(args.items)
    if args.scoring_bundle:
        scoring_missing = {'answer_options', 'scoring'} - set(items_df.columns)
        if scoring_missing:
            raise ValueError(f"Scoring definitions missing columns: {sorted(scoring_missing)}")

    # Run per (construct, questionnaire) group
    hca = HarmoniCA(models_dir=args.models_dir, inventory_path=args.inventory, device=args.device)
    all_results = []
    for (construct, questionnaire), group in items_df.groupby(['construct', 'questionnaire']):
        items = group[['item_id', 'item_text']].to_dict('records')
        options = {} if args.duplicates == 'ask' else {'confirm_match': lambda user_item, inv_row: args.duplicates == 'same'}
        result = hca.harmonize(
            questionnaire=questionnaire,
            construct=construct,
            items=items,
            force_rerun=args.force_rerun,
            **options,
        )
        group_df = pd.DataFrame(result['assignments'])
        group_df.insert(0, 'questionnaire', questionnaire)
        group_df.insert(1, 'construct', construct)
        if 'source' not in group_df:                      # engines that only report one source per questionnaire
            group_df['source'] = result['source']
        if 'probability_distribution' in group_df:        # as text, like the web app's results
            group_df['probability_distribution'] = group_df['probability_distribution'].map(
                lambda d: json.dumps(d) if isinstance(d, dict) else d)
        all_results.append(group_df)

    out_df = pd.concat(all_results, ignore_index=True)
    # Carry answer_options / scoring through, and use the same column order as the web app
    keep = [c for c in PASSTHROUGH if c in items_df.columns]
    if keep:
        out_df = out_df.merge(items_df[['construct', 'questionnaire', 'item_id'] + keep],
                              on=['construct', 'questionnaire', 'item_id'], how='left')
    extra = [c for c in out_df.columns if c not in OUTPUT_COLUMNS and c not in PASSTHROUGH]
    out_df = out_df[OUTPUT_COLUMNS + extra + keep]

    preview_cols = ['questionnaire', 'construct', 'item_id', 'dimension', 'dimension_label', 'confidence']
    print(out_df[preview_cols].to_string(index=False))

    output_path = args.output
    if output_path is None:
        items_path = Path(args.items)
        output_path = items_path.with_name(f"{items_path.stem}_harmonized.csv")

    out_df.to_csv(output_path, index=False)
    print(f"\nSaved to {output_path}")
    if args.scoring_bundle:
        from harmonica.pipeline import generate_pipeline, save_bundle
        pipeline = generate_pipeline(out_df.to_dict('records'), items_df.to_dict('records'))
        save_bundle(pipeline, args.scoring_bundle)
        print(f"Saved offline scoring bundle to {args.scoring_bundle}")



if __name__ == '__main__':
    main()
