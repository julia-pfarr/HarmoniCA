# Changelog

All notable changes to HarmoniCA are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Replace "Unreleased" with the version and date when you tag the release.

### Added

- **Web app** in `harmonica-ui/` (Streamlit, run from a clone; it is not part of the PyPI package). Five steps: pick questionnaires from the inventory and/or upload your own, review possible duplicates, run the harmonization, work with the results, and download the research score-transformation code.
  - Results: table of harmonized items, review of low-confidence model predictions (inventory items are expert consensus and are never changed), charts, and the CSV download.
  - A second download, "New inventory rows", with the model predictions in the inventory's file format, for contributing them by pull request.
- `harmonica --duplicates {ask,same,new}`: decide items that match an inventory item under a different `item_id` without being asked.
- Optional `answer_options` and `scoring` columns in the items CSV are carried into the results file, so the command-line output also works with the web app's score transformation.
- The engine now reports where each assignment comes from: every assignment returned by `HarmoniCA.harmonize()` has a `source` (`inventory` or `model`). The existing per-questionnaire `result['source']` is unchanged.
- Tests for the per-item `source` and for the command line's output columns, input handling and `--duplicates`.

### Changed

- **Breaking:** at the duplicate prompt, pressing Enter now means "same item" (it used to mean "no"). Use `--duplicates new` to keep the old behaviour in scripts.
- **Breaking:** the results file has the columns `construct`, `questionnaire`, `item_id`, `item_text`, `dimension`, `dimension_label`, `confidence`, `source`, and `source` is now set per item (`inventory` or `model`) instead of per questionnaire (`inventory`, `model` or `mixed`). The web app writes the same columns.
- The items CSV is read as text; whitespace is trimmed and `construct` is read in lower case, as in the web app.
- Both the command line and the web app use the same inventory file, model folder and dimension definitions, so they give the same results for the same input.
- README: new section for the web app, a comparison of the terminal tool and the web app, a repository layout, and absolute links so that the README renders correctly on PyPI.

### Removed

- **Breaking:** the Gradio web UI, with the `harmonica-ui` console command and the `pyHarmoniCA[ui]` extra. Use the Streamlit app in `harmonica-ui/` instead.
- Files that belonged to the Gradio UI or were stale: `deploy/`, the root `app.py` and `requirements.txt`, `log_changes/`, `examples/scoring-test/`, and the Gradio tests.

### Not changed

- The offline scoring bundle of the command line (`--scoring-bundle`) is unchanged. It uses raw answers and a scoring lookup, whereas step 5 of the web app ships the research score-transformation code, which expects numeric item scores.
