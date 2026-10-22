"""
Create Item-Dimension Mapping and Maximum Dimension Scores
==========================================================

Joins harmonizer output (item → dimension assignments) with the response
options table (item → scoring scale) to produce:

1. item_dimension_mapping.csv
   One row per item. Columns:
     construct, questionnaire, item_id, item_text, dimension, dimension_label,
     max_item_score, source, confidence

2. max_dimension_scores.csv
   One row per questionnaire × dimension combination. Columns:
     construct, questionnaire, dimension, dimension_label,
     n_items, item_ids, max_dimension_score

   max_dimension_score = sum of max_item_score across all items assigned
   to that dimension for that questionnaire. This is the denominator in:
     proportion_score = raw_dimension_score / max_dimension_score

Items assigned to dimension -1 ("Does not fit") are excluded from both
output tables, as they do not contribute to any dimension score.

Usage:
------
python create_item_dimension_mapping.py \\
    --harmonizer-output output/fine-tuning/bge-large/model-testing_round-1_results.csv \\
    --response-options input/score-transformation/questionnaire_response-options.csv \\
    --output input/score-transformation

# Multiple harmonizer output files (one per construct):
python create_item_dimension_mapping.py \\
    --harmonizer-output output/fine-tuning/bge-large/model-testing_round-1_depression_results.csv \\
                        output/fine-tuning/bge-large/model-testing_round-1_anxiety_results.csv \\
    --response-options input/score-transformation/questionnaire_response-options.csv \\
    --output input/score-transformation
"""

import argparse
import ast
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List


# =============================================================================
# Helpers
# =============================================================================

def parse_scoring(scoring_str: str) -> List[float]:
    """Parse scoring column (stored as a Python list string) to list of floats.

    Non-numeric entries such as "NA" are silently skipped.
    """
    try:
        values = ast.literal_eval(scoring_str)
    except Exception:
        return []
    result = []
    for v in values:
        try:
            result.append(float(v))
        except (ValueError, TypeError):
            pass
    return result


def max_item_score(scoring_str: str) -> float:
    """Return the maximum numeric score for a single item."""
    values = parse_scoring(scoring_str)
    if not values:
        raise ValueError(f"Could not parse scoring: {scoring_str!r}")
    return max(values)


# =============================================================================
# Main logic
# =============================================================================

def load_harmonizer_outputs(paths: List[str]) -> pd.DataFrame:
    """Load and concatenate one or more harmonizer output CSVs."""
    dfs = []
    for path in paths:
        df = pd.read_csv(path)
        print(f"  Loaded {len(df)} items from {path}")
        dfs.append(df)
    combined = pd.concat(dfs, ignore_index=True)

    # Drop duplicates in case constructs overlap across files
    combined = combined.drop_duplicates(subset=['item_id', 'construct'])
    print(f"  Total: {len(combined)} items across "
          f"{combined['construct'].nunique()} construct(s), "
          f"{combined['questionnaire'].nunique()} questionnaire(s)")
    return combined


def create_mapping(
    harmonizer_df: pd.DataFrame,
    response_options_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join harmonizer assignments with response options to add max_item_score.

    Matching key: item_id (harmonizer) == question_number (response options).
    Items with dimension == -1 are excluded.
    """
    # Exclude "Does not fit" items
    n_before = len(harmonizer_df)
    harmonizer_df = harmonizer_df[harmonizer_df['dimension'] != -1].copy()
    n_excluded = n_before - len(harmonizer_df)
    if n_excluded > 0:
        print(f"  Excluded {n_excluded} items with dimension = -1 ('Does not fit')")

    # Compute max score per item from the response options table
    response_options_df = response_options_df.copy()
    response_options_df['max_item_score'] = response_options_df['scoring'].apply(max_item_score)

    # Keep only the columns we need for the join
    scoring_lookup = response_options_df[
        ['question_number', 'questionnaire_name', 'max_item_score']
    ].rename(columns={'question_number': 'item_id', 'questionnaire_name': 'questionnaire'})

    # Merge
    merged = harmonizer_df.merge(
        scoring_lookup,
        on=['item_id', 'questionnaire'],
        how='left',
    )

    # Warn about items that could not be matched
    missing = merged['max_item_score'].isna()
    if missing.any():
        missing_items = merged.loc[missing, ['item_id', 'questionnaire']].drop_duplicates()
        print(f"\n  WARNING: {missing.sum()} item(s) could not be matched to "
              f"response options and will be excluded:")
        for _, row in missing_items.iterrows():
            print(f"    {row['item_id']} ({row['questionnaire']})")
        merged = merged[~missing].copy()

    # Select and order output columns
    cols = [
        'construct', 'questionnaire', 'item_id', 'item_text',
        'dimension', 'dimension_label', 'max_item_score',
        'source', 'confidence',
    ]
    # Only keep columns that exist (harmonizer outputs may vary slightly)
    cols = [c for c in cols if c in merged.columns]
    return merged[cols].reset_index(drop=True)


def create_max_dimension_scores(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate item-level mapping to questionnaire × dimension level.

    For each questionnaire × dimension:
      - n_items: number of items assigned to this dimension
      - item_ids: semicolon-separated list of item IDs
      - max_dimension_score: sum of max_item_score (denominator for proportion score)
    """
    rows = []
    group_cols = ['construct', 'questionnaire', 'dimension', 'dimension_label']

    for keys, group in mapping_df.groupby(group_cols, sort=True):
        construct, questionnaire, dimension, dimension_label = keys
        rows.append({
            'construct': construct,
            'questionnaire': questionnaire,
            'dimension': int(dimension),
            'dimension_label': dimension_label,
            'n_items': len(group),
            'item_ids': '; '.join(group['item_id'].tolist()),
            'max_dimension_score': group['max_item_score'].sum(),
        })

    return pd.DataFrame(rows)


def print_summary(max_dim_df: pd.DataFrame):
    """Print a readable summary table."""
    print("\n" + "=" * 70)
    print("SUMMARY: Items and maximum scores per questionnaire × dimension")
    print("=" * 70)

    for construct in max_dim_df['construct'].unique():
        print(f"\nConstruct: {construct.upper()}")
        df_c = max_dim_df[max_dim_df['construct'] == construct]

        for questionnaire in sorted(df_c['questionnaire'].unique()):
            df_q = df_c[df_c['questionnaire'] == questionnaire]
            print(f"\n  {questionnaire}")
            for _, row in df_q.iterrows():
                print(f"    Dim {row['dimension']:2d} — {row['dimension_label'][:40]:<40} "
                      f"| n={row['n_items']:2d} items | max score = {row['max_dimension_score']:.0f}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Create item-dimension mapping and max dimension scores',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single harmonizer output file
  python create_item_dimension_mapping.py \\
      --harmonizer-output output/fine-tuning/bge-large/model-testing_round-1_results.csv \\
      --response-options input/score-transformation/questionnaire_response-options.csv \\
      --output input/score-transformation

  # Multiple per-construct files
  python create_item_dimension_mapping.py \\
      --harmonizer-output \\
          output/fine-tuning/bge-large/model-testing_round-1_depression_results.csv \\
          output/fine-tuning/bge-large/model-testing_round-1_anxiety_results.csv \\
      --response-options input/score-transformation/questionnaire_response-options.csv \\
      --output input/score-transformation
        """
    )
    parser.add_argument(
        '--harmonizer-output', '-H', nargs='+', required=True,
        help='Path(s) to harmonizer output CSV file(s)'
    )
    parser.add_argument(
        '--response-options', '-r', required=True,
        help='Path to questionnaire_response-options.csv'
    )
    parser.add_argument(
        '--output', '-o', default='input/score-transformation',
        help='Output directory (default: input/score-transformation)'
    )
    parser.add_argument(
        '--construct', '-c', default=None,
        help='Filter to a single construct (optional)'
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("CREATING ITEM-DIMENSION MAPPING")
    print("=" * 70)

    # Load inputs
    print("\nLoading harmonizer output(s)...")
    harmonizer_df = load_harmonizer_outputs(args.harmonizer_output)

    print(f"\nLoading response options from {args.response_options}...")
    response_options_df = pd.read_csv(args.response_options)
    print(f"  {len(response_options_df)} items across "
          f"{response_options_df['questionnaire_name'].nunique()} questionnaire(s)")

    # Optional construct filter
    if args.construct:
        harmonizer_df = harmonizer_df[harmonizer_df['construct'] == args.construct].copy()
        response_options_df = response_options_df[
            response_options_df['construct'] == args.construct
        ].copy()
        print(f"\nFiltered to construct: {args.construct}")

    # Create mapping
    print("\nJoining assignments with response options...")
    mapping_df = create_mapping(harmonizer_df, response_options_df)
    print(f"  {len(mapping_df)} items retained after joining and filtering")

    # Create max dimension scores
    print("\nAggregating to questionnaire × dimension level...")
    max_dim_df = create_max_dimension_scores(mapping_df)
    print(f"  {len(max_dim_df)} questionnaire × dimension combinations")

    # Print summary
    print_summary(max_dim_df)

    # Save outputs
    mapping_path = output_dir / 'item_dimension_mapping.csv'
    max_scores_path = output_dir / 'max_dimension_scores.csv'

    mapping_df.to_csv(mapping_path, index=False)
    max_dim_df.to_csv(max_scores_path, index=False)

    print(f"\n{'=' * 70}")
    print(f"Saved:")
    print(f"  {mapping_path}")
    print(f"  {max_scores_path}")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
