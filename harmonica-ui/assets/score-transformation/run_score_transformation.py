"""
Run the score transformation on a HarmoniCA harmonized output CSV.

Takes the CSV you downloaded from HarmoniCA (it carries the item -> dimension
assignments plus each item's answer_options and scoring) and your participants'
item responses, and runs the same pipeline as the research code:

  1. Build item_dimension_mapping.csv and max_dimension_scores.csv from the
     harmonized CSV (create_item_dimension_mapping.py)
  2. Raw and proportion dimension scores
  3. Per-questionnaire C-scores (q_cdf_score)
  4. Averaged-CDF C-scores (av_cdf_score)

Participant responses: one row per participant, one column per item (column
names = item IDs), plus participant_id. Item values must already be numeric item
scores (the values listed in `scoring`). Missing values: empty cells or -9.
Any other columns (site, age, ...) are carried through to the output.

Usage: put harmonized_items.csv and responses.csv in the folder you run this from, then

  python run_score_transformation.py

or point to the files explicitly:

  python run_score_transformation.py --harmonized path/to/harmonized_items.csv \\
      --responses path/to/responses.csv --output scores
"""

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
except ImportError:
    sys.exit("This needs pandas and numpy. Install them first:\n  python -m pip install -r requirements.txt")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'research_code'))   # the unchanged research code
from create_item_dimension_mapping import create_mapping, create_max_dimension_scores  # noqa: E402
from score_transformation import ScoreTransformer  # noqa: E402

REQUIRED_HARMONIZED = ['construct', 'questionnaire', 'item_id', 'dimension', 'dimension_label', 'scoring']


def build_mapping(harmonized: pd.DataFrame):
    """Item -> dimension mapping and maximum dimension scores from a harmonized CSV."""
    missing = [c for c in REQUIRED_HARMONIZED if c not in harmonized.columns]
    if missing:
        raise ValueError(
            f"The harmonized CSV is missing columns: {missing}. Use the CSV downloaded from HarmoniCA "
            "(it must contain the answer_options and scoring columns)."
        )
    harmonized = harmonized.copy()
    harmonized['dimension'] = pd.to_numeric(harmonized['dimension'], errors='coerce')
    harmonized = harmonized[harmonized['dimension'].notna()].copy()
    harmonized['dimension'] = harmonized['dimension'].astype(int)
    harmonized = harmonized.drop_duplicates(['construct', 'questionnaire', 'item_id'], keep='last')

    shared = harmonized[harmonized.duplicated(['questionnaire', 'item_id'], keep=False)]
    if len(shared):
        raise ValueError(
            "The same item ID occurs under more than one construct: "
            f"{sorted(shared['item_id'].unique())[:5]}. Item IDs must be unique within a questionnaire."
        )

    # Items without scoring cannot be scored. The research code drops them with a warning.
    scoring = harmonized['scoring'].fillna('').astype(str).str.strip()
    options = pd.DataFrame({
        'construct': harmonized['construct'],
        'questionnaire_name': harmonized['questionnaire'],
        'question_number': harmonized['item_id'],
        'scoring': scoring,
    })[scoring != '']
    mapping = create_mapping(harmonized, options)
    if mapping.empty:
        raise ValueError("No item has both a dimension and scoring, so nothing can be scored.")
    return mapping, create_max_dimension_scores(mapping)


def reshape_to_long(responses: pd.DataFrame, mapping: pd.DataFrame, all_item_ids) -> pd.DataFrame:
    """One row per (participant, questionnaire) with at least one response to a mapped item.

    Columns that are item IDs but are not scored (no scoring, or "does not fit") are dropped;
    every other column (site, age, ...) is carried through as metadata.
    """
    meta_cols = [c for c in responses.columns if c not in set(all_item_ids)]
    parts = []
    for questionnaire, q_df in mapping.groupby('questionnaire'):
        present = [i for i in q_df['item_id'].unique() if i in responses.columns]
        if not present:
            continue
        has_any = responses[present].notna().any(axis=1)
        if not has_any.any():
            continue
        subset = responses.loc[has_any, meta_cols + present].copy()
        subset['questionnaire'] = questionnaire
        parts.append(subset)
    if not parts:
        raise ValueError(
            "No responses found for any scored item. The response columns must be named like the item IDs "
            "in the harmonized CSV (for example BDI_01)."
        )
    long_df = pd.concat(parts, ignore_index=True)
    print(f"  {len(long_df)} (participant x questionnaire) rows | "
          f"{long_df['questionnaire'].nunique()} questionnaires: {sorted(long_df['questionnaire'].unique())}")
    return long_df


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--harmonized', default='harmonized_items.csv',
                        help='Harmonized output CSV downloaded from HarmoniCA (default: harmonized_items.csv)')
    parser.add_argument('--responses', default='responses.csv',
                        help='Participant responses CSV, one row per participant (default: responses.csv)')
    parser.add_argument('--output', default='scores', help='Output directory (default: scores)')
    parser.add_argument('--participant-id-col', default='participant_id')
    parser.add_argument('--missing-values', nargs='*', type=float, default=[-9],
                        help='Codes to treat as missing, besides empty cells (default: -9)')
    args = parser.parse_args()

    for path, option in ((args.harmonized, '--harmonized'), (args.responses, '--responses')):
        if not Path(path).is_file():
            sys.exit(f"Error: cannot find {path}. Put it in the folder you run this from, or give its location with {option}.")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("SCORE TRANSFORMATION")
    print("=" * 70)
    print(f"Harmonized CSV: {args.harmonized}\nResponses:      {args.responses}\nResults go to:  {output_dir}")
    try:
        harmonized = pd.read_csv(args.harmonized)
        print(f"\nHarmonized CSV: {len(harmonized)} items")
        mapping, max_scores = build_mapping(harmonized)
        mapping.to_csv(output_dir / 'item_dimension_mapping.csv', index=False)
        max_scores.to_csv(output_dir / 'max_dimension_scores.csv', index=False)
        print(f"  {len(mapping)} items across {mapping['questionnaire'].nunique()} questionnaire(s) can be scored")

        responses = pd.read_csv(args.responses)
        if args.missing_values:
            responses = responses.replace(args.missing_values, np.nan)
        if args.participant_id_col not in responses.columns:
            raise ValueError(f"Column '{args.participant_id_col}' not found in the responses CSV.")
        if responses[args.participant_id_col].duplicated().any():
            raise ValueError("Each participant must appear once (one row per participant).")
        print(f"\nResponses: {len(responses)} participants")
        long_df = reshape_to_long(responses, mapping, harmonized['item_id'])
    except (ValueError, FileNotFoundError, KeyError) as exc:
        sys.exit(f"Error: {exc}")

    transformer = ScoreTransformer(min_items_high=4, min_items_moderate=2, missing_threshold=0.5)
    transformer.item_mapping = mapping
    transformer.max_scores = max_scores

    print("\nComputing raw and proportion scores...")
    scores_df = transformer.compute_scores(long_df, args.participant_id_col, 'questionnaire')
    print("\nComputing per-questionnaire CDF scores (q_cdf_score)...")
    scores_df = transformer.compute_q_cdf_scores(scores_df, 'questionnaire')
    print("\nComputing averaged-CDF scores (av_cdf_score)...")
    scores_df = transformer.compute_av_cdf_scores(scores_df, 'questionnaire')

    transformer._print_summary(scores_df, 'questionnaire')
    transformer.export(scores_df, str(output_dir))
    transformer.save_norms(str(output_dir / 'cdf_norms.json'))
    print(f"\nDone. Results saved to {output_dir}")


if __name__ == '__main__':
    main()
