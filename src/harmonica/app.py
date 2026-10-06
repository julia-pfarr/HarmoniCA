"""
HarmoniCA — Gradio web UI.

Run locally with:
    harmonica-ui
or:
    python -m harmonica.app

Three tabs (the Data Harmonizer lives in the ``harmonica.uploader`` package):
  - Harmonize: upload an items CSV, review any possible item_id/coding
    mismatches against the inventory, run harmonization, download results.
  - Inventory Browser: search/filter the existing harmonized_inventory.csv.
  - Data Harmonizer: enter or upload items under the same rules as "Check inventory"
    and see how many are already in the inventory, duplicates, or new.
"""
from pathlib import Path

import gradio as gr
import pandas as pd

from harmonica.harmonica import HarmoniCA
from harmonica.harmonica.config import CONSTRUCTS
from harmonica.uploader.inventory_check import DUPLICATE_COLUMNS, check_items_against_inventory
from harmonica.uploader.rules import CORE_COLUMNS, ItemsFormatError, check_constructs
from harmonica.uploader.runner import RESULT_COLUMNS, decisions_from_review, run_groups, write_results_csv
from harmonica.uploader.tab import UploaderTab

DEFAULT_MODELS_DIR = Path(__file__).parent / 'models'
DEFAULT_INVENTORY = Path(__file__).parent / 'inventory' / 'harmonized_inventory.csv'

REQUIRED_COLUMNS = set(CORE_COLUMNS)

REVIEW_COLUMNS = DUPLICATE_COLUMNS + ['same_item?']


_hca = None


def get_hca(models_dir: str = None, inventory_path: str = None) -> HarmoniCA:
    """Lazily create a single shared HarmoniCA instance for the app's lifetime."""
    global _hca
    if _hca is None:
        _hca = HarmoniCA(
            models_dir=models_dir or str(DEFAULT_MODELS_DIR),
            inventory_path=inventory_path or str(DEFAULT_INVENTORY),
        )
    return _hca


# ---------------------------------------------------------------------------
# Tab 1: Harmonize
# ---------------------------------------------------------------------------

def detect(items_file):
    """Load the uploaded items CSV, check the inventory, and surface any
    possible item_id/coding mismatches for the user to confirm or reject."""
    if items_file is None:
        raise gr.Error("Please upload an items CSV first.")

    items_df = pd.read_csv(items_file)
    missing_cols = REQUIRED_COLUMNS - set(items_df.columns)
    if missing_cols:
        raise gr.Error(f"Items CSV is missing required columns: {sorted(missing_cols)}")

    try:
        check_constructs(items_df['construct'].unique(), CONSTRUCTS)
    except ItemsFormatError as exc:
        raise gr.Error(str(exc))

    report = check_items_against_inventory(items_df, get_hca())
    groups, review_rows = report.groups, report.review_rows
    n_cached, n_new = report.n_cached, report.n_new

    review_df = pd.DataFrame(review_rows, columns=REVIEW_COLUMNS)

    summary = (
        f"{n_cached} item(s) already in the inventory (exact ID match).\n"
        f"{len(review_rows)} possible duplicate(s) found under a different item_id"
        f"{' — review below before running.' if review_rows else '.'}\n"
        f"{n_new} new item(s) will be sent to the model."
    )

    state = {'groups': groups}
    return state, summary, review_df, gr.update(visible=len(review_rows) > 0), gr.update(interactive=True)


def run_harmonization(state, review_df, force_rerun):
    if not state or not state.get('groups'):
        raise gr.Error("Click 'Check inventory' first.")

    out_df = run_groups(get_hca(), state['groups'], decisions_from_review(review_df), force_rerun)

    return out_df[RESULT_COLUMNS], write_results_csv(out_df)


# ---------------------------------------------------------------------------
# Tab 2: Inventory Browser
# ---------------------------------------------------------------------------

def browse_inventory(construct_filter, questionnaire_filter, text_filter):
    inv = pd.read_csv(DEFAULT_INVENTORY)  # reload fresh — the inventory grows as harmonize() runs

    if construct_filter and construct_filter != 'All':
        inv = inv[inv['construct'] == construct_filter]
    if questionnaire_filter:
        inv = inv[inv['questionnaire'].str.contains(questionnaire_filter, case=False, na=False)]
    if text_filter:
        inv = inv[inv['item_text'].str.contains(text_filter, case=False, na=False)]

    return inv, f"{len(inv)} item(s)"


# ---------------------------------------------------------------------------
# Tab 3: Data Harmonizer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def build_app() -> gr.Blocks:
    with gr.Blocks(title="HarmoniCA") as demo:
        gr.Markdown("# HarmoniCA — Harmonizing Clinical Assessments")

        with gr.Tab("Harmonize"):
            gr.Markdown(
                "Upload a CSV with columns `construct, questionnaire, item_id, item_text`."
            )
            items_file = gr.File(label="Items CSV", file_types=[".csv"])
            force_rerun = gr.Checkbox(label="Ignore inventory and always run the model", value=False)
            detect_btn = gr.Button("1. Check inventory")

            summary_box = gr.Textbox(label="Summary", interactive=False)

            with gr.Group(visible=False) as review_group:
                gr.Markdown(
                    "These items have the *same text* as an inventory item, but a "
                    "*different* item_id. Uncheck any that are actually a different item."
                )
                review_df = gr.Dataframe(
                    headers=REVIEW_COLUMNS,
                    datatype=["str", "str", "str", "str", "str", "str", "bool"],
                    interactive=True,
                    label="Possible duplicates",
                )

            run_btn = gr.Button("2. Run harmonization", interactive=False)

            results_df = gr.Dataframe(label="Results", interactive=False)
            download_file = gr.File(label="Download harmonized CSV")

            state = gr.State()

            detect_btn.click(
                fn=detect,
                inputs=[items_file],
                outputs=[state, summary_box, review_df, review_group, run_btn],
            )
            run_btn.click(
                fn=run_harmonization,
                inputs=[state, review_df, force_rerun],
                outputs=[results_df, download_file],
            )

        with gr.Tab("Inventory Browser"):
            with gr.Row():
                construct_dropdown = gr.Dropdown(
                    choices=['All'] + CONSTRUCTS, value='All', label="Construct"
                )
                questionnaire_search = gr.Textbox(label="Questionnaire contains")
                text_search = gr.Textbox(label="Item text contains")
            refresh_btn = gr.Button("Search")
            count_box = gr.Textbox(label="Matches", interactive=False)
            inventory_df = gr.Dataframe(label="Inventory", interactive=False)

            refresh_btn.click(
                fn=browse_inventory,
                inputs=[construct_dropdown, questionnaire_search, text_search],
                outputs=[inventory_df, count_box],
            )
            demo.load(
                fn=browse_inventory,
                inputs=[construct_dropdown, questionnaire_search, text_search],
                outputs=[inventory_df, count_box],
            )

        UploaderTab(get_hca=get_hca).build()

    return demo


def main():
    build_app().launch()


if __name__ == '__main__':
    main()
