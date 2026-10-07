# HarmoniCA visual research workspace 

An independent Streamlit frontend for julia-pfarr/HarmoniCA, inspected at commit b074bf07970959b4d5021e2cfbeff34a6b012385. This dashboard calls the actual upstream Python API. The source model strategy and dimension catalog are included with attribution; model weights are not bundled.

## Start

Extract this ZIP into a new directory. Open a terminal **inside harmonica-ui**. Activate the Python environment in which HarmoniCA is installed (upstream package requires Python 3.13+).

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Open http://localhost:8501 . Stop with Ctrl+C. Running inside this folder loads the included light-theme configuration.

If the engine is missing, follow https://github.com/julia-pfarr/HarmoniCA to install the project in this same environment. A similarly named package is not a substitute.

## First real run, without model downloads

In **Prepare**, choose **Explore reference inventory** to inspect stored assignments, **Upload files** to map CSV/Excel columns, or **Enter items manually** to add questionnaire items one at a time. Manual entries require construct, questionnaire, item ID, wording, answer options, and scoring, then move through inventory review and results. Exact matches and confirmed duplicates are reused; only new model predictions are appended to the local `harmonized_inventory.csv`. New-item inference requires model downloads.

Uploaded CSV or Excel files need the same six fields as manual entries: construct, questionnaire, item_id, item_text, answer_options and scoring. Empty cells are rejected. Items taken from **Explore reference inventory** only need the first four. In **Inventory check**, items with the same wording as an inventory item under a different item ID are listed as possible duplicates. Each one has a `same_item?` checkbox, checked by default, so its inventory assignment is reused. Unchecking it sends the item to the model as a new item.

For the existing dashboard workflow, upload CSV/Excel or choose **Explore reference inventory**, select a construct and questionnaires, then run from **Inventory check**. Open **Visual dashboard** and **Item inspector** to explore and review assignments. Force model rerun skips stored assignments.

Open `dashboard_preview.html` directly in a browser for a standalone visual preview using real upstream anxiety inventory entries. This HTML is a reference-data preview, not a model-inference test.

## Dashboard

- Sankey flow: questionnaire items → construct dimensions, with counts on hover.
- Coverage heatmap: counts or within-questionnaire percentages.
- Confidence histogram and review threshold.
- Construct, questionnaire and dimension filters linked to item cards.
- Item inspector: actual model assignment, available dimension distribution, and review decisions.
- Model catalog: all six supported constructs, dimension definitions, model strategies and upstream model links.

Only one construct is compared at a time. Charts canonicalize labels by dimension ID because reference labels can differ from the current catalog. Original output labels stay intact in exports and the item inspector. Confidence from stored inventory entries can describe expert agreement; it must not be assumed to be a fresh model probability or calibrated correctness estimate. Distributions are shown only when actually returned by the engine.

## Reusable harmonized outputs

**harmonized_items.csv** contains actual HarmoniCA item-to-dimension assignments with construct, questionnaire, item_id, item_text, dimension, dimension_label, confidence, source, and probability_distribution when returned. Use the composite key (construct, questionnaire, item_id) in downstream workflows.

The analysis ZIP also contains:
- reviewed_harmonized_items.csv: original predictions plus explicit review decisions; effective_dimension/effective_dimension_label incorporate Changed decisions.
- researcher_review.csv: review audit trail.
- submitted_items.csv: cleaned engine inputs.
- run_record.json: input hashes, timestamp, selected constructs, item counts, pinned source reference.
- engine.log and OUTPUT_README.txt.

Pending and Uncertain assignments remain flagged. The interface does not silently certify them. Save decisions with the inspector's button before exporting. Input changes clear previous results and decisions.

These are **harmonized item mappings**, not participant-level harmonized scores. Creating those scores requires response data, scale coding, reverse-scoring rules, missing-data handling, and a documented scoring method.

## Integration corrections

The earlier frontend passed a nonexistent inventory file. This version seeds each run with a private copy of the full upstream reference inventory, which is also needed by kNN models. It does not edit the original inventory. Changed wording under an existing item ID cannot silently retrieve a stale cached assignment. Matching wording under a different ID is processed as new rather than prompting on a hidden terminal. Upstream model weights and algorithms are unchanged. Output item IDs and counts must match the submitted input before results are accepted.

All runs use a separate temporary working directory. Model cache: ~/.cache/harmonica-ui/models . Downloads need internet and disk space; initial inference can take several minutes. Operations are synchronous with a configurable timeout. This is a local research app, not a public multiuser service.

Optional operator variables: HARMONICA_MODELS_DIR (persistent model path); HARMONICA_SOURCE_DIR (absolute upstream src directory, for a source checkout rather than an installed package).

## Attribution

Upstream project: https://github.com/julia-pfarr/HarmoniCA . Assets/reference_inventory.csv is copied from its inventory; assets/model_catalog.json is derived from its config.py. No modification to reference inventory content; reference explorer deduplicates repeated IDs for display. See assets/UPSTREAM_LICENSE (CC BY-NC 4.0). Independent frontend; no official affiliation is claimed.

## Tested

Actual inventory execution passed for 895 unique reference items across all six constructs. Real anxiety inference on new wording also passed with downloaded upstream weights. All 15 upstream tests passed, and Streamlit dashboard interaction checks passed. Other models were not inference-tested. See VALIDATION.md and inference_verification.txt.

## Multiple questionnaire files

Upload several CSV and XLSX files together. Choose one worksheet and map the four required columns separately for each file. Every file must validate before running. The combined input remains limited to 10,000 items; duplicate composite item keys are rejected rather than silently removed. Preserve distinct questionnaire names when comparing instruments. Upload only one format per questionnaire. The coverage map and grouped percentage bars compare item composition within one construct, not patient severity.
