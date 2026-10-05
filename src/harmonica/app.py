"""
HarmoniCA — Gradio web UI.

Run locally with:
    harmonica-ui
or:
    python -m harmonica.app

Two tabs:
  - Harmonize: upload an items CSV, review any possible item_id/coding
    mismatches against the inventory, run harmonization, download results.
  - Inventory Browser: search/filter the existing harmonized_inventory.csv.
"""
import tempfile
from pathlib import Path

import gradio as gr
import pandas as pd

from harmonica.harmonica import HarmoniCA
from harmonica.harmonica.config import CONSTRUCTS

DEFAULT_MODELS_DIR = Path(__file__).parent / 'models'
DEFAULT_INVENTORY = Path(__file__).parent / 'inventory' / 'harmonized_inventory.csv'

REQUIRED_COLUMNS = {'construct', 'questionnaire', 'item_id', 'item_text'}

REVIEW_COLUMNS = [
    'questionnaire', 'your_item_id', 'your_item_text',
    'matched_inventory_item_id', 'matched_item_text', 'dimension_label', 'same_item?',
]

RESULT_COLUMNS = ['questionnaire', 'construct', 'item_id', 'dimension', 'dimension_label', 'confidence', 'source']

# ---------------------------------------------------------------------------
# Theme (colours and font from the Figma template)
# ---------------------------------------------------------------------------
# In Gradio 6 the theme is passed to .launch(), not gr.Blocks(), so it's defined
# once here and used by both main() below and the root-level app.py.

HARMONICA_RED = gr.themes.Color(
    name="harmonica_red",
    c50="#FBF3F5",
    c100="#F9ECEF",  # light pink panels
    c200="#F0CBD6",
    c300="#E3A3B7",
    c400="#CF7090",
    c500="#B84B6F",
    c600="#A33B5C",  # main brand red
    c700="#872F4C",
    c800="#6E2840",
    c900="#5C2437",
    c950="#36121E",
)

THEME = gr.themes.Default(
    primary_hue=HARMONICA_RED,
    neutral_hue=gr.themes.colors.gray,
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    radius_size=gr.themes.sizes.radius_md,
).set(
    body_background_fill="#F6F7F9",
    body_text_color="#1F2430",
    block_background_fill="white",
    block_border_color="#E5E7EB",
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
    button_primary_text_color="white",
    checkbox_background_color_selected="*primary_600",
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

DOCS_URL = "https://github.com/julia-pfarr/HarmoniCA#readme"
# Link to the research dashboard; the header link stays hidden until this is set.
RESEARCH_WORKSPACE_URL = None

_LOGO_SVG = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linejoin="round"><path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z"/>'
    '<path d="m3 12 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/></svg>'
)
_FLASK_SVG = (
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M9 3h6M10 3v6L4.5 19A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/>'
    '<path d="M7.5 15h9"/></svg>'
)


def header_html() -> str:
    workspace_link = (
        f'<a href="{RESEARCH_WORKSPACE_URL}" target="_blank">{_FLASK_SVG} Research workspace</a>'
        if RESEARCH_WORKSPACE_URL else ''
    )
    return f"""
    <div class="hca-header">
      <div class="hca-brand">
        <div class="hca-logo">{_LOGO_SVG}</div>
        <div>
          <div class="hca-title">HarmoniCA</div>
          <div class="hca-subtitle">Harmonizing Clinical Assessments</div>
        </div>
      </div>
      <nav class="hca-links">
        <a href="{DOCS_URL}" target="_blank">Documentation &#8599;</a>
        {workspace_link}
      </nav>
    </div>
    """


# Like the theme, custom CSS is passed to .launch() in Gradio 6.
CSS = """
.hca-header { display: flex; align-items: center; justify-content: space-between;
              gap: 16px; flex-wrap: wrap; padding: 8px 0 12px; }
.hca-brand { display: flex; align-items: center; gap: 12px; }
.hca-logo { width: 38px; height: 38px; border-radius: 8px; display: grid; place-items: center;
            background: #F9ECEF; color: #A33B5C; }
.hca-title { font-size: 24px; line-height: 1.1; color: #1F2430; }
.hca-subtitle { font-size: 12px; color: #6B7280; }
.hca-links { display: flex; gap: 28px; font-size: 14px; }
.hca-links a { color: #4B5563; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
.hca-links a:hover { color: #A33B5C; }

/* Main tabs styled as the header navigation */
#hca-tabs > .tab-wrapper { border-bottom: 1px solid #E5E7EB; }
#hca-tabs [role="tab"] { font-size: 15px; color: #4B5563; border: none; background: none;
                         border-bottom: 2px solid transparent; border-radius: 0; padding: 10px 4px;
                         margin-right: 24px; }
#hca-tabs [role="tab"][aria-selected="true"] { color: #A33B5C; border-bottom-color: #A33B5C; }
"""

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

    unknown_constructs = set(items_df['construct'].unique()) - set(CONSTRUCTS)
    if unknown_constructs:
        raise gr.Error(f"Unknown construct(s) {sorted(unknown_constructs)}. Supported: {CONSTRUCTS}")

    hca = get_hca()
    groups = []
    review_rows = []
    n_cached, n_new = 0, 0

    for (construct, questionnaire), group in items_df.groupby(['construct', 'questionnaire']):
        items = group[['item_id', 'item_text']].to_dict('records')
        groups.append({'questionnaire': questionnaire, 'construct': construct, 'items': items})

        cached, missing = hca._check_inventory(questionnaire, construct, items)
        n_cached += len(cached)

        candidates = hca._find_id_mismatch_candidates(questionnaire, construct, missing)
        candidate_ids = {it['item_id'] for it, _ in candidates}
        n_new += len([it for it in missing if it['item_id'] not in candidate_ids])

        for it, inv_row in candidates:
            review_rows.append({
                'questionnaire': questionnaire,
                'your_item_id': it['item_id'],
                'your_item_text': it['item_text'],
                'matched_inventory_item_id': inv_row['item_id'],
                'matched_item_text': inv_row['item_text'],
                'dimension_label': inv_row['dimension_label'],
                'same_item?': True,
            })

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

    hca = get_hca()

    decisions = {}
    if review_df is not None and len(review_df) > 0:
        for _, row in review_df.iterrows():
            decisions[(row['questionnaire'], row['your_item_id'])] = bool(row['same_item?'])

    all_results = []
    for g in state['groups']:
        questionnaire, construct, items = g['questionnaire'], g['construct'], g['items']

        def confirm_match(user_item, inv_row, _q=questionnaire):
            return decisions.get((_q, user_item['item_id']), True)

        result = hca.harmonize(
            questionnaire=questionnaire, construct=construct, items=items,
            force_rerun=force_rerun, confirm_match=confirm_match,
        )
        group_df = pd.DataFrame(result['assignments'])
        group_df.insert(0, 'questionnaire', questionnaire)
        group_df.insert(1, 'construct', construct)
        group_df['source'] = result['source']
        all_results.append(group_df)

    out_df = pd.concat(all_results, ignore_index=True)

    out_path = Path(tempfile.mkdtemp()) / 'harmonized_results.csv'
    out_df.to_csv(out_path, index=False)

    return out_df[RESULT_COLUMNS], str(out_path)


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
# App
# ---------------------------------------------------------------------------

def build_app() -> gr.Blocks:
    with gr.Blocks(title="HarmoniCA") as demo:
        gr.HTML(header_html())

        with gr.Tabs(elem_id="hca-tabs"):
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

    return demo


def main():
    build_app().launch(theme=THEME, css=CSS)


if __name__ == '__main__':
    main()
