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
import time
from html import escape
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

RESULT_REVIEW_COLUMNS = ['selected', *RESULT_COLUMNS, 'review']
RESULT_REVIEW_DATATYPES = ['bool', 'str', 'str', 'str', 'number', 'str', 'number', 'str', 'str']

WORKFLOW_STEPS = ('Upload', 'Inventory check', 'Harmonization', 'Results')
RUN_STAGES = (
    'Validate file and required columns',
    'Compare items with the inventory',
    'Process items with the model',
    'Prepare results for review',
)

APP_CSS = """
#workflow-stepper .hca-stepper {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    padding: 20px 24px;
    border: 1px solid #dde2e8;
    border-radius: 10px;
    background: #ffffff;
    overflow: hidden;
}

#workflow-stepper .hca-step {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
}

#workflow-stepper .hca-step:not(:last-child)::after {
    content: "";
    position: absolute;
    left: 44px;
    right: 10px;
    top: 15px;
    height: 2px;
    background: #edf0f3;
}

#workflow-stepper .hca-step.is-complete:not(:last-child)::after {
    background: #efd4dc;
}

#workflow-stepper .hca-step-circle {
    z-index: 1;
    display: grid;
    place-items: center;
    flex: 0 0 32px;
    width: 32px;
    height: 32px;
    margin-right: 12px;
    border-radius: 999px;
    background: #eef1f4;
    color: #9aa2ad;
    font-size: 13px;
    font-weight: 700;
}

#workflow-stepper .is-current .hca-step-circle,
#workflow-stepper .is-complete .hca-step-circle {
    background: #b64768;
    color: #ffffff;
}

#workflow-stepper .hca-step-copy {
    z-index: 2;
    min-width: 0;
    padding-right: 16px;
    background: #ffffff;
}

#workflow-stepper .hca-step-title {
    color: #272d37;
    font-size: 14px;
    font-weight: 650;
    white-space: nowrap;
}

#workflow-stepper .is-current .hca-step-title { color: #b64768; }
#workflow-stepper .hca-step-status { color: #77808e; font-size: 11px; }

#run-status .hca-run-card {
    padding: 20px;
    border: 1px solid #dde2e8;
    border-radius: 10px;
    background: #ffffff;
}

#run-status .hca-run-header,
#run-status .hca-run-metric {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

#run-status .hca-run-title { color: #272d37; font-size: 16px; font-weight: 700; }
#run-status .hca-run-copy,
#run-status .hca-stage-detail { color: #77808e; font-size: 12px; }
#run-status .hca-run-count { color: #272d37; font-size: 28px; font-weight: 700; }
#run-status .hca-run-percent { color: #b64768; font-size: 22px; font-weight: 700; }

#run-status .hca-run-badge {
    padding: 4px 9px;
    border-radius: 6px;
    background: #f7edf0;
    color: #b64768;
    font-size: 11px;
}

#run-status .hca-progress-track {
    height: 7px;
    margin: 12px 0 16px;
    overflow: hidden;
    border-radius: 999px;
    background: #edf0f3;
}

#run-status .hca-progress-fill { height: 100%; background: #b64768; transition: width 220ms ease; }
#run-status .hca-stage { display: grid; grid-template-columns: 18px 1fr auto; gap: 10px; padding: 10px 0; }
#run-status .hca-stage + .hca-stage { border-top: 1px solid #edf0f3; }
#run-status .hca-stage-dot { color: #a7afb9; font-weight: 700; }
#run-status .is-complete .hca-stage-dot,
#run-status .is-complete .hca-stage-state { color: #2f806d; }
#run-status .is-running .hca-stage-dot,
#run-status .is-running .hca-stage-state { color: #b64768; }
#run-status .hca-stage-title { color: #343b46; font-size: 13px; font-weight: 650; }
#run-status .hca-stage-state { color: #8a929e; font-size: 11px; }

#run-status .hca-run-log {
    margin-top: 14px;
    padding: 14px;
    border-radius: 8px;
    background: #f7f8fa;
}

#run-status .hca-run-log-title { margin-bottom: 8px; color: #343b46; font-size: 13px; font-weight: 700; }
#run-status .hca-log-line { display: grid; grid-template-columns: 44px 1fr; gap: 10px; color: #626b78; font-size: 11px; }
#run-status .hca-log-time { color: #9aa2ad; font-family: ui-monospace, monospace; }

#results-review-table table th:last-child,
#results-review-table table td:last-child {
    color: #b64768;
    font-weight: 650;
}

#results-review-table table th:first-child,
#results-review-table table td:first-child {
    width: 72px;
    text-align: center;
}

#result-review-panel .hca-review-card {
    min-height: 100%;
    padding: 18px;
    border: 1px solid #dde2e8;
    border-radius: 10px;
    background: #ffffff;
}

#result-review-panel .hca-review-eyebrow {
    margin-bottom: 6px;
    color: #b64768;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

#result-review-panel .hca-review-title { color: #272d37; font-size: 17px; font-weight: 700; }
#result-review-panel .hca-review-copy { margin-top: 4px; color: #77808e; font-size: 12px; }
#result-review-panel .hca-review-grid { display: grid; gap: 12px; margin-top: 18px; }
#result-review-panel .hca-review-label { color: #8a929e; font-size: 10px; text-transform: uppercase; }
#result-review-panel .hca-review-value { color: #343b46; font-size: 13px; font-weight: 600; }

#result-review-panel .hca-review-badge {
    display: inline-block;
    margin-top: 16px;
    padding: 5px 9px;
    border-radius: 6px;
    background: #f7edf0;
    color: #b64768;
    font-size: 11px;
    font-weight: 650;
}

#assessment-upload {
    min-height: 164px;
    overflow: hidden;
    border: 1px dashed #e7c6d0 !important;
    border-radius: 10px !important;
    background: #fcf9fa !important;
    box-shadow: none !important;
    transition: border-color 160ms ease, background 160ms ease;
}

#assessment-upload:hover,
#assessment-upload:focus-within {
    border-color: #b64768 !important;
    background: #fffafb !important;
}

#assessment-upload > div {
    min-height: 162px;
    border: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
}

#assessment-upload .wrap,
#assessment-upload .upload-container {
    border: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
}

#assessment-upload button {
    color: #b64768 !important;
    font-weight: 650 !important;
}

#assessment-upload svg {
    color: #b64768 !important;
    stroke: currentColor !important;
}

#assessment-upload [class*="file-preview"] {
    margin: 12px !important;
    width: auto !important;
    min-width: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    border: 0 !important;
    border-radius: 8px !important;
    background: #f3f4f6 !important;
}

#assessment-upload [class*="file-preview"] .wrap {
    min-width: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
}

#assessment-upload table {
    width: 100% !important;
    min-width: 0 !important;
    table-layout: fixed;
}

@media (max-width: 760px) {
    #workflow-stepper .hca-stepper {
        grid-template-columns: 1fr;
        row-gap: 14px;
    }

    #workflow-stepper .hca-step:not(:last-child)::after {
        left: 15px;
        right: auto;
        top: 36px;
        width: 2px;
        height: 14px;
    }

    #workflow-stepper .hca-step-copy {
        padding-right: 0;
    }

    #run-status .hca-run-metric { align-items: flex-end; }
    #run-status .hca-stage { grid-template-columns: 18px 1fr; }
    #run-status .hca-stage-state { grid-column: 2; }

    #result-review-panel .hca-review-card { min-height: auto; }

    #assessment-upload,
    #assessment-upload > div {
        min-height: 132px;
    }
}
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


def render_stepper(current_step: int) -> str:
    """Render the four-step workflow indicator shown in the UX design."""
    current_step = max(1, min(current_step, len(WORKFLOW_STEPS)))
    parts = ['<div class="hca-stepper" aria-label="Harmonization progress">']

    for index, label in enumerate(WORKFLOW_STEPS, start=1):
        if index < current_step:
            css_class, marker, status = 'is-complete', '&#10003;', 'Complete'
        elif index == current_step:
            css_class, marker, status = 'is-current', str(index), 'Current step'
        else:
            css_class, marker, status = 'is-upcoming', str(index), 'Upcoming'

        parts.append(
            f'<div class="hca-step {css_class}">'
            f'<div class="hca-step-circle">{marker}</div>'
            f'<div class="hca-step-copy">'
            f'<div class="hca-step-title">{label}</div>'
            f'<div class="hca-step-status">{status}</div>'
            f'</div></div>'
        )

    parts.append('</div>')
    return ''.join(parts)


def show_upload_step():
    return render_stepper(1)


def show_inventory_step():
    return render_stepper(2)


def show_harmonization_step():
    return render_stepper(3)


def show_results_step():
    return render_stepper(4)


def render_run_status(percent, processed, total, active_stage, activities):
    """Render model progress, stage states, and a timestamped activity log."""
    percent = max(0, min(int(percent), 100))
    is_complete = active_stage > len(RUN_STAGES)
    badge = 'Complete' if is_complete else 'In progress'
    remaining = max(total - processed, 0)

    stages = []
    for index, title in enumerate(RUN_STAGES, start=1):
        if index < active_stage:
            css_class, marker, state = 'is-complete', '&#10003;', 'Complete'
        elif index == active_stage:
            css_class, marker, state = 'is-running', '&#9684;', 'Running'
        else:
            css_class, marker, state = 'is-waiting', '&#9675;', 'Waiting'

        if index <= 2:
            detail = 'Completed before model processing'
        elif index == 3:
            detail = f'{processed} of {total} items processed'
        else:
            detail = 'Combine inventory records and model suggestions'

        stages.append(
            f'<div class="hca-stage {css_class}">'
            f'<div class="hca-stage-dot">{marker}</div>'
            f'<div><div class="hca-stage-title">{escape(title)}</div>'
            f'<div class="hca-stage-detail">{escape(detail)}</div></div>'
            f'<div class="hca-stage-state">{state}</div></div>'
        )

    log_lines = []
    for elapsed_seconds, message in activities:
        minutes, seconds = divmod(max(int(elapsed_seconds), 0), 60)
        log_lines.append(
            f'<div class="hca-log-line"><span class="hca-log-time">'
            f'{minutes:02d}:{seconds:02d}</span><span>{escape(str(message))}</span></div>'
        )

    return (
        '<div class="hca-run-card">'
        f'<div class="hca-run-header"><div><div class="hca-run-title">Model processing</div>'
        f'<div class="hca-run-copy">{processed} processed &middot; {remaining} remaining</div></div>'
        f'<span class="hca-run-badge">{badge}</span></div>'
        f'<div class="hca-run-metric"><span class="hca-run-count">{processed} '
        f'<span class="hca-run-copy">/ {total}</span></span>'
        f'<span class="hca-run-percent">{percent}%</span></div>'
        f'<div class="hca-progress-track"><div class="hca-progress-fill" style="width:{percent}%"></div></div>'
        f'{"".join(stages)}'
        f'<div class="hca-run-log"><div class="hca-run-log-title">Run activity</div>'
        f'{"".join(log_lines)}</div></div>'
    )


def format_results_for_review(results):
    """Add UI-only selection and review action columns to result rows."""
    frame = pd.DataFrame(results).copy()
    for column in RESULT_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame[RESULT_COLUMNS]
    frame.insert(0, 'selected', False)
    frame['review'] = frame['source'].map(
        lambda source: 'Model suggestion' if source == 'model' else 'Inventory record'
    )
    return frame[RESULT_REVIEW_COLUMNS]


def render_result_detail_placeholder():
    return (
        '<div class="hca-review-card">'
        '<div class="hca-review-eyebrow">Result review</div>'
        '<div class="hca-review-title">Select a result row</div>'
        '<div class="hca-review-copy">Choose any row to inspect its harmonization details.</div>'
        '</div>'
    )


def render_result_detail(results, event: gr.SelectData):
    """Render the selected result row in a compact review panel."""
    frame = pd.DataFrame(results)
    index = getattr(event, 'index', event)
    row_index = index[0] if isinstance(index, (list, tuple)) else index
    if row_index is None or frame.empty or not 0 <= int(row_index) < len(frame):
        return render_result_detail_placeholder()

    row = frame.iloc[int(row_index)]

    def display(column, fallback='—'):
        value = row.get(column, fallback)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            value = fallback
        return escape(str(value))

    source = str(row.get('source', ''))
    source_label = 'Model suggestion' if source == 'model' else 'Inventory record'
    confidence = row.get('confidence')
    if isinstance(confidence, (int, float)) and not pd.isna(confidence) and 0 <= confidence <= 1:
        confidence_text = f'{confidence:.0%}'
    else:
        confidence_text = display('confidence')

    return (
        '<div class="hca-review-card">'
        f'<div class="hca-review-eyebrow">{escape(source_label)}</div>'
        f'<div class="hca-review-title">{display("item_id")}</div>'
        f'<div class="hca-review-copy">{display("questionnaire")} &middot; {display("construct")}</div>'
        '<div class="hca-review-grid">'
        f'<div><div class="hca-review-label">Construct mapping</div>'
        f'<div class="hca-review-value">{display("dimension_label")}</div></div>'
        f'<div><div class="hca-review-label">Dimension</div>'
        f'<div class="hca-review-value">{display("dimension")}</div></div>'
        f'<div><div class="hca-review-label">Confidence</div>'
        f'<div class="hca-review-value">{escape(confidence_text)}</div></div>'
        '</div>'
        f'<span class="hca-review-badge">{escape(source_label)}</span>'
        '</div>'
    )


def render_checked_result_detail(results):
    """Render the last checked result row from the editable checkbox column."""
    frame = pd.DataFrame(results)
    if frame.empty or 'selected' not in frame.columns:
        return render_result_detail_placeholder()

    checked_rows = [
        index for index, value in enumerate(frame['selected'])
        if value is True or str(value).strip().lower() == 'true'
    ]
    if not checked_rows:
        return render_result_detail_placeholder()
    return render_result_detail(frame, checked_rows[-1])


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


def stream_harmonization(state, review_df, force_rerun):
    """Yield live run status updates, then the completed table and CSV path."""
    if not state or not state.get('groups'):
        raise gr.Error("Click 'Check inventory' first.")

    hca = get_hca()
    started_at = time.monotonic()
    total_items = sum(len(group['items']) for group in state['groups'])
    processed_items = 0
    activities = [(0, f'Run started with {total_items} item(s).')]

    decisions = decisions_from_review(review_df)

    yield (
        gr.update(
            value=render_run_status(0, 0, total_items, 3, activities),
            visible=True,
        ),
        gr.update(),
        gr.update(),
    )

    all_results = []
    for g in state['groups']:
        questionnaire, construct, items = g['questionnaire'], g['construct'], g['items']
        all_results.append(run_groups(hca, [g], decisions, force_rerun))

        processed_items += len(items)
        activities.append((
            time.monotonic() - started_at,
            f'Processed {questionnaire} ({construct}): {len(items)} item(s).',
        ))
        percent = min(round((processed_items / max(total_items, 1)) * 85), 85)
        yield (
            gr.update(
                value=render_run_status(
                    percent, processed_items, total_items, 3, activities
                ),
                visible=True,
            ),
            gr.update(),
            gr.update(),
        )

    activities.append((time.monotonic() - started_at, 'Preparing results for review.'))
    yield (
        gr.update(
            value=render_run_status(
                92, processed_items, total_items, 4, activities
            ),
            visible=True,
        ),
        gr.update(),
        gr.update(),
    )

    out_df = pd.concat(all_results, ignore_index=True)

    out_path = write_results_csv(out_df)

    activities.append((time.monotonic() - started_at, 'Results are ready for review.'))
    yield (
        gr.update(
            value=render_run_status(
                100, total_items, total_items, len(RUN_STAGES) + 1, activities
            ),
            visible=True,
        ),
        format_results_for_review(out_df),
        out_path,
    )


def run_harmonization(state, review_df, force_rerun):
    """Synchronous adapter retained for direct callers and tests."""
    final_update = None
    for final_update in stream_harmonization(state, review_df, force_rerun):
        pass
    return final_update[1][RESULT_COLUMNS], final_update[2]


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
    with gr.Blocks(title="HarmoniCA", css=APP_CSS) as demo:
        gr.Markdown("# HarmoniCA — Harmonizing Clinical Assessments")

        with gr.Tab("Harmonize"):
            stepper = gr.HTML(render_stepper(1), elem_id="workflow-stepper")
            gr.Markdown(
                "Upload a CSV with columns `construct, questionnaire, item_id, item_text`."
            )
            items_file = gr.File(
                label="Items CSV",
                file_types=[".csv"],
                elem_id="assessment-upload",
            )
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

            run_status = gr.HTML(value="", visible=False, elem_id="run-status")
            gr.Markdown("Select a row checkbox to review its harmonization details.")
            results_df = gr.Dataframe(
                headers=RESULT_REVIEW_COLUMNS,
                datatype=RESULT_REVIEW_DATATYPES,
                interactive=True,
                static_columns=list(range(1, len(RESULT_REVIEW_COLUMNS))),
                label="Results",
                max_height=520,
                wrap=False,
                column_widths=[72, 130, 130, 170, 100, 190, 110, 100, 180],
                show_search="search",
                pinned_columns=1,
                elem_id="results-review-table",
            )
            result_detail = gr.HTML(
                render_result_detail_placeholder(),
                elem_id="result-review-panel",
            )
            download_file = gr.File(label="Download harmonized CSV")

            state = gr.State()

            items_file.change(
                fn=show_upload_step,
                outputs=[stepper],
            )
            detect_event = detect_btn.click(
                fn=detect,
                inputs=[items_file],
                outputs=[state, summary_box, review_df, review_group, run_btn],
            )
            detect_event.then(
                fn=show_inventory_step,
                outputs=[stepper],
            )
            run_start = run_btn.click(
                fn=show_harmonization_step,
                outputs=[stepper],
            )
            run_complete = run_start.then(
                fn=stream_harmonization,
                inputs=[state, review_df, force_rerun],
                outputs=[run_status, results_df, download_file],
            )
            run_complete.then(
                fn=show_results_step,
                outputs=[stepper],
            )
            results_df.change(
                fn=render_checked_result_detail,
                inputs=[results_df],
                outputs=[result_detail],
                queue=False,
                scroll_to_output=True,
                show_progress="hidden",
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
