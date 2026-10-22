# HarmoniCA web app

The browser app of [HarmoniCA](https://github.com/julia-pfarr/HarmoniCA), built with Streamlit. It harmonizes questionnaire items with the HarmoniCA engine (reusing the inventory of already harmonized questionnaires wherever possible) and offers code to turn your participants' item responses into dimension scores. Model weights are not bundled; they are downloaded when the model has to run.

## Start

The app lives in this repository and is not part of the PyPI package. It uses the same engine, inventory file (`src/harmonica/inventory/harmonized_inventory.csv`), model folder (`src/harmonica/models`) and dimension definitions as the `harmonica` command, so both tools give the same results. From a checkout, with Python 3.13 or newer:

```bash
pip install -e ..                      # the HarmoniCA engine (the repository root)
pip install -r requirements.txt        # Streamlit and the app's dependencies
python -m streamlit run app.py --server.address 127.0.0.1
```

Open http://localhost:8501 and stop with Ctrl+C. Run it from inside this folder so that `.streamlit/config.toml` (theme) is loaded. Without the engine the app shows a message instead of the steps. Instead of installing the engine you can point the app at the source tree: `HARMONICA_SOURCE_DIR=../src python -m streamlit run app.py`. The header shows whether the engine was found.

## Three ways to start

The **inventory** holds questionnaires that are already harmonized, so researchers can reuse them in their own study. Step 1 (**Upload**) shows two panels side by side, and the line underneath tells you how many items come from each:

- **Inventory only**: pick questionnaires in *From the inventory*. Everything is reused instantly, with no model download.
- **Inventory + new**: pick from the inventory and also upload your own files in *Your new questionnaires*. Inventory items are reused, new ones go through the model.
- **New only**: only upload your own CSV/Excel files. Everything goes through the model, which needs model downloads.

On **Review & confirm**, every item from your files that we think is already in the inventory is listed as a **possible duplicate** (same item ID and wording, or same wording under a different item ID). Tick *Same item?* to reuse the inventory assignment; untick it to send the item to the model. Everything starts ticked, and unticking is the only way to force a model run. The three cards at the top (from the inventory, possible duplicates, items sent to the model) update as you answer. Then press **Run harmonization**, and open **Results**, then **Overview** and **Review items**.

**Results** has three subpages:

- **Overview**: a summary and a table of all harmonized items, with **Download output** (the harmonized items as CSV) at the end. While model-predicted items with low confidence are still unreviewed, a short hint at the top links to **Review items**.
- **Review items**: a list of all flagged items that the **model predicted** (confidence below the threshold, or no confidence), one table per construct. Items reused from the inventory are expert consensus: they are never listed here and can never be changed. For each item choose *Accept* or *Change to* another dimension. Nothing is preselected. The confidence threshold is set here, at the top of the subpage.
- **Explore results**: the questionnaire → dimension landscape (charts).

## Look and feel

The header is assembled from three crops of `assets/logo.png` (`logo_mark.png`, `logo_wordmark.png`, `logo_tagline.png`) on a white page, and the browser tab uses `assets/favicon.png` (the waveform mark). The colours come from the logo: petrol blue `#0F4C6B` for interface accents, and the colours of its pills for charts and highlights. They are defined once as CSS variables at the top of `app.py` (`:root`), mirrored in `.streamlit/config.toml` and `visuals.py`.

## Input files

Uploaded CSV/Excel files need six columns: `construct`, `questionnaire`, `item_id`, `item_text`, **`answer_options`** and **`scoring`**. `scoring` is a list with one numeric score per answer option, for example `[0, 1, 2, 3]`; the score transformation uses it to get each item's maximum score, so it must contain at least one number. `answer_options` lists the answer choices and only has to be filled in. For a questionnaire that is neither in the inventory nor in the bundled definitions, this upload is the only source of its scoring; the score transformation reads only the highest `scoring` value per item (the item's maximum score), and your participants' responses must already be the numeric item scores (reverse-scored where needed). The template (`example_items.csv`) shows the format.

Questionnaires picked from the inventory bring their answer options and scoring along where we have them (`assets/questionnaire_response_options.csv`, compiled from the ENIGMA-PD `questionnaire_response-options.csv` and `questionnaire_model-testing - complete.csv`; 726 of the 895 inventory items). The two source files write some item IDs differently from the inventory (for example `PAS_A1` vs `PAS_A.1`, `NPI_E_01` vs `NPI_E_1`); for 63 items (PAS, NPI, STAI, NMSS) the IDs in the asset were aligned to the inventory's, and the original ID is kept in the `original_item_id` column. Inventory items without definitions can be harmonized but not scored; the Score transformation step lists them. Still missing are SMGAD, CAPE-P15, PQ-B, PSQI and NMSSQuest; the inventory's "data-augmentation" entries are not real questionnaires and cannot be scored. Some bundled `answer_options` lists are malformed or differ in length from `scoring` (for example PDSS, QUIP-CS, NPI, PANAS, TEPS); the score transformation does not read `answer_options`, so scores are not affected.

## Explore results

Everything is shown at once, one section per construct, with two figures each:

- Sankey flow: questionnaire items → construct dimensions, with counts on hover.
- Confidence histogram.

For detailed exploration, use the downloaded CSV in your own analysis software. Each construct is shown separately so dimensions remain comparable. Charts canonicalize labels by dimension ID because reference labels can differ from the current catalog. Original output labels stay intact in exports and the item inspector. Confidence from stored inventory entries can describe expert agreement; it must not be assumed to be a fresh model probability or calibrated correctness estimate. Distributions are shown only when actually returned by the engine.

## Score transformation (step 5)

The last step offers a ZIP with the research score-transformation code. Put the harmonized CSV from **Results** (as `harmonized_items.csv`) and your participants' item responses (as `responses.csv`) next to `run_score_transformation.py`, then run:

```
python run_score_transformation.py
```

Other file names or locations can be given with `--harmonized` and `--responses`; results go to a folder called `scores` (`--output`).

The ZIP contains one script to run, `run_score_transformation.py` (a thin wrapper that builds the item-dimension mapping from the harmonized CSV and runs the pipeline), plus `requirements.txt` (pandas, numpy), a README, the licence note and a `research_code/` folder with `score_transformation.py` and `create_item_dimension_mapping.py`, the research code, unchanged. Responses are one row per participant with one column per item (numeric item scores, missing = empty or -9). Items without scoring and items assigned to dimension -1 are left out. The step also offers a header-only responses template for the questionnaires in your result.

## Reusable harmonized outputs

**harmonized_items.csv** contains the HarmoniCA item-to-dimension assignments with construct, questionnaire, item_id, item_text, dimension, dimension_label, confidence, source, probability_distribution (when returned), original_dimension and original_dimension_label. Use the composite key (construct, questionnaire, item_id) in downstream workflows.

The CSV also carries each item's `answer_options` and `scoring`, so it is all the score transformation needs. `source` says where each item's assignment comes from: `inventory` (reused, expert consensus), `model` (predicted in this run) or `expert_reviewed`. Review decisions are part of the file: model-predicted items you accepted or changed in **Review items** get `source = expert_reviewed`; inventory items are never changed. For a changed item, `dimension` and `dimension_label` hold your new choice, and the model's original assignment is kept in `original_dimension` and `original_dimension_label` (empty for items you did not change). `confidence` is always the model's score for its original assignment. Items you did not review keep their original source. The Overview table and the charts show the reviewed result too. Decisions are held in the browser session, so download the CSV before closing the page. A new run clears previous results and decisions.

These are **harmonized item mappings**, not participant-level harmonized scores. Creating those scores requires response data, scale coding, reverse-scoring rules, missing-data handling, and a documented scoring method.

## How it runs

Each run seeds a private copy of the engine's inventory (the models need it as their reference pool) in a separate temporary working directory and never edits the original; the rows the model adds to that copy come back as the **New inventory rows** download on Results, exactly what the `harmonica` command would append to the inventory. Changed wording under an existing item ID cannot silently retrieve a stale cached assignment, and an item with the same wording under a different ID is reused only if you confirm it on **Review & confirm**. Output item IDs and counts must match the submitted input before results are accepted. Model weights are read from, and downloaded to, the engine's model folder (`HARMONICA_MODELS_DIR` overrides it); downloads need internet and disk space, and initial inference can take several minutes. Runs stop automatically after 30 minutes (shown on the Harmonization page). This is a local research app, not a public multi-user service.

Optional environment variables: `HARMONICA_MODELS_DIR` (persistent model path) and `HARMONICA_SOURCE_DIR` (absolute path of the repository's `src` directory, to use a source checkout instead of an installed package).

## Files in this folder

| File | Purpose |
|---|---|
| `app.py` | The five-step interface (Upload, Review & confirm, Harmonization, Results, Score transformation) |
| `backend.py` | Reads and validates the items files, checks items against the inventory, starts the engine |
| `engine_worker.py` | Runs the HarmoniCA engine in an isolated process with the user's confirmations |
| `visuals.py` | The two charts on Explore results, in the logo palette |
| `score_kit.py` | Builds the score-transformation ZIP, the responses template and the "not included" list |
| `assets/` | Answer options and scoring (`questionnaire_response_options.csv`), the score-transformation code, logo files |
| `example_items.csv` | The input template offered on the Upload step |
| `.streamlit/config.toml` | Theme and toolbar settings |

## Attribution

The inventory, the constructs and the dimension definitions come from the HarmoniCA engine itself. See `assets/UPSTREAM_LICENSE` (CC BY-NC 4.0).

## Tests

There is no automated test suite for this app in the repository yet. The repository's `tests/` cover the command-line package and the engine.

## Multiple questionnaire files

Upload several CSV and XLSX files together. Choose one worksheet and map the six required columns (construct, questionnaire, item_id, item_text, answer_options, scoring) separately for each file. Every file must validate before running. The combined input remains limited to 10,000 items; duplicate composite item keys are rejected rather than silently removed. Preserve distinct questionnaire names when comparing instruments. Upload only one format per questionnaire.
