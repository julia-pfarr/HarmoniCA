"""
HarmoniCA — Harmonised Construct Assignment

Workflow:
  1. Check inventory: if the questionnaire is already known, return stored assignments.
  2. If not found: run the fine-tuned model for the given construct, store new items
     in the inventory, and return assignments.
"""

import json
import re
import contextlib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Callable, List, Dict, Optional

from .config import BEST_MODEL, KNN_K, KNN_ALPHA, BASE_MODEL_NAMES, DIMENSION_DESCRIPTIONS, HF_REPOS


# ---------------------------------------------------------------------------
# Item-text normalisation, used to detect the same item under a different
# item_id coding (e.g. 'PHQ9_1' vs the inventory's 'PHQ-9_01').
# ---------------------------------------------------------------------------

def _auto_device() -> str:
    try:
        import torch
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    except ImportError:
        return 'cpu'


def _normalize_item_text(text) -> str:
    text = str(text).strip().lower()
    text = re.sub(r'\s+', ' ', text)
    text = text.strip(' .?!"\'')
    return text


# ---------------------------------------------------------------------------
# Tokeniser-config compatibility fix (needed for some fine-tuned T5 encoders)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _fix_tokenizer_config(encoder_dir: Path):
    import json as _json
    config_path = encoder_dir / 'tokenizer_config.json'
    if not config_path.exists():
        yield
        return
    with open(config_path) as f:
        original_text = f.read()
    data = _json.loads(original_text)
    if isinstance(data.get('extra_special_tokens'), list):
        data['extra_special_tokens'] = {}
        with open(config_path, 'w') as f:
            _json.dump(data, f, indent=2)
        try:
            yield
        finally:
            with open(config_path, 'w') as f:
                f.write(original_text)
    else:
        yield


# ---------------------------------------------------------------------------
# kNN helpers
# ---------------------------------------------------------------------------

def _knn_predict_proba(
    item_embs: np.ndarray,
    pool_embs: np.ndarray,
    pool_dims: list,
    dimensions: list,
    k: int = 5,
) -> np.ndarray:
    dim_to_idx = {d: i for i, d in enumerate(dimensions)}
    k = min(k, len(pool_dims))
    sims  = item_embs @ pool_embs.T
    proba = np.zeros((len(item_embs), len(dimensions)))
    for i in range(len(item_embs)):
        top_k  = np.argsort(sims[i])[-k:][::-1]
        top_s  = sims[i][top_k]
        exp_s  = np.exp(top_s - top_s.max())
        weights = exp_s / exp_s.sum()
        for w, j in zip(weights, top_k):
            d = pool_dims[j]
            if d in dim_to_idx:
                proba[i, dim_to_idx[d]] += w
    return proba


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class HarmoniCA:
    """
    Main interface for HarmoniCA dimension assignment.

    Parameters
    ----------
    models_dir : path to the models/ directory (contains one subfolder per construct)
    inventory_path : path to harmonized_inventory.csv
    device : 'cuda' or 'cpu' for the fine-tuned models. Defaults to 'cuda' if a
             GPU is available, else 'cpu'.
    """

    def __init__(self, models_dir: str, inventory_path: str, device: Optional[str] = None):
        self.models_dir     = Path(models_dir)
        self.inventory_path = Path(inventory_path)
        self.inventory      = pd.read_csv(inventory_path)
        self.device         = device or _auto_device()
        self._loaded_models: Dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def harmonize(
        self,
        questionnaire: str,
        construct: str,
        items: List[Dict],
        force_rerun: bool = False,
        confirm_match: Optional[Callable[[Dict, Dict], bool]] = None,
    ) -> Dict:
        """
        Assign items from a questionnaire to construct dimensions.

        Parameters
        ----------
        questionnaire : questionnaire name (e.g. 'PHQ-9')
        construct     : one of 'depression', 'apathy', 'psychosis', 'anxiety',
                        'sleep', 'impulse_control'
        items         : list of dicts with keys 'item_id' and 'item_text'
        force_rerun   : skip inventory lookup and always run the model
        confirm_match : called as `confirm_match(user_item, inventory_row)` when an
                        item's text matches an inventory item under a *different*
                        item_id (e.g. 'PHQ9_1' vs the inventory's 'PHQ-9_01').
                        Return True to reuse the inventory's assignment, False to
                        treat it as a new item and run the model. Defaults to an
                        interactive y/n prompt on the terminal; pass your own
                        callable for non-interactive / programmatic use.

        Returns
        -------
        dict with keys:
          'assignments' : list of dicts (item_id, item_text, dimension,
                          dimension_label, confidence)
          'source'      : 'inventory', 'model', or 'mixed'
          'questionnaire': questionnaire name
          'construct'   : construct name
        """
        if construct not in BEST_MODEL:
            raise ValueError(
                f"Unknown construct '{construct}'. "
                f"Supported: {list(BEST_MODEL.keys())}"
            )

        # 1. Check inventory — reuse whatever is already cached, only run the
        #    model for items that are missing.
        if force_rerun:
            cached, missing_items = [], items
        else:
            cached, missing_items = self._check_inventory(questionnaire, construct, items)
            if missing_items:
                cached, missing_items = self._resolve_id_mismatches(
                    questionnaire, construct, cached, missing_items,
                    confirm_match or self._default_confirm_match,
                )

        if not missing_items:
            return {
                'assignments':  cached,
                'source':       'inventory',
                'questionnaire': questionnaire,
                'construct':    construct,
            }

        # 2. Run model on the missing items only
        print(f"[HarmoniCA] Running model for {len(missing_items)} item(s) of "
              f"'{questionnaire}' ({construct})...")
        new_assignments = self._run_model(construct, missing_items)

        # 3. Update inventory with the newly predicted items
        self._update_inventory(questionnaire, construct, new_assignments)

        # 4. Merge cached + newly predicted assignments, preserving input order
        order = {it['item_id']: i for i, it in enumerate(items)}
        assignments = sorted(cached + new_assignments, key=lambda a: order[a['item_id']])

        return {
            'assignments':  assignments,
            'source':       'model' if not cached else 'mixed',
            'questionnaire': questionnaire,
            'construct':    construct,
        }

    # ------------------------------------------------------------------
    # Inventory helpers
    # ------------------------------------------------------------------

    def _check_inventory(
        self,
        questionnaire: str,
        construct: str,
        items: List[Dict],
    ) -> "tuple[List[Dict], List[Dict]]":
        """
        Split `items` into those already assigned in the inventory and those
        that still need to be run through the model.

        Returns
        -------
        (cached_assignments, missing_items)
        """
        sub = self.inventory[
            (self.inventory['questionnaire'] == questionnaire) &
            (self.inventory['construct'] == construct)
        ]
        if len(sub) == 0:
            return [], items

        # Match on item_id (dedupe in case the inventory has repeat rows)
        matched = sub.drop_duplicates(subset='item_id', keep='last')
        matched = matched[matched['item_id'].isin({it['item_id'] for it in items})]
        matched_ids = set(matched['item_id'])
        missing_items = [it for it in items if it['item_id'] not in matched_ids]

        if missing_items:
            print(f"[HarmoniCA] '{questionnaire}' partially found in inventory "
                  f"({len(matched)}/{len(items)} items). Running model for "
                  f"{len(missing_items)} new item(s).")
        else:
            print(f"[HarmoniCA] '{questionnaire}' found in inventory ({len(matched)} items).")

        cached = matched[[
            'item_id', 'item_text', 'dimension', 'dimension_label', 'confidence'
        ]].to_dict('records')
        return cached, missing_items

    def _find_id_mismatch_candidates(
        self,
        questionnaire: str,
        construct: str,
        missing_items: List[Dict],
    ) -> "list[tuple[Dict, pd.Series]]":
        """
        Among items with no item_id match, find those whose (normalized) text
        matches an inventory item under a different item_id — a likely sign the
        questionnaire is already in the inventory but coded differently.

        Returns a list of (user_item, inventory_row) pairs. Pure lookup, no
        side effects — used both by `_resolve_id_mismatches` (CLI/library, via
        `confirm_match`) and by UIs that want to show candidates for review
        before deciding.
        """
        sub = self.inventory[
            (self.inventory['questionnaire'] == questionnaire) &
            (self.inventory['construct'] == construct)
        ]
        if len(sub) == 0:
            return []

        text_to_row = {}
        for _, row in sub.iterrows():
            text_to_row.setdefault(_normalize_item_text(row['item_text']), row)

        candidates = []
        for it in missing_items:
            inv_row = text_to_row.get(_normalize_item_text(it['item_text']))
            if inv_row is not None:
                candidates.append((it, inv_row))
        return candidates

    def _resolve_id_mismatches(
        self,
        questionnaire: str,
        construct: str,
        cached: List[Dict],
        missing_items: List[Dict],
        confirm_match: Callable[[Dict, Dict], bool],
    ) -> "tuple[List[Dict], List[Dict]]":
        """
        Ask `confirm_match` whether to reuse the inventory's assignment for each
        item found by `_find_id_mismatch_candidates`.
        """
        candidates = self._find_id_mismatch_candidates(questionnaire, construct, missing_items)
        candidate_ids = {it['item_id'] for it, _ in candidates}
        still_missing = [it for it in missing_items if it['item_id'] not in candidate_ids]

        for it, inv_row in candidates:
            if confirm_match(it, inv_row):
                print(f"[HarmoniCA] Reusing inventory assignment for '{it['item_id']}' "
                      f"(matched by text to '{inv_row['item_id']}').")
                cached.append({
                    'item_id':        it['item_id'],
                    'item_text':      it['item_text'],
                    'dimension':      int(inv_row['dimension']),
                    'dimension_label':inv_row['dimension_label'],
                    'confidence':     float(inv_row['confidence']),
                })
            else:
                print(f"[HarmoniCA] Treating '{it['item_id']}' as a new item.")
                still_missing.append(it)

        return cached, still_missing

    @staticmethod
    def _default_confirm_match(user_item: Dict, inv_row: Dict) -> bool:
        prompt = (
            f"\n[HarmoniCA] Item '{user_item['item_id']}' ({user_item['item_text']!r}) "
            f"looks identical to inventory item '{inv_row['item_id']}' "
            f"({inv_row['item_text']!r}), already assigned to dimension "
            f"{inv_row['dimension']} ({inv_row['dimension_label']}).\n"
            f"Did you mean this item? Reuse its assignment instead of re-running the model? [y/N]: "
        )
        answer = input(prompt).strip().lower()
        return answer in ('y', 'yes')

    def _update_inventory(
        self,
        questionnaire: str,
        construct: str,
        assignments: List[Dict],
    ):
        now = datetime.utcnow().isoformat()
        new_rows = []
        for a in assignments:
            new_rows.append({
                'item_id':        a['item_id'],
                'item_text':      a['item_text'],
                'construct':      construct,
                'questionnaire':  questionnaire,
                'dimension':      a['dimension'],
                'dimension_label':a['dimension_label'],
                'confidence':     a['confidence'],
                'source':         'model_prediction',
                'date_added':     now,

                'model_version':  BEST_MODEL[construct],
            })
        self.inventory = pd.concat(
            [self.inventory, pd.DataFrame(new_rows)], ignore_index=True
        )
        self.inventory.to_csv(self.inventory_path, index=False)
        print(f"[HarmoniCA] Inventory updated: +{len(new_rows)} items for '{questionnaire}'.")

    # ------------------------------------------------------------------
    # Model inference
    # ------------------------------------------------------------------

    def _run_model(self, construct: str, items: List[Dict]) -> List[Dict]:
        model_type = BEST_MODEL[construct]
        item_texts = [it['item_text'] for it in items]

        if model_type == 'ft':
            return self._predict_finetuned(construct, items, item_texts)
        elif model_type == 'ft_knn':
            return self._predict_finetuned_knn(construct, items, item_texts)
        elif model_type == 'base_knn':
            return self._predict_base_knn(construct, items, item_texts)
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    def _ensure_model_downloaded(self, construct: str):
        """Download model from HuggingFace if not cached locally."""
        construct_dir    = self.models_dir / construct
        contrastive_path = construct_dir / 'contrastive_model.pkl'
        prototype_path   = construct_dir / 'prototype_model.pkl'

        if contrastive_path.exists() or prototype_path.exists():
            return  # already available locally

        repo_id = HF_REPOS.get(construct)
        if repo_id is None:
            raise FileNotFoundError(
                f"No model found for '{construct}' in {construct_dir} and no HuggingFace "
                f"repo is configured for this construct.\n"
                f"Either run scripts/setup_encoders.py --source <local-models-dir>, or "
                f"set HF_REPOS['{construct}'] in harmonica/config.py."
            )

        print(f"[HarmoniCA] Downloading '{construct}' model from {repo_id} ...")
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo_id, local_dir=str(construct_dir))
        print(f"[HarmoniCA] '{construct}' model downloaded.")

    def _load_finetuned_model(self, construct: str):
        if construct in self._loaded_models:
            return self._loaded_models[construct]

        self._ensure_model_downloaded(construct)

        from .models import ContrastiveModel, PrototypeModel

        construct_dir    = self.models_dir / construct
        contrastive_path = construct_dir / 'contrastive_model.pkl'
        prototype_path   = construct_dir / 'prototype_model.pkl'

        if contrastive_path.exists():
            model_path  = contrastive_path
            model_class = ContrastiveModel
            encoder_dir = construct_dir / 'contrastive_model_encoder'
        elif prototype_path.exists():
            model_path  = prototype_path
            model_class = PrototypeModel
            encoder_dir = construct_dir / 'prototype_model_encoder'
        else:
            raise FileNotFoundError(
                f"No model found for '{construct}' in {construct_dir}."
            )

        with _fix_tokenizer_config(encoder_dir):
            model = model_class.load(str(model_path), device=self.device)

        self._loaded_models[construct] = model
        return model

    def _predict_finetuned(
        self, construct: str, items: List[Dict], item_texts: list
    ) -> List[Dict]:
        model  = self._load_finetuned_model(construct)
        preds  = model.predict(item_texts)
        probs  = model.predict_proba(item_texts)
        labels = dict(zip(model.dimensions, model.dimension_labels))

        results = []
        for i, it in enumerate(items):
            dim     = int(preds[i])
            dim_idx = model.dimensions.index(dim)
            results.append({
                'item_id':        it['item_id'],
                'item_text':      it['item_text'],
                'dimension':      dim,
                'dimension_label':labels.get(dim, f'Dim {dim}'),
                'confidence':     round(float(probs[i, dim_idx]), 4),
                'probability_distribution': {
                    int(model.dimensions[j]): round(float(probs[i, j]), 4)
                    for j in range(len(model.dimensions))
                },
            })
        return results

    def _predict_finetuned_knn(
        self, construct: str, items: List[Dict], item_texts: list
    ) -> List[Dict]:
        alpha  = KNN_ALPHA.get(construct, 0.5)
        model  = self._load_finetuned_model(construct)
        ft_probs = model.predict_proba(item_texts)

        # Encode items and inventory pool
        item_embs = model.encoder.encode(item_texts, convert_to_numpy=True, show_progress_bar=False)
        item_embs = item_embs / (np.linalg.norm(item_embs, axis=1, keepdims=True) + 1e-10)

        pool_df = self.inventory[
            (self.inventory['construct'] == construct) &
            (self.inventory['dimension'].isin(model.dimensions))
        ].dropna(subset=['item_text', 'dimension'])
        pool_texts = pool_df['item_text'].tolist()
        pool_dims  = pool_df['dimension'].astype(int).tolist()

        pool_embs = model.encoder.encode(pool_texts, convert_to_numpy=True, show_progress_bar=False)
        pool_embs = pool_embs / (np.linalg.norm(pool_embs, axis=1, keepdims=True) + 1e-10)

        knn_proba = _knn_predict_proba(item_embs, pool_embs, pool_dims, model.dimensions, KNN_K)
        blended   = alpha * ft_probs + (1.0 - alpha) * knn_proba

        labels = dict(zip(model.dimensions, model.dimension_labels))
        results = []
        for i, it in enumerate(items):
            dim_idx = int(np.argmax(blended[i]))
            dim     = int(model.dimensions[dim_idx])
            results.append({
                'item_id':        it['item_id'],
                'item_text':      it['item_text'],
                'dimension':      dim,
                'dimension_label':labels.get(dim, f'Dim {dim}'),
                'confidence':     round(float(blended[i, dim_idx]), 4),
                'probability_distribution': {
                    int(model.dimensions[j]): round(float(blended[i, j]), 4)
                    for j in range(len(model.dimensions))
                },
            })
        return results

    def _predict_base_knn(
        self, construct: str, items: List[Dict], item_texts: list
    ) -> List[Dict]:
        from sentence_transformers import SentenceTransformer

        base_model_name = BASE_MODEL_NAMES[construct]
        dim_defs   = DIMENSION_DESCRIPTIONS[construct]
        dim_ids    = sorted(dim_defs.keys())
        dim_labels = {d: dim_defs[d]['label'] for d in dim_ids}

        model = SentenceTransformer(base_model_name, device=self.device)

        item_embs = model.encode(item_texts, convert_to_numpy=True, show_progress_bar=False)
        item_embs = item_embs / (np.linalg.norm(item_embs, axis=1, keepdims=True) + 1e-10)

        pool_df = self.inventory[
            (self.inventory['construct'] == construct) &
            (self.inventory['dimension'].isin(dim_ids))
        ].dropna(subset=['item_text', 'dimension'])
        pool_texts = pool_df['item_text'].tolist()
        pool_dims  = pool_df['dimension'].astype(int).tolist()

        pool_embs = model.encode(pool_texts, convert_to_numpy=True, show_progress_bar=False)
        pool_embs = pool_embs / (np.linalg.norm(pool_embs, axis=1, keepdims=True) + 1e-10)

        proba = _knn_predict_proba(item_embs, pool_embs, pool_dims, dim_ids, KNN_K)

        results = []
        for i, it in enumerate(items):
            dim_idx = int(np.argmax(proba[i]))
            dim     = int(dim_ids[dim_idx])
            results.append({
                'item_id':        it['item_id'],
                'item_text':      it['item_text'],
                'dimension':      dim,
                'dimension_label':dim_labels.get(dim, f'Dim {dim}'),
                'confidence':     round(float(proba[i, dim_idx]), 4),
                'probability_distribution': {
                    int(dim_ids[j]): round(float(proba[i, j]), 4)
                    for j in range(len(dim_ids))
                },
            })
        return results
