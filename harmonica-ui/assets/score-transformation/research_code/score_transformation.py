"""
Score Transformation Pipeline
==============================

Transforms raw participant responses to harmonized dimension scores suitable
for cross-questionnaire pooling and brain-imaging correlations.

Pipeline:
  1. Map items to dimensions (from harmonizer output)
  2. Compute raw dimension scores (sum of item responses per dimension)
  3. Compute proportion scores (raw / max possible, 0–1)
  4. Compute C-scores:
       q_cdf_score    : percentile within each questionnaire × dimension group
       av_cdf_score   : questionnaire-averaged CDF transform (see
                        compute_av_cdf_scores; used in the downstream analyses)
  5. Add reliability flags (based on number of items contributing to each score)

C-score rationale:
  Raw proportion scores across instruments are not directly interchangeable
  even after 0–1 normalization, because instruments sample severity
  differently.

  q_cdf_score (per-questionnaire): maps each instrument's proportion scores onto
  its own empirical CDF. Comparable within an instrument across studies, but
  not directly comparable across instruments in the same study.

  CDF norms can be saved and loaded as a reference for
  future datasets, enabling comparison against the ENIGMA-PD normative sample.

Missing items:
  If a participant is missing responses for some items in a dimension, the
  proportion score denominator is adjusted to the max possible score for
  only the items they actually responded to. Dimensions where the participant
  responded to fewer items than the minimum threshold are flagged.

Expected input format (participant response data):
  Wide-format CSV with one row per participant. Required columns:
    - participant_id (configurable)
    - questionnaire  (configurable; must match questionnaire names in mapping)
  Optional columns:
    - site, construct, or any other metadata columns (passed through to output)
  Item response columns:
    - Named with item IDs matching those in item_dimension_mapping.csv
      (e.g. BDI_01, BDI_02, GDS_01, ...)
  Missing responses should be coded as NaN or empty.

Usage:
------
python score_transformation.py \\
    --responses input/participant_responses.csv \\
    --item-mapping input/score-transformation/item_dimension_mapping.csv \\
    --max-scores input/score-transformation/max_dimension_scores.csv \\
    --output output/score-transformation \\
    --save-norms output/score-transformation/cdf_norms.json

# Apply pre-computed norms from a reference dataset:
python score_transformation.py \\
    --responses input/new_study_responses.csv \\
    --item-mapping input/score-transformation/item_dimension_mapping.csv \\
    --max-scores input/score-transformation/max_dimension_scores.csv \\
    --load-norms output/score-transformation/cdf_norms.json \\
    --output output/score-transformation/new_study
"""

import argparse
import ast
import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# Reliability thresholds (configurable via CLI)
# =============================================================================

DEFAULT_MIN_ITEMS_HIGH = 4
DEFAULT_MIN_ITEMS_MODERATE = 2


# =============================================================================
# C-score computation
# =============================================================================

def ecdf_transform(values: np.ndarray) -> np.ndarray:
    """
    Transform proportion scores to C-scores using the empirical CDF.

    For each value x:
        C(x) = (n_below + 0.5 * n_equal) / n_total

    The midpoint rule for ties ensures that tied values receive the same
    C-score, and the formula maps values to (0, 1) open interval, avoiding
    boundary issues at 0 and 1.

    Parameters
    ----------
    values : np.ndarray
        Proportion scores for a single questionnaire × dimension group.
        May contain NaN (excluded from CDF estimation, returned as NaN).

    Returns
    -------
    c_scores : np.ndarray
        C-scores in (0, 1), same length as values. NaN preserved.
    """
    c_scores = np.full(len(values), np.nan)
    valid_mask = ~np.isnan(values)
    valid_vals = values[valid_mask]

    if len(valid_vals) == 0:
        return c_scores

    n = len(valid_vals)
    sorted_vals = np.sort(valid_vals)

    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        n_below = np.sum(sorted_vals < v)
        n_equal = np.sum(sorted_vals == v)
        c_scores[i] = (n_below + 0.5 * n_equal) / n

    return c_scores


def apply_norm_cdf(
    values: np.ndarray,
    reference_scores: np.ndarray,
) -> np.ndarray:
    """
    Apply a pre-computed CDF from a reference dataset to new proportion scores.

    This enables cross-study comparability: new participants are placed on the
    same percentile scale as the reference population (e.g. ENIGMA-PD norms).

    Parameters
    ----------
    values : np.ndarray
        Proportion scores for new participants.
    reference_scores : np.ndarray
        Sorted proportion scores from the reference dataset for this
        questionnaire × dimension group.

    Returns
    -------
    c_scores : np.ndarray
        C-scores relative to the reference distribution.
    """
    c_scores = np.full(len(values), np.nan)
    n_ref = len(reference_scores)

    if n_ref == 0:
        return c_scores

    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        n_below = np.sum(reference_scores < v)
        n_equal = np.sum(reference_scores == v)
        c_scores[i] = (n_below + 0.5 * n_equal) / n_ref

    return c_scores


# =============================================================================
# Reliability flagging
# =============================================================================

def reliability_flag(
    n_items: int,
    min_high: int = DEFAULT_MIN_ITEMS_HIGH,
    min_moderate: int = DEFAULT_MIN_ITEMS_MODERATE,
) -> str:
    """
    Assign reliability flag based on number of items contributing to the score.

    high     : n_items >= min_high (default 4)
    moderate : min_moderate <= n_items < min_high (default 2–3)
    low      : n_items == 1
    none     : n_items == 0 (score is NaN)
    """
    if n_items == 0:
        return 'none'
    elif n_items == 1:
        return 'low'
    elif n_items < min_high:
        return 'moderate'
    else:
        return 'high'


# =============================================================================
# ScoreTransformer
# =============================================================================

class ScoreTransformer:
    """
    Transforms raw participant responses to harmonized dimension scores.

    Designed as a class so it can be imported and embedded into a future
    web or desktop tool without modification.

    Parameters
    ----------
    min_items_high : int
        Minimum items for 'high' reliability flag (default 4).
    min_items_moderate : int
        Minimum items for 'moderate' reliability flag (default 2).
    missing_threshold : float
        Maximum fraction of missing items per dimension before score is set
        to NaN (default 0.5 — if more than half the items are missing,
        the score is unreliable).
    """

    def __init__(
        self,
        min_items_high: int = DEFAULT_MIN_ITEMS_HIGH,
        min_items_moderate: int = DEFAULT_MIN_ITEMS_MODERATE,
        missing_threshold: float = 0.5,
    ):
        self.min_items_high = min_items_high
        self.min_items_moderate = min_items_moderate
        self.missing_threshold = missing_threshold

        self.item_mapping: Optional[pd.DataFrame] = None
        self.max_scores: Optional[pd.DataFrame] = None
        self.norms: Dict = {}               # {construct: {questionnaire: {dimension: sorted_array}}}
        self.averaged_cdf_norms: Dict = {}  # {construct: {dimension: {x_grid, f_avg, q_sorted}}}

    # -------------------------------------------------------------------------
    # Data loading
    # -------------------------------------------------------------------------

    def load_mapping(
        self,
        item_mapping_path: str,
        max_scores_path: str,
    ):
        """Load item-dimension mapping and max dimension scores."""
        self.item_mapping = pd.read_csv(item_mapping_path)
        self.max_scores = pd.read_csv(max_scores_path)

        print(f"Loaded mapping: {len(self.item_mapping)} items across "
              f"{self.item_mapping['questionnaire'].nunique()} questionnaire(s), "
              f"{self.item_mapping['construct'].nunique()} construct(s)")
        print(f"Loaded max scores: {len(self.max_scores)} "
              f"questionnaire × dimension combinations")

    def load_responses(
        self,
        response_path: str,
        participant_id_col: str = 'participant_id',
        questionnaire_col: str = 'questionnaire',
        missing_values: Optional[List] = None,
    ) -> pd.DataFrame:
        """
        Load participant response data.

        Parameters
        ----------
        response_path : str
            Path to wide-format CSV.
        participant_id_col : str
            Column name for participant IDs.
        questionnaire_col : str
            Column name for questionnaire names.
        missing_values : list, optional
            Values to treat as missing (in addition to NaN/empty).
            Common examples: [-9, 999, 'NA'].

        Returns
        -------
        pd.DataFrame
            Loaded and cleaned response data.
        """
        df = pd.read_csv(response_path)

        # Replace custom missing value codes with NaN
        if missing_values:
            df = df.replace(missing_values, np.nan)

        # Validate required columns
        for col in [participant_id_col, questionnaire_col]:
            if col not in df.columns:
                raise ValueError(
                    f"Required column '{col}' not found. "
                    f"Available columns: {df.columns.tolist()}"
                )

        print(f"Loaded responses: {len(df)} participants, "
              f"{df[questionnaire_col].nunique()} questionnaire(s)")
        print(f"  Questionnaires: {sorted(df[questionnaire_col].unique().tolist())}")

        return df

    # -------------------------------------------------------------------------
    # Score computation
    # -------------------------------------------------------------------------

    def _get_items_for_group(
        self,
        questionnaire: str,
        construct: str,
        dimension: int,
    ) -> pd.DataFrame:
        """Return item mapping rows for a specific questionnaire × construct × dimension."""
        mask = (
            (self.item_mapping['questionnaire'] == questionnaire) &
            (self.item_mapping['construct'] == construct) &
            (self.item_mapping['dimension'] == dimension)
        )
        return self.item_mapping[mask]

    def compute_scores(
        self,
        responses_df: pd.DataFrame,
        participant_id_col: str = 'participant_id',
        questionnaire_col: str = 'questionnaire',
    ) -> pd.DataFrame:
        """
        Compute raw, proportion, and reliability scores for all participants.

        Iterates over each participant × questionnaire × construct × dimension
        combination present in the mapping, computing:
          - raw_score: sum of item responses
          - max_possible_score: sum of max item scores for responded items
          - proportion_score: raw / max (NaN if too many items missing)
          - n_items_mapped: items assigned to this dimension for this questionnaire
          - n_items_responded: items the participant actually responded to
          - n_items_missing: items with missing response
          - reliability: high / moderate / low / none

        Returns
        -------
        pd.DataFrame
            Long-format results, one row per participant × construct × dimension.
        """
        if self.item_mapping is None or self.max_scores is None:
            raise RuntimeError("Call load_mapping() before compute_scores().")

        # Identify metadata columns (non-item columns)
        all_item_ids = set(self.item_mapping['item_id'].unique())
        meta_cols = [
            c for c in responses_df.columns
            if c not in all_item_ids
        ]

        rows = []
        n_participants = len(responses_df)

        for q_idx, (questionnaire, q_df) in enumerate(
            responses_df.groupby(questionnaire_col)
        ):
            # Which constructs × dimensions does this questionnaire cover?
            q_mapping = self.item_mapping[
                self.item_mapping['questionnaire'] == questionnaire
            ]
            if len(q_mapping) == 0:
                warnings.warn(
                    f"Questionnaire '{questionnaire}' not found in item mapping. "
                    f"Skipping {len(q_df)} participant(s)."
                )
                continue

            groups = q_mapping.groupby(['construct', 'dimension', 'dimension_label'])

            for (construct, dimension, dimension_label), group in groups:
                item_ids = group['item_id'].tolist()
                max_scores_per_item = dict(
                    zip(group['item_id'], group['max_item_score'])
                )

                # Find which item columns are present in the response data
                available_items = [i for i in item_ids if i in responses_df.columns]
                missing_from_data = [i for i in item_ids if i not in responses_df.columns]

                if missing_from_data:
                    warnings.warn(
                        f"{questionnaire} / {construct} / dim {dimension}: "
                        f"{len(missing_from_data)} item column(s) not found in "
                        f"response data and will be treated as missing: "
                        f"{missing_from_data}"
                    )

                n_items_mapped = len(item_ids)

                for _, participant_row in q_df.iterrows():
                    # Collect responses for this participant
                    item_responses = {}
                    for item_id in available_items:
                        val = participant_row.get(item_id, np.nan)
                        if pd.notna(val):
                            item_responses[item_id] = float(val)

                    n_responded = len(item_responses)
                    n_missing = n_items_mapped - n_responded

                    # Check missing threshold
                    missing_fraction = n_missing / n_items_mapped if n_items_mapped > 0 else 1.0
                    if missing_fraction > self.missing_threshold or n_responded == 0:
                        raw_score = np.nan
                        max_possible = np.nan
                        proportion_score = np.nan
                    else:
                        raw_score = sum(item_responses.values())
                        max_possible = sum(
                            max_scores_per_item[i]
                            for i in item_responses.keys()
                        )
                        proportion_score = (
                            raw_score / max_possible
                            if max_possible > 0 else np.nan
                        )

                    # Build output row
                    row = {meta_col: participant_row.get(meta_col, np.nan)
                           for meta_col in meta_cols}
                    row.update({
                        'construct':           construct,
                        'dimension':           int(dimension),
                        'dimension_label':     dimension_label,
                        'n_items_mapped':      n_items_mapped,
                        'n_items_responded':   n_responded,
                        'n_items_missing':     n_missing,
                        'raw_score':           raw_score,
                        'max_possible_score':  max_possible,
                        'proportion_score':    proportion_score,
                        'reliability':         reliability_flag(
                                                   n_responded,
                                                   self.min_items_high,
                                                   self.min_items_moderate,
                                               ),
                    })
                    rows.append(row)

        scores_df = pd.DataFrame(rows)
        print(f"\nComputed scores: {len(scores_df)} participant × dimension rows")

        return scores_df

    # -------------------------------------------------------------------------
    # C-score transformation
    # -------------------------------------------------------------------------

    def compute_q_cdf_scores(
        self,
        scores_df: pd.DataFrame,
        questionnaire_col: str = 'questionnaire',
        reference_norms: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """
        Add C-scores to a scores DataFrame.

        C-scores are computed within each questionnaire × construct × dimension
        group using the empirical CDF. If reference_norms are provided (e.g.
        pre-computed ENIGMA-PD norms), new participants are placed on the
        reference CDF instead of the current sample's CDF.

        Stores the empirical CDFs in self.norms for later export.

        Parameters
        ----------
        scores_df : pd.DataFrame
            Output of compute_scores().
        questionnaire_col : str
            Column name for questionnaire.
        reference_norms : dict, optional
            Pre-loaded norms from load_norms(). If None, uses own-sample CDF.

        Returns
        -------
        pd.DataFrame
            scores_df with 'q_cdf_score' and 'q_cdf_score_reference' columns added.
        """
        scores_df = scores_df.copy()
        scores_df['q_cdf_score'] = np.nan
        scores_df['q_cdf_score_reference'] = 'own_sample'

        group_cols = [questionnaire_col, 'construct', 'dimension']

        for keys, group_idx in scores_df.groupby(group_cols).groups.items():
            questionnaire, construct, dimension = keys
            prop_scores = scores_df.loc[group_idx, 'proportion_score'].values

            # Check if we have reference norms for this group
            norm_key = str(dimension)
            ref_available = (
                reference_norms is not None
                and construct in reference_norms
                and questionnaire in reference_norms[construct]
                and norm_key in reference_norms[construct][questionnaire]
            )

            if ref_available:
                ref_scores = np.array(
                    reference_norms[construct][questionnaire][norm_key]
                )
                c = apply_norm_cdf(prop_scores, ref_scores)
                scores_df.loc[group_idx, 'q_cdf_score_reference'] = 'enigma_pd_norms'
            else:
                c = ecdf_transform(prop_scores)
                # Store this group's proportion scores for norm export
                valid = prop_scores[~np.isnan(prop_scores)]
                if construct not in self.norms:
                    self.norms[construct] = {}
                if questionnaire not in self.norms[construct]:
                    self.norms[construct][questionnaire] = {}
                self.norms[construct][questionnaire][norm_key] = sorted(
                    valid.tolist()
                )

            scores_df.loc[group_idx, 'q_cdf_score'] = c

        n_normed = (scores_df['q_cdf_score_reference'] == 'enigma_pd_norms').sum()
        n_own = (scores_df['q_cdf_score_reference'] == 'own_sample').sum()
        if n_normed > 0:
            print(f"C-scores: {n_own} rows from own-sample CDF, "
                  f"{n_normed} rows from reference norms")
        else:
            print(f"C-scores computed from own-sample CDF "
                  f"({scores_df[group_cols[0]].nunique()} questionnaire groups)")

        return scores_df

    def compute_av_cdf_scores(
        self,
        scores_df: pd.DataFrame,
        questionnaire_col: str = 'questionnaire',
    ) -> pd.DataFrame:
        """
        Questionnaire-averaged CDF integral transform (Step 5 alternative).

        For each construct × dimension group with ≥ 2 questionnaires:
          1. Estimate each questionnaire's ECDF separately: F_Q1, F_Q2, …
          2. Average them with equal weight per questionnaire (1/k each):
                 F_avg(x) = (1/k) × Σᵢ Fᵢ(x)
          3. For each participant from questionnaire Q with proportion score x:
                 transformed = F_avg⁻¹( F_Q(x) )
             — find their percentile within their own questionnaire's distribution,
               then map that percentile to the corresponding value on the average
               CDF scale.

        Large questionnaires do not dominate the
        reference distribution: every questionnaire contributes equally to F_avg
        regardless of sample size (GDS n=1816 has the same weight as HADS n=283).

        The transform preserves within-questionnaire rank ordering exactly (same
        participants rank the same relative to each other). What changes is how
        each questionnaire's distribution is aligned to a common reference.

        Stores result in column 'av_cdf_score'.
        Also stores per-questionnaire-averaged CDF norms in self.averaged_cdf_norms
        for future dataset application.
        """
        scores_df = scores_df.copy()
        scores_df['av_cdf_score'] = np.nan

        group_cols = ['construct', 'dimension']

        for (construct, dimension), group_idx in scores_df.groupby(group_cols).groups.items():
            sub = scores_df.loc[group_idx, [questionnaire_col, 'proportion_score']]
            norm_key = str(dimension)

            # Collect per-questionnaire sorted arrays (ECDFs)
            q_sorted: Dict[str, np.ndarray] = {}
            for q in sub[questionnaire_col].unique():
                vals = sub.loc[
                    sub[questionnaire_col] == q, 'proportion_score'
                ].dropna().values
                if len(vals) >= 2:
                    q_sorted[q] = np.sort(vals)

            if len(q_sorted) < 2:
                # Only one questionnaire: fall back to its own ECDF (= per-q C-score)
                continue

            # Evaluation grid: all unique observed proportion scores across questionnaires
            x_grid = np.sort(np.unique(np.concatenate(list(q_sorted.values()))))
            k = len(q_sorted)

            # Compute F_avg(x) at each grid point using midpoint ECDF rule
            f_avg = np.zeros(len(x_grid))
            for sorted_q in q_sorted.values():
                n_q = len(sorted_q)
                n_below = np.searchsorted(sorted_q, x_grid, side='left')
                n_equal = np.searchsorted(sorted_q, x_grid, side='right') - n_below
                f_avg += (n_below + 0.5 * n_equal) / n_q
            f_avg /= k

            # Deduplicate f_avg to ensure strict monotonicity for inversion
            _, unique_idx = np.unique(f_avg, return_index=True)
            x_grid_u = x_grid[unique_idx]
            f_avg_u  = f_avg[unique_idx]

            # Store norms: (x_grid, f_avg) pairs allow future datasets to use this transform
            self.averaged_cdf_norms.setdefault(construct, {})[norm_key] = {
                'x_grid': x_grid_u.tolist(),
                'f_avg':  f_avg_u.tolist(),
                'questionnaires': list(q_sorted.keys()),
                'q_sorted': {q: v.tolist() for q, v in q_sorted.items()},
            }

            # Transform each questionnaire's scores
            for q, sorted_q in q_sorted.items():
                n_q = len(sorted_q)
                q_valid = (sub[questionnaire_col] == q) & sub['proportion_score'].notna()
                q_global = group_idx[q_valid.values]
                x_vals = sub.loc[q_valid, 'proportion_score'].values

                # Step 1: F_Q(x) — per-questionnaire ECDF (midpoint rule)
                n_below = np.searchsorted(sorted_q, x_vals, side='left')
                n_equal = np.searchsorted(sorted_q, x_vals, side='right') - n_below
                p_vals  = (n_below + 0.5 * n_equal) / n_q

                # Step 2: F_avg⁻¹(p) — invert average CDF via linear interpolation
                transformed = np.interp(p_vals, f_avg_u, x_grid_u)

                scores_df.loc[q_global, 'av_cdf_score'] = transformed

        n_computed = scores_df['av_cdf_score'].notna().sum()
        n_dims = len(self.averaged_cdf_norms.get('depression', {})) + \
                 len(self.averaged_cdf_norms.get('anxiety', {})) + \
                 len(self.averaged_cdf_norms.get('sleep', {}))
        print(f"CDF-transform C-scores computed: {n_computed} rows "
              f"({n_dims} construct × dimension groups)")

        return scores_df

    # -------------------------------------------------------------------------
    # Norm saving / loading
    # -------------------------------------------------------------------------

    def save_norms(self, path: str):
        """
        Export empirical CDFs as JSON normative reference.

        Saves per-questionnaire CDFs (for q_cdf_score) and, if computed,
        questionnaire-averaged CDFs (for av_cdf_score) in a single file.

        Structure:
            {
              "per_questionnaire": {construct: {questionnaire: {dim: [...]}}},
              "averaged_cdf":      {construct: {dim: {x_grid, f_avg, q_sorted}}}
            }
        """
        if not self.norms and not self.averaged_cdf_norms:
            warnings.warn("No norms to save. Run compute_q_cdf_scores() first.")
            return

        out: Dict = {'per_questionnaire': self.norms}
        if self.averaged_cdf_norms:
            out['averaged_cdf'] = self.averaged_cdf_norms

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(out, f, indent=2)

        n_per_q = sum(
            len(dims)
            for construct in self.norms.values()
            for dims in construct.values()
        )
        print(f"Saved norms: {n_per_q} per-questionnaire CDFs → {path}")

    def load_norms(self, path: str) -> Dict:
        """
        Load pre-computed per-questionnaire normative CDFs from JSON.

        Handles the current format (with a 'per_questionnaire' key) and the
        legacy format (flat construct keys, per-questionnaire only).

        Returns
        -------
        per_questionnaire_norms : dict
            {construct: {questionnaire: {dimension: sorted_scores}}}
        """
        with open(path, 'r') as f:
            data = json.load(f)

        per_q = data['per_questionnaire'] if 'per_questionnaire' in data else data

        n_per_q = sum(len(d) for c in per_q.values() for d in c.values())
        print(f"Loaded norms: {n_per_q} per-questionnaire CDFs from {path}")
        return per_q

    # -------------------------------------------------------------------------
    # Full pipeline
    # -------------------------------------------------------------------------

    def run(
        self,
        response_path: str,
        participant_id_col: str = 'participant_id',
        questionnaire_col: str = 'questionnaire',
        missing_values: Optional[List] = None,
        norms_path: Optional[str] = None,
        site_col: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Run the full score transformation pipeline.

        Parameters
        ----------
        site_col : str, optional
            Column in the response data containing site labels, carried
            through to the output.

        Returns
        -------
        pd.DataFrame
            Long-format results with proportion scores, C-scores, and
            reliability flags.
        """
        # Load responses
        responses_df = self.load_responses(
            response_path, participant_id_col, questionnaire_col, missing_values
        )

        # Load reference norms if provided
        ref_per_q = {}
        if norms_path and Path(norms_path).exists():
            ref_per_q = self.load_norms(norms_path)

        # Compute raw + proportion scores
        print("\nComputing raw and proportion scores...")
        scores_df = self.compute_scores(responses_df, participant_id_col, questionnaire_col)

        # Carry site column into scores_df if present in responses
        if site_col and site_col in responses_df.columns:
            site_map = (responses_df[[participant_id_col, site_col]]
                        .drop_duplicates(subset=participant_id_col)
                        .set_index(participant_id_col)[site_col])
            scores_df[site_col] = scores_df[participant_id_col].map(site_map)

        # Compute per-questionnaire C-scores
        print("\nComputing per-questionnaire C-scores...")
        scores_df = self.compute_q_cdf_scores(
            scores_df, questionnaire_col,
            reference_norms=ref_per_q or None,
        )

        self._print_summary(scores_df, questionnaire_col)
        return scores_df

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------

    def export(self, scores_df: pd.DataFrame, output_dir: str):
        """
        Save results to output directory.

        Saves:
          - dimension_scores.csv  : full long-format results
          - dimension_scores_wide.csv : wide format (one column per dimension,
                                        C-scores only) for use in correlations
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Full results
        long_path = output_dir / 'dimension_scores.csv'
        scores_df.to_csv(long_path, index=False)
        print(f"\nSaved full results → {long_path}")

        # Wide format — all three score types, one column per construct × dimension
        # Useful for merging with brain imaging data and comparing approaches
        try:
            id_cols = ['participant_id', 'questionnaire']
            id_cols = [c for c in id_cols if c in scores_df.columns]

            score_types = [
                ('proportion_score',              'prop'),
                ('q_cdf_score',                   'q_cdf'),
                ('av_cdf_score',                  'av_cdf'),
            ]

            wide_parts = []
            for value_col, suffix in score_types:
                if value_col not in scores_df.columns:
                    continue
                wide = scores_df.pivot_table(
                    index=id_cols,
                    columns=['construct', 'dimension_label'],
                    values=value_col,
                    aggfunc='first',
                )
                wide.columns = [
                    f"{construct}__{dim.replace(' ', '_').replace('&', 'and')}__{suffix}"
                    for construct, dim in wide.columns
                ]
                wide_parts.append(wide)

            if wide_parts:
                wide_all = pd.concat(wide_parts, axis=1).reset_index()
                wide_path = output_dir / 'dimension_scores_wide.csv'
                wide_all.to_csv(wide_path, index=False)
                print(f"Saved wide-format scores → {wide_path}")
                print(f"  Columns: __prop (proportion), __q_cdf (per-questionnaire CDF), "
                      f"__av_cdf (averaged CDF)")
        except Exception as e:
            warnings.warn(f"Could not create wide-format output: {e}")

    def _print_summary(self, scores_df: pd.DataFrame, questionnaire_col: str):
        """Print a summary of scores and reliability flags."""
        print("\n" + "=" * 70)
        print("SCORE TRANSFORMATION SUMMARY")
        print("=" * 70)

        for construct in sorted(scores_df['construct'].unique()):
            df_c = scores_df[scores_df['construct'] == construct]
            print(f"\n{construct.upper()}")

            for dim_label in sorted(df_c['dimension_label'].unique()):
                df_d = df_c[df_c['dimension_label'] == dim_label]
                n_total = len(df_d)
                n_valid = df_d['proportion_score'].notna().sum()
                rel_counts = df_d['reliability'].value_counts().to_dict()
                mean_prop = df_d['proportion_score'].mean()
                mean_c = df_d['q_cdf_score'].mean()

                rel_str = ' | '.join(
                    f"{k}:{v}" for k, v in sorted(rel_counts.items())
                )
                print(f"  {dim_label[:40]:<40} "
                      f"n={n_valid}/{n_total}  "
                      f"prop={mean_prop:.2f}  "
                      f"q_cdf={mean_c:.2f}  "
                      f"[{rel_str}]")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Score transformation pipeline for ENIGMA-PD harmonized dimensions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage — compute scores from own sample
  python score_transformation.py \\
      --responses input/participant_responses.csv \\
      --item-mapping input/score-transformation/item_dimension_mapping.csv \\
      --max-scores input/score-transformation/max_dimension_scores.csv \\
      --output output/score-transformation \\
      --save-norms output/score-transformation/cdf_norms_enigma-pd.json

  # Apply ENIGMA-PD norms to a new study
  python score_transformation.py \\
      --responses input/new_study_responses.csv \\
      --item-mapping input/score-transformation/item_dimension_mapping.csv \\
      --max-scores input/score-transformation/max_dimension_scores.csv \\
      --load-norms output/score-transformation/cdf_norms_enigma-pd.json \\
      --output output/score-transformation/new_study
        """
    )
    parser.add_argument('--responses', '-r', required=True,
                        help='Path to participant response data CSV (wide format)')
    parser.add_argument('--item-mapping', required=True,
                        help='Path to item_dimension_mapping.csv')
    parser.add_argument('--max-scores', required=True,
                        help='Path to max_dimension_scores.csv')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory')
    parser.add_argument('--participant-id-col', default='participant_id',
                        help='Column name for participant IDs (default: participant_id)')
    parser.add_argument('--questionnaire-col', default='questionnaire',
                        help='Column name for questionnaire names (default: questionnaire)')
    parser.add_argument('--missing-values', nargs='+', type=float, default=None,
                        help='Additional missing value codes (e.g. --missing-values -9 999)')
    parser.add_argument('--save-norms', default=None,
                        help='Path to save empirical CDFs as normative reference JSON')
    parser.add_argument('--load-norms', default=None,
                        help='Path to load pre-computed normative CDFs (e.g. ENIGMA-PD norms)')
    parser.add_argument('--min-items-high', type=int, default=DEFAULT_MIN_ITEMS_HIGH,
                        help=f'Min items for high reliability flag (default: {DEFAULT_MIN_ITEMS_HIGH})')
    parser.add_argument('--min-items-moderate', type=int, default=DEFAULT_MIN_ITEMS_MODERATE,
                        help=f'Min items for moderate reliability flag (default: {DEFAULT_MIN_ITEMS_MODERATE})')
    parser.add_argument('--missing-threshold', type=float, default=0.5,
                        help='Max fraction of missing items before score set to NaN (default: 0.5)')
    parser.add_argument('--site-col', default=None,
                        help='Column name in the response CSV that contains site labels '
                             '(passed through to the output)')

    args = parser.parse_args()

    print("=" * 70)
    print("SCORE TRANSFORMATION PIPELINE")
    print(f"Responses      : {args.responses}")
    print(f"Item mapping   : {args.item_mapping}")
    print(f"Max scores     : {args.max_scores}")
    print(f"Output         : {args.output}")
    print(f"Reliability    : high ≥ {args.min_items_high} items, "
          f"moderate ≥ {args.min_items_moderate} items")
    if args.load_norms:
        print(f"Norms (load)   : {args.load_norms}")
    if args.save_norms:
        print(f"Norms (save)   : {args.save_norms}")
    print("=" * 70)

    transformer = ScoreTransformer(
        min_items_high=args.min_items_high,
        min_items_moderate=args.min_items_moderate,
        missing_threshold=args.missing_threshold,
    )
    transformer.load_mapping(args.item_mapping, args.max_scores)

    scores_df = transformer.run(
        response_path=args.responses,
        participant_id_col=args.participant_id_col,
        questionnaire_col=args.questionnaire_col,
        missing_values=args.missing_values,
        norms_path=args.load_norms,
        site_col=args.site_col,
    )

    transformer.export(scores_df, args.output)

    if args.save_norms:
        transformer.save_norms(args.save_norms)


if __name__ == '__main__':
    main()
