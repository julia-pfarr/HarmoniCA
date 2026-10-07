"""The Data Harmonizer Gradio tab. All validation lives in ``rules`` / ``inventory_check`` /
``runner`` as this module only turns the results into UI behaviour."""
import inspect
import tempfile
from types import SimpleNamespace
from pathlib import Path
from typing import Callable, List, Optional

import gradio as gr
import pandas as pd

from harmonica.harmonica.config import CONSTRUCTS

from .inventory_check import DUPLICATE_TABLE_COLUMNS, InventoryReport, check_items_against_inventory
from .rules import CORE_COLUMNS, UPLOAD_COLUMNS, EmptyUploadError, ItemsFormatError, validate_items
from .runner import RESULT_COLUMNS, decisions_from_review, run_groups, write_results_csv

FORMAT_HINT = (
    "Upload format did not match the expected format. {detail} "
    "Please click \"Download sample CSV\" to check the required format."
)


def _err(message: str) -> gr.Error:
    """A validation error for the user, with no traceback in the server log."""
    try:
        return gr.Error(message, print_exception=False)
    except TypeError:  # older Gradio without print_exception
        return gr.Error(message)


def make_sample_csv() -> str:
    """Write a header-only template CSV and return its path."""
    path = Path(tempfile.mkdtemp()) / 'sample_items.csv'
    pd.DataFrame(columns=UPLOAD_COLUMNS).to_csv(path, index=False)
    return str(path)


def _empty_items_table() -> pd.DataFrame:
    return pd.DataFrame(columns=UPLOAD_COLUMNS)


def _table_to_df(table) -> pd.DataFrame:
    """The items table from the screen as a DataFrame (empty when there is none yet)."""
    return _empty_items_table() if table is None else pd.DataFrame(table, columns=UPLOAD_COLUMNS)


def _delete_btn_state(n_rows: int):
    """The delete button is only usable while the list has rows."""
    return gr.update(interactive=n_rows > 0)


# Column widths in pixels, in column order. Text wraps inside each cell, and when the columns
# add up to more than the page is wide the table scrolls sideways instead of squashing them.
DUPLICATE_WIDTHS = [130, 140, 120, 240, 250, 240, 170]  # same_item? first (scrolls on narrow screens)
ITEMS_WIDTHS = [130, 160, 130, 400, 280, 120]            # the six upload columns
CACHED_WIDTHS = [150, 140, 140, 380, 110, 190, 120]      # questionnaire .. confidence
NEW_WIDTHS = [140, 130, 130, 380, 280, 150]               # questionnaire .. scoring
RESULT_WIDTHS = [190, 150, 200, 120, 320, 120, 130]      # RESULT_COLUMNS


def _table_style(widths=None) -> dict:
    """Wrap long text inside cells. With fixed pixel widths the table also scrolls sideways when
    there are more columns than fit. (column_widths is missing in older 4.x releases, where the
    columns are simply sized automatically.)"""
    style = {"wrap": True}
    if widths and "column_widths" in inspect.signature(gr.Dataframe.__init__).parameters:
        style["column_widths"] = widths
    return style



class UploaderTab:
    """Builds the tab and holds its handlers.

    ``get_hca`` returns the shared HarmoniCA instance (the same one the Harmonize tab
    uses), so both tabs look at the same inventory.

    NOTE: when a handler raises gr.Error, Gradio paints an "Error" overlay over every
    component the handler writes to. So each button first runs a validate-only step
    (no visible outputs). The step that updates the screen runs only on success.
    """

    def __init__(self, get_hca: Callable, constructs: Optional[List[str]] = None):
        self.get_hca = get_hca
        self.constructs = constructs or CONSTRUCTS

    # ---- shared helpers -------------------------------------------------

    def _validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            return validate_items(df, self.constructs)
        except ItemsFormatError as exc:
            raise _err(str(exc))

    def _report(self, df: pd.DataFrame) -> Optional[InventoryReport]:
        try:
            return check_items_against_inventory(df, self.get_hca())
        except Exception:  # never block uploading because the report failed
            return None

    @staticmethod
    def _summary_text(report: Optional[InventoryReport]) -> str:
        return report.summary() if report else "(Inventory check unavailable.)"

    def _summary(self, df: pd.DataFrame) -> str:
        return self._summary_text(self._report(df))

    # ---- Option 1: enter items manually ---------------------------------

    def _prepare_item(self, construct, questionnaire, item_id, item_text, answer_options, scoring, table):
        values = [construct, questionnaire, item_id, item_text, answer_options, scoring]
        if not any((v or '').strip() for v in values):
            raise _err("Please fill in the item details before clicking Add item.")
        try:
            clean = validate_items(pd.DataFrame([values], columns=UPLOAD_COLUMNS), self.constructs)
        except ItemsFormatError as exc:
            raise _err(str(exc).replace("Row 1: ", ""))

        staged = _table_to_df(table)
        if clean.loc[0, 'item_id'] in set(staged['item_id']):
            raise _err(f"item_id {clean.loc[0, 'item_id']} is already in your list.")
        return clean, staged

    def _items_summary(self, df: pd.DataFrame) -> str:
        if df is None or len(df) == 0:
            return ""
        return f"**{len(df)} item(s) in your list:** {self._summary(df)}"

    def check_item(self, *args):
        self._prepare_item(*args)

    def add_item(self, *args):
        clean, staged = self._prepare_item(*args)
        out = pd.concat([staged, clean], ignore_index=True)
        # Keep construct / questionnaire / answer_options / scoring (usually shared by
        # consecutive items). Clear item_id and item_text for the next entry.
        return (out, gr.update(value=""), gr.update(value=""), _delete_btn_state(len(out)),
                None, "No row selected.", self._items_summary(out))

    @staticmethod
    def select_row(evt: gr.SelectData):
        row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        return row, f"Selected row {row + 1}."

    @staticmethod
    def check_delete(table, selected_row):
        df = _table_to_df(table)
        if selected_row is None:
            raise _err("Click a row in the table first, then delete it.")
        if selected_row >= len(df):
            raise _err("That row no longer exists. Click a row and try again.")

    def delete_selected_row(self, table, selected_row):
        df = _table_to_df(table)
        df = df.drop(index=selected_row).reset_index(drop=True)
        return df, None, "No row selected.", _delete_btn_state(len(df)), self._items_summary(df)

    def stage_items(self, table):
        """Validate the manual list and hand it to the same preview step the CSV upload uses."""
        return self._validate(_table_to_df(table))

    # ---- Option 2: upload a CSV -----------------------------------------

    def process_upload(self, upload_file):
        """Validate the file. Nothing is stored anywhere."""
        if upload_file is None:
            raise _err("Please upload a CSV file first.")
        try:
            df = pd.read_csv(upload_file, dtype=str)
        except Exception as exc:
            raise _err(FORMAT_HINT.format(detail=f"The file could not be read as a CSV ({exc})."))
        if set(UPLOAD_COLUMNS) <= set(df.columns) and df.dropna(how='all').empty:
            raise _err(
                "At least one row is required. The file has no data rows. "
                "Fill in the sample CSV with your items, then upload it again."
            )
        try:
            clean = validate_items(df, self.constructs)
        except EmptyUploadError as exc:
            raise _err(str(exc))
        except ItemsFormatError as exc:
            raise _err(FORMAT_HINT.format(detail=str(exc)))
        return clean

    def show_preview(self, pending):
        """Show the rows, the inventory report, and ask the user to confirm."""
        report = self._report(pending)
        msg = f"**{len(pending)} row(s)** found: {self._summary_text(report)}\n\n"
        if report is not None:
            msg += (
                f"**Run harmonization** runs the model **only for the {report.n_new} new item(s)** and "
                f"adds them to the inventory. The {report.n_cached} item(s) already in the inventory are "
                f"reused{', and possible duplicates are reused unless you uncheck them below' if report.n_duplicates else ''}. "
                f"Nothing else is saved.\n\n"
            )
        msg += "Do you want to run harmonization?"

        def show(df):  # a table, hidden when empty
            return gr.update(value=df, visible=len(df) > 0)

        empty = pd.DataFrame()
        if report is None:
            return pending, msg, gr.update(visible=True), show(empty), show(empty), show(empty)
        return (pending, msg, gr.update(visible=True),
                show(report.cached_table()), show(report.duplicates_table()), show(report.new_table()))

    def check_pending(self, pending):
        """Validate-only step before Run harmonization (see the NOTE in the class docstring)."""
        if pending is None or len(pending) == 0:
            raise _err("Nothing to harmonize. Please add items or choose a CSV file first.")

    def harmonize_items(self, pending, review_df, progress=gr.Progress()):
        """Run harmonization (the model only for items not in the inventory) and show the results."""
        progress(0, desc="Checking the inventory")
        df = pd.DataFrame(pending, columns=UPLOAD_COLUMNS)
        hca = self.get_hca()
        core = df[CORE_COLUMNS]
        report = check_items_against_inventory(core, hca)
        rows_before = len(hca.inventory)

        def on_group(i, total, group):
            progress(0.1 + 0.85 * i / total,
                     desc=f"Harmonizing {group['questionnaire']} ({group['construct']}): "
                          f"{i + 1} of {total} group(s)")

        out_df = run_groups(hca, report.groups, decisions_from_review(review_df), on_group=on_group)
        progress(1.0, desc="Done")
        n_model = len(hca.inventory) - rows_before  # items the model ran for (added to the inventory)

        summary = (
            f"**Harmonization finished.** {len(out_df)} item(s) harmonized. "
            f"The model ran only for {n_model} new item(s) and added them to the inventory. "
            f"the other {len(out_df) - n_model} were reused from it."
        )
        gr.Info(f"Model ran for {n_model} new item(s).")
        return (None, gr.update(visible=False), None,
                gr.update(visible=True), summary, out_df[RESULT_COLUMNS], write_results_csv(out_df),
                gr.update(visible=False))

    @staticmethod
    def show_running():
        """Shown the moment 'Run harmonization' is accepted: a note, an empty slot for the
        progress bar to appear in, and the buttons locked so the run cannot be started twice."""
        note = ("**Running harmonization.** The model runs only for the new items, so this can "
                "take a little while (the first run also loads the model). Please keep this page open.")
        off = gr.update(interactive=False)
        return (gr.update(value=note, visible=True),
                gr.update(value="<br><br><br><br>", visible=True),  # room for the progress bar
                off, off)  # Run harmonization, Cancel

    @staticmethod
    def reset_run_ui():
        """Runs after the harmonize step, whether it worked or failed: unlock the buttons."""
        on = gr.update(interactive=True)
        return gr.update(visible=False), gr.update(visible=False), on, on  # note, bar, 2 buttons

    @staticmethod
    def cancel_upload():
        gr.Info("Cancelled. Nothing was changed.")
        return None, gr.update(visible=False), None

    def _review_section(self, clear_on_done=None) -> SimpleNamespace:
        """The preview, run and results block that sits under the button of one option.

        Each option (manual entry, CSV upload) gets its own copy, so the preview, the progress
        bar and the results appear right under the button that was clicked.
        ``clear_on_done`` is a component to empty when the run finishes or is cancelled
        (the CSV option passes its file box).
        """
        clear = clear_on_done if clear_on_done is not None else gr.State(None)
        pending = gr.State(None)

        with gr.Group(visible=False) as confirm_group:
            confirm_msg = gr.Markdown()
            preview = gr.Dataframe(
                label="Preview of your items", interactive=False, max_height=300,
                **_table_style(ITEMS_WIDTHS),
            )
            cached_df = gr.Dataframe(
                label="Already in the inventory (exact item_id match): the existing "
                      "assignment is reused, the model does not run",
                interactive=False, visible=False, max_height=300,
                **_table_style(CACHED_WIDTHS),
            )
            dupes_df = gr.Dataframe(
                label="Possible duplicates (same text as an inventory item, different item_id). "
                      "Uncheck same_item? for any that are actually a different item",
                headers=DUPLICATE_TABLE_COLUMNS,
                datatype=["bool"] + ["str"] * (len(DUPLICATE_TABLE_COLUMNS) - 1),
                interactive=True, visible=False, max_height=300,
                **_table_style(DUPLICATE_WIDTHS),
            )
            new_df = gr.Dataframe(
                label="New items: Run harmonization runs the model only for these "
                      "(plus any possible duplicate you mark as a different item)",
                interactive=False, visible=False, max_height=300,
                **_table_style(NEW_WIDTHS),
            )
            with gr.Row():
                harmonize_btn = gr.Button("Run harmonization")
                cancel_btn = gr.Button("Cancel")
            running_note = gr.Markdown(visible=False)
            run_status = gr.Markdown(visible=False)  # the progress bar is drawn here

        with gr.Group(visible=False) as results_group:
            results_msg = gr.Markdown()
            results_df = gr.Dataframe(label="Harmonization results", interactive=False,
                                      max_height=300, **_table_style(RESULT_WIDTHS))
            download_file = gr.File(label="Download harmonized CSV")

        run_buttons = [harmonize_btn, cancel_btn]
        harmonize_btn.click(fn=self.check_pending, inputs=[pending]).success(
            fn=self.show_running, outputs=[running_note, run_status] + run_buttons,
        ).success(
            fn=self.harmonize_items,
            inputs=[pending, dupes_df],
            outputs=[pending, confirm_group, clear,
                     results_group, results_msg, results_df, download_file, run_status],
        ).then(
            fn=self.reset_run_ui, outputs=[running_note, run_status] + run_buttons,
        )
        cancel_btn.click(
            fn=self.cancel_upload, outputs=[pending, confirm_group, clear],
        )
        return SimpleNamespace(
            pending=pending, confirm_group=confirm_group, results_group=results_group,
            preview_outputs=[preview, confirm_msg, confirm_group, cached_df, dupes_df, new_df],
        )

    @staticmethod
    def _hide_sections(*sections):
        """When a new check starts, hide the old preview and results of every section."""
        return lambda: tuple(gr.update(visible=False) for _ in range(2 * len(sections)))

    def _wire_preview(self, button, stage_fn, stage_inputs, section, all_sections):
        """Button click: hide old previews, validate and stage the items, then show the preview of this section."""
        groups = [g for sec in all_sections for g in (sec.confirm_group, sec.results_group)]
        button.click(
            fn=self._hide_sections(*all_sections), outputs=groups,
        ).then(
            fn=stage_fn, inputs=stage_inputs, outputs=[section.pending],
        ).success(
            fn=self.show_preview, inputs=[section.pending], outputs=section.preview_outputs,
        )

    # ---- layout ----------------------------------------------------------

    def build(self):
        with gr.Tab("Data Harmonizer"):
            gr.Markdown(
                "Columns: `construct, questionnaire, item_id, item_text, answer_options, "
                "scoring`. All six are required for every item."
            )

            gr.Markdown("### Option 1: Enter items manually")
            with gr.Row():
                construct_in = gr.Textbox(label="construct", placeholder="e.g. depression")
                questionnaire_in = gr.Textbox(label="questionnaire", placeholder="e.g. CES-D")
                item_id_in = gr.Textbox(label="item_id", placeholder="e.g. CES-D_01")
            item_text_in = gr.Textbox(label="item_text", lines=2)
            with gr.Row():
                options_in = gr.Textbox(label="answer_options", placeholder='e.g. ["Never", "Always"]')
                scoring_in = gr.Textbox(label="scoring", placeholder="e.g. [0, 1]")
            add_item_btn = gr.Button("Add item")

            items_df = gr.Dataframe(
                value=_empty_items_table(),
                headers=UPLOAD_COLUMNS,
                datatype=["str"] * len(UPLOAD_COLUMNS),
                interactive=False,
                max_height=300,
                **_table_style(ITEMS_WIDTHS),
                label="Items to harmonize",
            )
            items_summary = gr.Markdown()
            selected_info = gr.Markdown("No row selected.")
            with gr.Row():
                delete_row_btn = gr.Button("Delete selected row", interactive=False)
                review_btn = gr.Button("Review and harmonize")

            manual_review = self._review_section()  # preview / run / results for Option 1

            gr.Markdown("### Option 2: Upload a CSV file")
            gr.DownloadButton("Download sample CSV", value=make_sample_csv())
            upload_file = gr.File(label="Data file", file_types=[".csv"])
            upload_btn = gr.Button("Upload")
            csv_review = self._review_section(clear_on_done=upload_file)  # same, for Option 2

            selected_row = gr.State(None)
            both = [manual_review, csv_review]

            row_inputs = [construct_in, questionnaire_in, item_id_in, item_text_in,
                          options_in, scoring_in, items_df]
            items_df.select(fn=self.select_row, outputs=[selected_row, selected_info])
            add_item_btn.click(fn=self.check_item, inputs=row_inputs).success(
                fn=self.add_item,
                inputs=row_inputs,
                outputs=[items_df, item_id_in, item_text_in, delete_row_btn,
                         selected_row, selected_info, items_summary],
            )
            delete_row_btn.click(
                fn=self.check_delete, inputs=[items_df, selected_row],
            ).success(
                fn=self.delete_selected_row,
                inputs=[items_df, selected_row],
                outputs=[items_df, selected_row, selected_info, delete_row_btn, items_summary],
            )
            self._wire_preview(review_btn, self.stage_items, [items_df], manual_review, both)
            self._wire_preview(upload_btn, self.process_upload, [upload_file], csv_review, both)
