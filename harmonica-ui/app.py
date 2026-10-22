import base64
import hashlib
import io
import json
import os
import shutil
import importlib.util
import sys
import html
from visuals import flow_figure, confidence_figure
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
from backend import COLUMNS, ITEM_COLUMNS, SCORING_COLUMNS, SEPARATORS, detect_separator, inventory_check, load_response_options, parse_items, run_harmonica
from score_kit import build_kit_zip, responses_template, unscored_questionnaires

CATALOG = json.loads(Path(__file__).with_name('assets').joinpath('model_catalog.json').read_text())
if os.environ.get('HARMONICA_SOURCE_DIR'):
    sys.path.insert(0, os.environ['HARMONICA_SOURCE_DIR'])

ASSETS = Path(__file__).with_name('assets')
st.set_page_config(page_title='HarmoniCA', page_icon=str(ASSETS / 'favicon.png'), layout='wide')


@st.cache_resource
def logo_uris():
    """The three parts of the logo as data URIs, since markdown cannot load local files."""
    return {name: 'data:image/png;base64,' + base64.b64encode((ASSETS / f'logo_{name}.png').read_bytes()).decode()
            for name in ('mark', 'wordmark', 'tagline')}


# Colours come from the HarmoniCA logo (petrol wordmark, teal-to-green "CA", the pill spectrum); change them here only.
st.markdown('''<style>
:root {
  --primary:#0F4C6B; --primary-strong:#0B3A53; --primary-soft:#E6F0F5; --primary-line:#B9D3DF; --primary-faint:#F4F9FB;
  --ink:#16303D; --text-2:#3F5967; --muted:#567080; --faint:#6F8794; --border:#DCE6EB; --surface-2:#EEF3F6; --page:#FFFFFF;
  --teal:#146B66; --teal-soft:#E4F1EF; --orange:#E8834E; --amber:#D48C12; --amber-soft:var(--amber-soft); --amber-text:var(--amber-text); --terracotta:#C45A24;
}
.hca-header {display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:0 0 14px;}
.hca-brand {display:flex;flex-direction:column;align-items:center;gap:8px;}
.hca-brand-row {display:flex;align-items:center;gap:28px;}
.hca-mark {height:128px;width:auto;display:block;}
.hca-word {height:62px;width:auto;display:block;}
.hca-tagline {height:26px;width:auto;display:block;}
@media (max-width:760px) {.hca-brand-row {gap:16px;} .hca-mark {height:80px;} .hca-word {height:40px;} .hca-tagline {height:17px;}}
[data-testid="stMainBlockContainer"] {padding-top:1.25rem;}
[data-testid="stHeader"] {background:transparent;}
/* A markdown block alone in a column keeps Streamlit's -16px bottom margin, which pushes it off-centre in centred rows */
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:only-child [data-testid="stMarkdownContainer"] {margin-bottom:0;}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:only-child [data-testid="stMarkdownContainer"] p {margin-bottom:0;}
.hca-links {display:flex;align-items:center;gap:24px;font-size:14px;}
.hca-links a {color:var(--text-2)!important;text-decoration:none;}
.hca-links a:hover {color:var(--primary-strong)!important;}
.hca-eyebrow {font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--primary);margin-top:4px;}
.hca-lead {font-size:15px;color:var(--text-2);margin:4px 0 8px;}
/* st.metric as the Figma stat cards */
[data-testid="stMetric"] {background:#FFFFFF;border:1px solid var(--border);border-radius:10px;padding:18px 20px;}
[data-testid="stMetricValue"] {font-weight:600;color:var(--ink);}
/* Tabs styled like the header navigation */
[data-baseweb="tab-list"] {border-bottom:1px solid var(--border);gap:24px;}
[data-baseweb="tab"] {font-size:15px;color:var(--text-2);padding-left:2px;padding-right:2px;}
[data-baseweb="tab"]:is([aria-selected="true"], [data-selected]) {color:var(--primary);}
/* Workflow step indicator */
.hca-stepper {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:20px 24px;margin:4px 0 18px;
              border:1px solid var(--border);border-radius:10px;background:#FFFFFF;overflow:hidden;}
.hca-step {position:relative;display:flex;align-items:center;min-width:0;}
.hca-step:not(:last-child)::after {content:"";position:absolute;left:44px;right:10px;top:15px;height:2px;background:var(--surface-2);}
.hca-step.is-complete:not(:last-child)::after {background:var(--primary-line);}
.hca-step-circle {z-index:1;display:grid;place-items:center;flex:0 0 32px;width:32px;height:32px;margin-right:12px;
                  border-radius:999px;background:var(--surface-2);color:var(--muted);font-size:13px;font-weight:700;}
.is-current .hca-step-circle, .is-complete .hca-step-circle {background:var(--primary);color:#FFFFFF;}
.hca-step-copy {z-index:2;min-width:0;padding-right:16px;background:#FFFFFF;}
.hca-step-title {color:var(--ink);font-size:14px;font-weight:650;white-space:nowrap;}
.is-current .hca-step-title {color:var(--primary);}
.hca-step-status {color:var(--muted);font-size:11px;}
@media (max-width:760px) {
  .hca-stepper {grid-template-columns:1fr;row-gap:14px;}
  .hca-step:not(:last-child)::after {left:15px;right:auto;top:36px;width:2px;height:14px;}
  .hca-step-copy {padding-right:0;}
}
/* Upload area (dropzone) */
[data-testid="stFileUploaderDropzone"] {min-height:140px;border:1px dashed var(--primary-line)!important;border-radius:10px!important;
                                        background:var(--primary-faint)!important;transition:border-color 160ms ease,background 160ms ease;}
[data-testid="stFileUploaderDropzone"]:hover, [data-testid="stFileUploaderDropzone"]:focus-within {
  border-color:var(--primary)!important;background:var(--primary-faint)!important;}
[data-testid="stFileUploaderDropzone"] button {color:var(--primary)!important;border-color:var(--primary-line)!important;font-weight:650!important;}
[data-testid="stFileUploaderDropzoneInstructions"] svg {color:var(--primary)!important;}
/* Check & harmonize tab (Figma step 2/3/4 screens) */
.hca-h1 {font-size:32px;font-weight:600;color:var(--ink);margin:6px 0 6px;padding:0;}
.hca-stats {display:grid;grid-template-columns:repeat(var(--hca-cols,3),minmax(0,1fr));gap:20px;margin:14px 0 18px;}
@media (max-width:720px) {.hca-stats {grid-template-columns:1fr;}}
.hca-stat {background:#FFFFFF;border:1px solid var(--border);border-radius:10px;padding:24px;}
.hca-stat--accent {background:var(--primary-soft);border-color:var(--primary-line);}
.hca-stat-value {font-size:34px;font-weight:600;color:var(--ink);line-height:1.1;}
.hca-stat--accent .hca-stat-value {color:var(--primary);}
.hca-stat-label {font-size:15px;font-weight:600;color:var(--ink);margin-top:12px;}
.hca-stat-sub {font-size:13px;color:var(--muted);margin-top:4px;}
.hca-run-note {color:var(--text-2);font-size:14px;text-align:right;margin:0;}
.hca-card {background:#FFFFFF;border:1px solid var(--border);border-radius:10px;padding:22px 24px;margin-bottom:18px;}
.hca-card-head {display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px;}
.hca-card-title {font-size:18px;font-weight:600;color:var(--ink);}
.hca-card-sub {font-size:13px;color:var(--muted);margin-top:2px;}
.hca-pill {font-size:12px;color:var(--text-2);background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:3px 10px;white-space:nowrap;}
.hca-progress-head {display:flex;align-items:flex-end;justify-content:space-between;margin:18px 0 12px;}
.hca-big {font-size:38px;font-weight:600;color:var(--ink);}
.hca-big-total {font-size:20px;color:var(--muted);}
.hca-pct {font-size:28px;font-weight:600;color:var(--primary);}
.hca-bar {height:8px;border-radius:999px;background:var(--surface-2);overflow:hidden;margin-bottom:10px;}
.hca-bar-fill {height:100%;background:var(--primary);border-radius:999px;transition:width 300ms ease;}
.hca-check {display:flex;align-items:center;gap:14px;padding:12px 0;}
.hca-check-icon {flex:0 0 20px;width:20px;height:20px;border-radius:999px;border:1.5px solid var(--faint);
                 display:grid;place-items:center;font-size:11px;}
.hca-check--done .hca-check-icon {border-color:var(--teal);color:var(--teal);}
.hca-check--running .hca-check-icon {border-color:var(--primary-line);border-top-color:var(--primary);animation:hca-spin 900ms linear infinite;}
@keyframes hca-spin {to {transform:rotate(360deg);}}
.hca-check-copy {flex:1;min-width:0;}
.hca-check-title {font-size:14px;color:var(--ink);font-weight:500;}
.hca-check-sub {font-size:12px;color:var(--muted);}
.hca-check-state {font-size:12px;color:var(--muted);}
.hca-check--done .hca-check-state {color:var(--teal);}
.hca-check--running .hca-check-state {color:var(--primary);}
.hca-log-row {display:flex;gap:18px;font-size:13px;color:var(--text-2);padding:5px 0;}
.hca-log-time {font-family:"JetBrains Mono",monospace;color:var(--muted);min-width:52px;}
.hca-run-file {font-weight:600;color:var(--ink);margin:14px 0 10px;}
.hca-kv {display:flex;justify-content:space-between;font-size:14px;color:var(--text-2);padding:7px 0;}
.hca-kv strong {color:var(--ink);}
.hca-tag {display:inline-block;margin-top:10px;font-size:12px;color:var(--teal);background:var(--teal-soft);border-radius:6px;padding:3px 10px;}
.hca-tag--warn {color:var(--amber-text);background:var(--amber-soft);border:1px solid #F1D3A0;}
.hca-stepnum {display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--primary);color:#FFFFFF;font-size:13px;font-weight:700;margin-right:10px;}
/* Upload step: two source panels with a "+" between them */
.st-key-panel_inventory, .st-key-panel_new {border-top:4px solid var(--primary)!important;}
.hca-plus {text-align:center;font-size:34px;font-weight:300;color:var(--faint);line-height:1;margin-top:110px;}
.hca-links .hca-tag {margin-top:0;}
.hca-note {background:var(--primary-soft);border-radius:10px;padding:20px 24px;color:var(--text-2);font-size:14px;}
.hca-note-title {color:var(--primary);font-weight:600;margin-bottom:6px;}
.hca-note p {margin:0;}
</style>''', unsafe_allow_html=True)


# HTML pieces for the Check & harmonize tab, following the Figma step 2/3/4 screens.
# Kept on single lines so Markdown never turns indented HTML into code blocks.

def format_elapsed(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    return f'{minutes}m {seconds:02d}s' if minutes else f'{seconds}s'


def page_intro_html(eyebrow, title, lead):
    return (f'<div class="hca-eyebrow">{html.escape(eyebrow)}</div><h2 class="hca-h1">{html.escape(title)}</h2>'
            f'<p class="hca-lead">{html.escape(lead)}</p>')


def stat_cards_html(cards):
    """cards: list of (value, label, sub, accent)."""
    return f'<div class="hca-stats" style="--hca-cols:{len(cards)}">' + ''.join(
        f'<div class="hca-stat{" hca-stat--accent" if accent else ""}"><div class="hca-stat-value">{value}</div>'
        f'<div class="hca-stat-label">{html.escape(label)}</div><div class="hca-stat-sub">{html.escape(sub)}</div></div>'
        for value, label, sub, accent in cards) + '</div>'


def _check_row(state, title, sub):
    icon = '&#10003;' if state == 'done' else ''
    label = {'done': 'Complete', 'running': 'Running', 'waiting': 'Waiting'}[state]
    return (f'<div class="hca-check hca-check--{state}"><div class="hca-check-icon">{icon}</div>'
            f'<div class="hca-check-copy"><div class="hca-check-title">{html.escape(title)}</div>'
            f'<div class="hca-check-sub">{html.escape(sub)}</div></div><div class="hca-check-state">{label}</div></div>')


def processing_card_html(file_name, n_model, model_done, n_inventory, n_duplicate, n_total, groups_done, n_groups, complete=False):
    finished = complete or groups_done >= n_groups
    pct = 100 if n_model == 0 else min(100, round(100 * model_done / n_model))
    rows = [
        _check_row('done', 'Validate file and required columns', f'{n_total} items validated'),
        _check_row('done', 'Compare items with the inventory', f'{n_inventory} reused from the inventory · {n_duplicate} possible duplicates'),
        _check_row('done' if finished else 'running', 'Process new items with the model',
                   f'{model_done} of {n_model} items processed · {groups_done} of {n_groups} questionnaires'),
        _check_row('done' if complete else ('running' if finished else 'waiting'), 'Prepare results for review',
                   'Combine inventory records and model suggestions'),
    ]
    return (f'<div class="hca-card"><div class="hca-card-head"><div><div class="hca-card-title">Model processing</div>'
            f'<div class="hca-card-sub">{html.escape(file_name)} · {n_model} new items</div></div>'
            f'<span class="hca-pill">{"Complete" if complete else "In progress"}</span></div>'
            f'<div class="hca-progress-head"><div><span class="hca-big">{model_done}</span>'
            f'<span class="hca-big-total"> / {n_model}</span>'
            f'<div class="hca-card-sub">new items processed · {n_model - model_done} remaining</div></div>'
            f'<div class="hca-pct">{pct}%</div></div>'
            f'<div class="hca-bar"><div class="hca-bar-fill" style="width:{pct}%"></div></div>'
            + ''.join(rows) + '</div>')


def activity_card_html(entries, live=True):
    rows = ''.join(f'<div class="hca-log-row"><span class="hca-log-time">{format_elapsed(t)}</span>'
                   f'<span>{html.escape(text)}</span></div>' for t, text in entries[-8:])
    return (f'<div class="hca-card"><div class="hca-card-head"><div class="hca-card-title">Run activity</div>'
            f'<span class="hca-pill">{"Live" if live else "Finished"}</span></div>{rows}</div>')


def run_card_html(file_name, n_total, n_inventory, n_model, elapsed):
    rows = ''.join(f'<div class="hca-kv"><span>{k}</span><strong>{v}</strong></div>' for k, v in [
        ('Total items', n_total), ('Inventory matches', n_inventory), ('Sent to the model', n_model),
        ('Elapsed time', format_elapsed(elapsed))])
    return (f'<div class="hca-card"><div class="hca-card-title">This run</div>'
            f'<div class="hca-run-file">{html.escape(file_name)}</div>{rows}</div>')


RUN_TIMEOUT_MINUTES = 30
DEFAULT_FLAG_THRESHOLD = 0.40  # mean confidence in the research project this tool is built on
KEEP_OPEN_HTML = ('<div class="hca-note"><div class="hca-note-title">&#9432; Keep this page open</div>'
                  '<p>Results will be available once processing is complete. Model suggestions should be reviewed before export.</p>'
                  '<p style="margin-top:8px">The first run can download model weights (about 1.5 GB per construct), so it may take '
                  f'several minutes. The run stops automatically after {RUN_TIMEOUT_MINUTES} minutes.</p></div>')
engine = importlib.util.find_spec('harmonica') is not None
engine_badge = ('<span class="hca-tag" title="The HarmoniCA engine is installed in this environment">Engine ready</span>' if engine else
                '<span class="hca-tag hca-tag--warn" title="Install HarmoniCA in this Python environment to run harmonization">Engine not found</span>')
logo = logo_uris()
st.markdown(f'''
<div class="hca-header">
  <div class="hca-brand">
    <div class="hca-brand-row">
      <img class="hca-mark" src="{logo['mark']}" alt="">
      <img class="hca-word" src="{logo['wordmark']}" alt="HarmoniCA">
    </div>
    <img class="hca-tagline" src="{logo['tagline']}" alt="Harmonizing Clinical Assessments">
  </div>
  <div class="hca-links">
    <a href="https://github.com/julia-pfarr/HarmoniCA#readme" target="_blank">Documentation &#8599;</a>
    {engine_badge}
  </div>
</div>
''', unsafe_allow_html=True)

items = None
source_name = 'example_items.csv'
# The workflow bar is the main navigation. Detailed result views live underneath Results.
RESULT_VIEWS = ['Overview', 'Review items', 'Explore results']
WORKFLOW_VIEWS = ['Upload', 'Review & confirm', 'Harmonization', 'Results', 'Score transformation']


def go_to_tab(label):
    if label == 'Prepare':
        st.session_state.main_tab = 'Upload'
    elif label in RESULT_VIEWS:
        st.session_state.main_tab = 'Results'
        st.session_state.results_tab = label
    else:
        st.session_state.main_tab = label


stored_tab = st.session_state.get('main_tab', 'Upload')
if stored_tab == 'Prepare':
    stored_tab = 'Upload'
elif stored_tab in RESULT_VIEWS:
    st.session_state.results_tab = stored_tab
    stored_tab = 'Results'
if stored_tab not in WORKFLOW_VIEWS:
    stored_tab = 'Upload'
st.session_state.main_tab = stored_tab

# Support both older BaseWeb tabs and newer accessible Streamlit tabs.
st.markdown("""<style>
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {
    display:flex; gap:0; background:#FFFFFF; border:1px solid var(--border);
    border-radius:10px; padding:20px 24px; min-height:110px;
    width:100%; box-sizing:border-box;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {
    flex:1 1 0!important; width:auto!important; height:64px; padding:0 12px 14px 0; justify-content:flex-start;
    color:var(--ink); position:relative; border-radius:6px; overflow:visible;
    gap:12px; white-space:nowrap;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) p {
    font-size:17px; font-weight:650; background:white; padding-right:14px;
    position:relative; z-index:2;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::before {
    display:grid; place-items:center; width:40px; height:40px; flex:0 0 40px;
    border-radius:50%; background:var(--surface-2); color:var(--muted);
    font-size:13px; font-weight:700; position:relative; z-index:2;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(1)::before {content:"1";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(2)::before {content:"2";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(3)::before {content:"3";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(4)::before {content:"4";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(5)::before {content:"5";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::after {
    content:""; position:absolute; left:52px; right:12px; top:24px;
    height:2px; background:var(--surface-2); z-index:0;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(5)::after {display:none;}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):is([aria-selected="true"], [data-selected]) {color:var(--primary);}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):is([aria-selected="true"], [data-selected])::before {background:var(--primary); color:white;}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):hover p {color:var(--primary);}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):focus-visible {outline:2px solid var(--primary); outline-offset:2px;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {display:none;}
[data-testid="stTabs"] [data-testid="stTab"] > span {display:none;}
/* Nested Results controls are ordinary tabs, outside the framed bar. */
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {
    background:transparent; border:0; border-bottom:1px solid var(--border);
    border-radius:0; padding:0; min-height:0; gap:24px;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {
    flex:0 0 auto!important; height:42px; padding:0 2px; background:transparent;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) p {
    font-size:15px; font-weight:400; background:transparent; padding-right:0;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::before,
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::after {content:none; display:none;}
[data-testid="stTabs"] [data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-testid="stTabs"] [data-baseweb="tab-border"] {display:block;}
[data-testid="stTabs"] [data-testid="stTabs"] [data-testid="stTab"] > span {display:block;}
@media (max-width:640px) {
    [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {padding:12px; overflow-x:auto;}
    [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {flex:0 0 auto; min-width:155px;}
    [data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {padding:0;}
}
</style>""", unsafe_allow_html=True)
prepare, check, harmonize, results, score = st.tabs(WORKFLOW_VIEWS, key='main_tab', on_change='rerun')
with results:
    overview, review, explore = st.tabs(RESULT_VIEWS, key='results_tab', on_change='rerun')

@st.cache_data
def load_inventory():
    """The harmonized questionnaires that researchers can reuse, one row per item."""
    return pd.read_csv(Path(__file__).with_name('assets')/'reference_inventory.csv', dtype=str,
                       keep_default_na=False).drop_duplicates(['construct', 'questionnaire', 'item_id'], keep='last')


def dup_key(construct, questionnaire, item_id):
    return f'same|{construct}|{questionnaire}|{item_id}'


def review_key(construct, questionnaire, item_id):
    return f'{construct}|{questionnaire}|{item_id}'


with prepare:
    st.markdown(page_intro_html('Step 1 of 5', 'Choose your questionnaires',
                                'Take them from the inventory, add your own, or use both.'), unsafe_allow_html=True)
    inventory = load_inventory()
    inv_col, plus_col, new_col = st.columns([10, 1, 10])
    with inv_col, st.container(border=True, key='panel_inventory'):
        st.markdown('<div class="hca-card-title">From the inventory</div>'
                    '<div class="hca-card-sub">Already harmonized. Reused instantly.</div>', unsafe_allow_html=True)
        pairs = list(inventory[['construct', 'questionnaire']].drop_duplicates().sort_values(['construct', 'questionnaire'])
                     .itertuples(index=False, name=None))
        picked = st.multiselect('Questionnaires', pairs, key='inventory_picks', format_func=lambda p: f'{p[1]} · {p[0]}',
                                placeholder='Search or choose questionnaires')
        # Inventory items bring their answer options / scoring along where we have them (otherwise empty)
        inventory_items = (inventory.merge(pd.DataFrame(picked, columns=['construct', 'questionnaire']), on=['construct', 'questionnaire'])[COLUMNS]
                           .merge(load_response_options(), on=['construct', 'questionnaire', 'item_id'], how='left').fillna('')[ITEM_COLUMNS]
                           if picked else pd.DataFrame(columns=ITEM_COLUMNS))
        st.caption(f'{len(picked)} questionnaires · {len(inventory_items)} items' if picked else 'Nothing selected yet.')
    plus_col.markdown('<div class="hca-plus">+</div>', unsafe_allow_html=True)
    with new_col, st.container(border=True, key='panel_new'):
        st.markdown('<div class="hca-card-title">Your new questionnaires</div>'
                    '<div class="hca-card-sub">Not in the inventory yet. The model harmonizes them.</div>', unsafe_allow_html=True)
        uploaded = st.file_uploader('Upload CSV or Excel files', type=['csv', 'xlsx'], accept_multiple_files=True)
        st.caption('Columns: construct, questionnaire, item_id, item_text, answer_options, scoring.')
        with st.expander('What goes in answer_options and scoring?'):
            st.markdown('- **answer_options**: the answer choices, as a list.\n'
                        '- **scoring**: the numeric score of each choice, in the same order. The highest value is the item\'s maximum score.\n'
                        '- Later, your participants\' responses must use these scores (reverse-score items first).')
            st.dataframe(pd.DataFrame({'item_id': ['DEMO_01', 'DEMO_04'],
                                       'answer_options': ['["Not at all", "Sometimes", "Often", "Always"]', '["Yes", "No"]'],
                                       'scoring': ['[0, 1, 2, 3]', '[0, 1]']}), hide_index=True, width='stretch')
        sample = Path(__file__).with_name('example_items.csv').read_bytes()
        st.download_button('Download input template', sample, 'example_items.csv', 'text/csv')
    summary_slot = st.container()

    sources = [(u.name, u.getvalue()) for u in uploaded]
    frames, summaries = [], []
    for index, (filename, raw) in enumerate(sources):
        file_key = hashlib.sha256(filename.encode()+raw).hexdigest()[:16]+'_'+str(index)
        with st.expander(f'Your file: {filename}', expanded=True):
            try:
                if len(raw) > 10*1024*1024:
                    raise ValueError('File exceeds 10 MB.')
                if filename.lower().endswith('.xlsx'):
                    workbook = pd.ExcelFile(io.BytesIO(raw))
                    sheet = st.selectbox('Worksheet', workbook.sheet_names, key='sheet_'+file_key)
                    frame = pd.read_excel(workbook, sheet_name=sheet, dtype=str).fillna('')
                    file_key += hashlib.sha256(sheet.encode()).hexdigest()[:8]
                else:
                    detected = detect_separator(raw)
                    separator = st.selectbox('CSV separator', SEPARATORS, index=SEPARATORS.index(detected),
                                             format_func=lambda x: {',':'Comma',';':'Semicolon','\t':'Tab'}[x],
                                             key='sep_'+file_key,
                                             help='Detected automatically from the header row. Change it if columns look wrong.')
                    frame = pd.read_csv(io.BytesIO(raw), sep=separator, dtype=str, keep_default_na=False, encoding='utf-8-sig')
                frame.columns = frame.columns.astype(str).str.strip()
                if frame.empty or not len(frame.columns):
                    raise ValueError('No item rows found.')
                if all(field in frame.columns for field in ITEM_COLUMNS):
                    st.success(f'Loaded {len(frame)} rows. All {len(ITEM_COLUMNS)} columns were matched automatically.')
                    adjust = st.checkbox('Change column mapping', key='adjust_'+file_key)
                else:
                    st.caption(f'Loaded {len(frame)} rows. Match your columns to HarmoniCA fields.')
                    adjust = True
                mapping = {}
                cols = st.columns(2)
                for i, field in enumerate(ITEM_COLUMNS):
                    if not adjust:
                        mapping[field] = field
                        continue
                    options = ['— Select —'] + list(frame.columns)
                    with cols[i % 2]:
                        mapping[field] = st.selectbox(field, options, index=options.index(field) if field in options else 0, key=f'map_{field}_{file_key}')
                chosen = list(mapping.values())
                if '— Select —' in chosen:
                    st.warning(f'Match all {len(ITEM_COLUMNS)} columns to enable running.')
                elif len(set(chosen)) != len(ITEM_COLUMNS):
                    st.error('Choose a different source column for each field.')
                else:
                    mapped = pd.DataFrame({field:frame[column] for field,column in mapping.items()})
                    st.caption('Edit input items if needed')
                    edited = st.data_editor(mapped, hide_index=True, num_rows='dynamic', width='stretch', key='input_'+file_key+hashlib.sha256(str(mapping).encode()).hexdigest())
                    file_items = parse_items(edited.to_csv(index=False).encode())
                    unknown = set(file_items.construct)-set(CATALOG['CONSTRUCTS'])
                    if unknown:
                        raise ValueError('Unsupported constructs: '+', '.join(sorted(unknown))+'. Supported: '+', '.join(CATALOG['CONSTRUCTS']))
                    frames.append(file_items)
                    summaries.append({'File': filename, 'Items': len(file_items), 'Questionnaires': ', '.join(sorted(file_items.questionnaire.unique()))})
            except Exception as exc:
                st.error(f'{filename}: {exc}')

    # Combine both panels into the one set of items the rest of the app works with.
    items, problem = None, None
    uploads_ok = len(frames) == len(sources)
    file_items = pd.concat(frames, ignore_index=True) if frames and uploads_ok else pd.DataFrame(columns=ITEM_COLUMNS)
    item_keys = lambda df: list(zip(df.construct, df.questionnaire, df.item_id))
    # Items in your files take the place of picked inventory items with the same ID; whether they are the
    # same item is decided on the next page, item by item.
    file_keys = set(item_keys(file_items))
    inventory_part = inventory_items[[k not in file_keys for k in item_keys(inventory_items)]]
    file_part = file_items
    if sources and not uploads_ok:
        problem = 'Complete the column mapping and resolve errors in every file before running.'
    elif len(inventory_part) or len(file_part):
        try:
            items = parse_items(pd.concat([inventory_part, file_part], ignore_index=True).to_csv(index=False).encode(), scoring='optional')
        except Exception as exc:
            problem = f'Combined input needs attention: {exc}'
    if len(summaries) > 1:
        st.dataframe(pd.DataFrame(summaries), hide_index=True, width='stretch')

    n_from_files = len(file_part)
    n_from_inventory = len(inventory_part)
    situation = ('mixed' if n_from_inventory and n_from_files else 'inventory' if n_from_inventory
                 else 'new' if n_from_files else None)
    source_name = ' + '.join(([f'Inventory ({len(picked)} questionnaires)'] if picked else []) + [n for n, _ in sources]) or 'no items yet'
    # Canonical combined bytes identify the complete input in the run record.
    raw = items.to_csv(index=False).encode() if items is not None else None

    # Everything the user chose in the two panels is harmonized.
    selected = items if items is not None else pd.DataFrame(columns=ITEM_COLUMNS)
    constructs = sorted(selected.construct.unique())
    # Identifies the current selection; results remember the one they were made from.
    fingerprint = hashlib.sha256(selected.to_csv(index=False).encode()).hexdigest()

    with summary_slot:
        if problem:
            st.warning(problem)
        elif situation is None:
            st.caption('Pick questionnaires from the inventory, upload your own, or do both.')
        else:
            bits = []
            if n_from_inventory:
                bits.append(f'**{n_from_inventory}** items from the inventory (reused)')
            if n_from_files:
                bits.append(f'**{n_from_files}** items from your files (new ones go through the model)')
            st.markdown(' + '.join(bits))

    if not selected.empty:
        st.button('Continue to Review & confirm →', type='primary', width='stretch',
                  on_click=go_to_tab, args=('Review & confirm',))

# Shared numbers for the Review & confirm and Harmonization tabs
decisions = {'same_items': [], 'rerun_items': []}
if not selected.empty:
    routed = inventory_check(selected)
    keys = item_keys(routed)
    # Items from your files that we think are already in the inventory (exact or same wording) are listed one by one.
    # The user confirms each as the same item (ticked by default) or not.
    routed['candidate'] = [k in file_keys and route != 'new' for k, route in zip(keys, routed.route)]
    routed['same'] = [cand and st.session_state.get(dup_key(*k), True) for k, cand in zip(keys, routed.candidate)]
    reused = ((routed.route == 'inventory') & ~routed.candidate) | routed.same
    decisions['same_items'] = [list(k) for k, r, same in zip(keys, routed.route, routed.same) if same and r == 'duplicate']
    decisions['rerun_items'] = [list(k) for k, r, cand, same in zip(keys, routed.route, routed.candidate, routed.same)
                                if cand and not same and r == 'inventory']
    n_total = len(routed)
    n_exact = int(((routed.route == 'inventory') & ~routed.candidate).sum())
    n_duplicate = int(routed.candidate.sum())
    n_same = int(routed.same.sum())
    n_inventory = int(reused.sum())
    n_model = n_total - n_inventory
    n_groups = selected.groupby(['construct', 'questionnaire']).ngroups
    group_model_counts = routed[~reused].groupby(['construct', 'questionnaire']).size().to_dict()
    model_keys = [review_key(*k) for k, r in zip(keys, reused) if not r]   # the items the model runs on
    # Answers change what the run does, so they are part of what results are compared against.
    fingerprint = hashlib.sha256(selected.to_csv(index=False).encode()
                                 + json.dumps(decisions, sort_keys=True).encode()).hexdigest()

# A run happens in a background thread so that switching tabs (which reruns this
# script) never interrupts it. The thread only updates the plain `job` dict; the
# results are moved into session state here, on the next rerun after it finishes.
job = st.session_state.get('run_job')
running = job is not None and job['status'] == 'running'
if job is not None and job['status'] == 'done' and not job.get('collected'):
    job['collected'] = True
    st.session_state.update(result=job['result'], log=job['log'], manifest=job['manifest'],
                            run_summary=job, result_fingerprint=job['fingerprint'], review_decisions={})
has_result = 'result' in st.session_state
# Results are kept when the selection changes; they're only replaced by a new run.
stale = has_result and st.session_state.get('result_fingerprint') != fingerprint

# The confidence threshold for flagging items is set in Review items; the other subpages read the shared value.
threshold = st.session_state.get('flag_threshold', DEFAULT_FLAG_THRESHOLD)


def stale_notice():
    if stale:
        st.warning('These results are from a previous selection or run settings. They are kept until you run '
                   'harmonization again from **Review & confirm**.')


REVIEW_ACCEPT, REVIEW_CHANGE, REVIEW_PENDING = 'Accept', 'Change to: ', '— choose —'


def catalog_label(construct, dimension, fallback):
    """The catalog's label for a dimension ID (labels in stored results can differ from the current catalog)."""
    return CATALOG['DIMENSION_DESCRIPTIONS'].get(construct, {}).get(str(dimension).split('.')[0], {}).get('label', fallback)


def apply_review(result, review_decisions):
    """The engine's result with the researcher's review decisions applied.

    Only model predictions can be reviewed: inventory items are expert consensus and are never changed.
    Reviewed items get source 'expert_reviewed'. A changed item gets the new dimension and label; the model's
    original assignment stays in original_dimension / original_dimension_label (empty for unchanged items).
    """
    final = result.copy()
    final['original_dimension'] = ''
    final['original_dimension_label'] = ''
    index_of = {review_key(c, q, i): idx for idx, c, q, i in zip(final.index, final.construct, final.questionnaire, final.item_id)}
    for key, decision in review_decisions.items():
        idx = index_of.get(key)
        if idx is None or final.at[idx, 'source'] != 'model':
            continue
        if decision.startswith(REVIEW_CHANGE):
            label = decision[len(REVIEW_CHANGE):]
            ids = {d['label']: k for k, d in CATALOG['DIMENSION_DESCRIPTIONS'].get(final.at[idx, 'construct'], {}).items()}
            # Changing to the dimension it already has is the same as accepting
            if label in ids and ids[label] != str(final.at[idx, 'dimension']).split('.')[0]:
                final.at[idx, 'original_dimension'] = final.at[idx, 'dimension']
                final.at[idx, 'original_dimension_label'] = final.at[idx, 'dimension_label']
                final.at[idx, 'dimension'] = ids[label]
                final.at[idx, 'dimension_label'] = label
        final.at[idx, 'source'] = 'expert_reviewed'
    return final


# What the Results page shows and downloads: the engine's result with the review decisions applied
final_result = apply_review(st.session_state.result, st.session_state.get('review_decisions', {})) if has_result else None


def score_step_html(number, title, sub):
    return (f'<div class="hca-card-title"><span class="hca-stepnum">{number}</span>{html.escape(title)}</div>'
            f'<div class="hca-card-sub" style="margin-bottom:10px">{html.escape(sub)}</div>')


def flagged_items(all_items, threshold):
    """Model-predicted items to review: confidence below the threshold, or missing. Inventory items are never listed."""
    model_items = all_items[all_items.source == 'model']
    confidence = pd.to_numeric(model_items.confidence, errors='coerce')
    return model_items[confidence.isna() | (confidence < threshold)]


def download_bar():
    """'Download output' block at the end of the Overview subpage."""
    with st.container(border=True):
        title, button = st.columns([3, 1], vertical_alignment='center')
        title.markdown('<div class="hca-card-title">Download output</div>', unsafe_allow_html=True)
        button.download_button('Harmonized items (CSV)', final_result.to_csv(index=False).encode(), 'harmonized_items.csv', 'text/csv',
                               type='primary', width='stretch', icon=':material/download:', key='dl_csv')


def run_job(job, df, timeout):
    def on_progress(event):
        if event is not None:
            key = (event['construct'], event['questionnaire'])
            job['groups_done'] += 1
            job['model_done'] += job['group_model_counts'].get(key, 0)
            job['activity'].append((time.monotonic() - job['started'],
                                    f"{event['questionnaire']} ({event['construct']}): {event['items']} items done, "
                                    f"{job['group_model_counts'].get(key, 0)} sent to the model."))
    try:
        data, result, log = run_harmonica(df, timeout=timeout, on_progress=on_progress, decisions=job['decisions'])
        # The engine reports one source per questionnaire; make it per item: only these items were predicted by the model.
        model_keys = set(job['model_keys'])
        result['source'] = ['model' if review_key(c, q, i) in model_keys else 'inventory'
                            for c, q, i in zip(result.construct, result.questionnaire, result.item_id)]
        # Carry each item's answer options and scoring into the result, so the downloaded CSV can be scored
        result = result.merge(df[['construct', 'questionnaire', 'item_id'] + SCORING_COLUMNS], on=['construct', 'questionnaire', 'item_id'], how='left')
        result[SCORING_COLUMNS] = result[SCORING_COLUMNS].fillna('')
        job['activity'].append((time.monotonic() - job['started'], 'Results combined and ready for review.'))
        job.update(data=data, result=result, log=log, status='done')
    except Exception as exc:
        job.update(error=str(exc), status='error')
    job['elapsed'] = time.monotonic() - job['started']


def start_run(df, context):
    job = dict(context, status='running', started=time.monotonic(), elapsed=0, model_done=0, groups_done=0,
               activity=[(0, f"Run started with {context['n_model']} new items across {context['n_groups']} questionnaires.")])
    if context['n_inventory']:
        job['activity'].append((0, f"{context['n_inventory']} items reused from the inventory."))
    st.session_state.run_job = job
    threading.Thread(target=run_job, args=(job, df, RUN_TIMEOUT_MINUTES * 60), daemon=True).start()
    go_to_tab('Harmonization')


def run_view(job, live):
    """Model processing, activity and run cards for a running or finished job."""
    elapsed = time.monotonic() - job['started'] if live else job['elapsed']
    left_col, right_col = st.columns([2.2, 1])
    left_col.markdown(processing_card_html(job['source_name'], job['n_model'], job['model_done'], job['n_inventory'],
                                           job['n_duplicate'], job['n_total'], job['groups_done'], job['n_groups'],
                                           complete=not live), unsafe_allow_html=True)
    left_col.markdown(activity_card_html(job['activity'], live=live), unsafe_allow_html=True)
    right_col.markdown(run_card_html(job['source_name'], job['n_total'], job['n_inventory'], job['n_model'], elapsed),
                       unsafe_allow_html=True)
    if live:
        right_col.markdown(KEEP_OPEN_HTML, unsafe_allow_html=True)


with check:
    if selected.empty:
        st.info('Prepare your items in the **Upload** tab first.')
    else:
        st.markdown(page_intro_html('Step 2 of 5', 'Review and confirm',
                                    'Items we already know are reused. New items are sent to the model.'),
                    unsafe_allow_html=True)
        st.markdown(stat_cards_html([
            (n_exact, 'From the inventory', 'Picked by you, no check needed', False),
            (n_duplicate, 'Possible duplicates', f'Same as an inventory item · {n_same} marked as the same', False),
            (n_model, 'Items sent to the model', f'{n_model / n_total:.1%} of your selection', True),
        ]), unsafe_allow_html=True)
        if n_duplicate:
            dups = routed[routed.candidate]
            dup_keys = [dup_key(c, q, i) for c, q, i in zip(dups.construct, dups.questionnaire, dups.item_id)]

            def mark_all(value, keys=dup_keys):
                for key in keys:
                    st.session_state[key] = value

            with st.container(border=True):
                head, same_all, none_all = st.columns([3, 1, 1], vertical_alignment='center')
                head.markdown(f'<div class="hca-card-title">{n_duplicate} possible duplicate(s)</div>'
                              f'<div class="hca-card-sub">We think these are already in the inventory. Tick the ones that are '
                              f'the same; the others are sent to the model.</div>', unsafe_allow_html=True)
                same_all.button('All the same', on_click=mark_all, args=(True,), disabled=running, width='stretch', key='dups_all_same')
                none_all.button('None the same', on_click=mark_all, args=(False,), disabled=running, width='stretch', key='dups_none_same')
                with st.container(height=min(60 + 70 * len(dups), 420) if len(dups) > 5 else 'content'):
                    cols = st.columns([1, 4, 4, 2])
                    for col, label in zip(cols, ['Same item?', 'Your item', 'Inventory item', 'Dimension']):
                        col.caption(label)
                    for row, key in zip(dups.itertuples(), dup_keys):
                        c0, c1, c2, c3 = st.columns([1, 4, 4, 2], vertical_alignment='center')
                        st.session_state.setdefault(key, True)
                        c0.checkbox('Same item', key=key, label_visibility='collapsed', disabled=running)
                        c1.markdown(f'**{row.questionnaire} · {row.item_id}**  \n{row.item_text}')
                        c2.markdown(f'**{row.matched_item_id}**  \n{row.matched_item_text}')
                        c3.write(row.matched_dimension_label)
        if has_result and not running:
            st.info('A previous run is kept. Running again will replace its results'
                    + (' and your review decisions.' if st.session_state.get('review_decisions') else '.'))
        if not engine:
            st.error('The HarmoniCA engine was not found, so a run cannot start. Activate the Python environment in which '
                     '`harmonica --help` works, then restart this app.')
        back, note, action = st.columns([1, 2, 1], vertical_alignment='center')
        back.button('Previous: Upload', width='stretch', on_click=go_to_tab, args=('Prepare',), key='back_to_prepare')
        note.markdown(f'<p class="hca-run-note">'
                      + ('A run is in progress' if running else f'{n_model} item(s) will be processed by the model') + '</p>',
                      unsafe_allow_html=True)
        context = {'source_name': source_name, 'fingerprint': fingerprint,
                   'n_total': n_total, 'n_inventory': n_inventory, 'n_duplicate': n_duplicate, 'n_model': n_model,
                   'n_groups': n_groups, 'group_model_counts': group_model_counts, 'model_keys': model_keys, 'decisions': decisions,
                   'manifest': {'created_utc': datetime.now(timezone.utc).isoformat(), 'input_file': source_name,
                                'input_sha256': hashlib.sha256(raw).hexdigest() if raw else '',
                                'submitted_sha256': hashlib.sha256(selected.to_csv(index=False).encode()).hexdigest(),
                                'selected_items': len(selected), 'constructs': constructs, 'decisions': decisions,
                                'output_rows': len(selected), 'upstream_commit': 'b074bf07970959b4d5021e2cfbeff34a6b012385'}}
        action.button('Run harmonization →', type='primary', disabled=not engine or running, width='stretch',
                      on_click=start_run, args=(selected.copy(), context))

with harmonize:
    if running:
        st.markdown(page_intro_html('Step 3 of 5', 'Harmonizing your items',
                                    f"The model is processing new items. Your {job['n_inventory']} items reused from the inventory are already ready."),
                    unsafe_allow_html=True)

        @st.fragment(run_every=1.0)
        def live_progress():
            # Refreshes every second on its own; you can switch tabs while it runs.
            current = st.session_state.run_job
            run_view(current, live=current['status'] == 'running')
            if current['status'] != 'running':
                st.rerun(scope='app')

        live_progress()
        back, note, action = st.columns([1, 2, 1], vertical_alignment='center')
        back.button('Previous: Review & confirm', width='stretch', on_click=go_to_tab, args=('Review & confirm',),
                    key='back_to_check')
        note.markdown('<p class="hca-run-note">Available when processing completes · you can browse other tabs meanwhile</p>',
                      unsafe_allow_html=True)
        action.button('View results →', type='primary', width='stretch', disabled=True, key='view_results_wait')
    elif job is not None and job['status'] == 'error':
        st.markdown(page_intro_html('Step 3 of 5', 'Harmonizing your items', 'The last run failed.'), unsafe_allow_html=True)
        st.error('Mapping failed. See the engine details below.' + (' Your earlier results are kept.' if has_result else ''))
        st.code(job['error'], language=None)
        st.button('Previous: Review & confirm', on_click=go_to_tab, args=('Review & confirm',), key='back_to_check_error')
    elif has_result:
        stale_notice()
        summary = st.session_state.run_summary
        st.markdown(page_intro_html('Step 3 of 5', 'Harmonizing your items',
                                    'Processing is complete. Model suggestions should be reviewed before export.'),
                    unsafe_allow_html=True)
        run_view(summary, live=False)
        back, note, action = st.columns([1, 2, 1], vertical_alignment='center')
        back.button('Previous: Review & confirm', width='stretch', on_click=go_to_tab, args=('Review & confirm',),
                    key='back_to_check')
        note.markdown('<p class="hca-run-note">Results are ready</p>', unsafe_allow_html=True)
        action.button('View results →', type='primary', width='stretch', on_click=go_to_tab, args=('Overview',))
    elif selected.empty:
        st.info('Prepare your items in the **Upload** tab first.')
    else:
        st.markdown(page_intro_html('Step 3 of 5', 'Harmonizing your items',
                                    'Start a run from the Review & confirm tab. Progress will appear here.'),
                    unsafe_allow_html=True)
        st.button('Previous: Review & confirm', on_click=go_to_tab, args=('Review & confirm',), key='back_to_check_idle')

# Ask the browser to confirm before a refresh or close would lose a run or its results.
st.iframe('<script>window.parent.onbeforeunload = '
                + ('function (e) { e.preventDefault(); e.returnValue = ""; return ""; }' if running or has_result else 'null')
                + ';</script>', height=1)


with overview:
    stale_notice()
    if 'result' not in st.session_state:
        st.info('Run harmonization from the **Review & confirm** tab to see your results.')
    else:
        result = final_result
        # A quiet hint: flagged model predictions nobody has looked at yet
        to_review = flagged_items(st.session_state.result, threshold)
        reviewed_keys = st.session_state.get('review_decisions', {})
        pending = sum(review_key(c, q, i) not in reviewed_keys for c, q, i in zip(to_review.construct, to_review.questionnaire, to_review.item_id))
        if pending:
            with st.container(border=True):
                hint, jump = st.columns([4, 1], vertical_alignment='center')
                hint.markdown(f'**{pending} predicted item{"s" if pending != 1 else ""}** with low confidence can be reviewed.')
                jump.button('Review items →', on_click=go_to_tab, args=('Review items',), width='stretch', key='review_hint')
        a, b, c = st.columns(3)
        a.metric('Harmonized items', len(result))
        b.metric('Questionnaires', result.groupby(['construct', 'questionnaire']).ngroups)
        c.metric('Constructs', result.construct.nunique())
        table = result[['construct', 'questionnaire', 'item_id', 'item_text', 'dimension_label', 'confidence']].copy()
        table['confidence'] = pd.to_numeric(table.confidence, errors='coerce')
        table.columns = ['Construct', 'Questionnaire', 'Item ID', 'Item text', 'Dimension', 'Confidence']
        st.dataframe(table, hide_index=True, width='stretch',
                     column_config={'Confidence': st.column_config.NumberColumn(format='%.2f')})
        download_bar()

with review:
    stale_notice()
    if not has_result:
        st.info('Run harmonization from the **Review & confirm** tab to review items.')
    else:
        # Only model predictions are reviewed; items reused from the inventory are expert consensus.
        all_items = st.session_state.result.reset_index(drop=True)
        result = all_items[all_items.source == 'model']
        store = st.session_state.setdefault('review_decisions', {})
        if result.empty:
            st.info('All items come from the inventory (expert consensus), so there is nothing to review. '
                    'Inventory assignments are never changed here.')
        else:
            with st.container(border=True):
                slider_col, count_col = st.columns([3, 2], vertical_alignment='center')
                threshold = slider_col.slider('Flag items with confidence below', 0.0, 1.0, DEFAULT_FLAG_THRESHOLD, 0.05, key='flag_threshold',
                                              help='A review threshold, not a validated error cutoff. Confidence is an engine score, '
                                                   'not calibrated clinical certainty. Items without a confidence are always flagged.')
                flagged = flagged_items(all_items, threshold)
                count_col.markdown(f'<div class="hca-card-title">{len(flagged)} of {len(result)} predicted items flagged</div>'
                                   f'<div class="hca-card-sub">Only items predicted by the model are listed. Accept each mapping or '
                                   f'change it to another dimension. Inventory items are expert consensus.</div>',
                                   unsafe_allow_html=True)
            if flagged.empty:
                st.success('No predicted items are below the threshold.')
            store_changed = False
            for construct in flagged.construct.unique():
                rows = flagged[flagged.construct == construct]
                keys = [review_key(construct, q, i) for q, i in zip(rows.questionnaire, rows.item_id)]
                labels = [d['label'] for d in CATALOG['DIMENSION_DESCRIPTIONS'][construct].values()]
                table = pd.DataFrame({
                    'Questionnaire': rows.questionnaire.values, 'Item ID': rows.item_id.values, 'Item text': rows.item_text.values,
                    'Assigned dimension': [catalog_label(construct, d, l) for d, l in zip(rows.dimension, rows.dimension_label)],
                    'Confidence': pd.to_numeric(rows.confidence, errors='coerce').values,
                    'Decision': [store.get(k, REVIEW_PENDING) for k in keys]})
                st.subheader(construct.capitalize())
                edited = st.data_editor(
                    table, hide_index=True, width='stretch', key='review_' + construct + '_' + hashlib.sha256('|'.join(keys).encode()).hexdigest()[:12],
                    disabled=[c for c in table.columns if c != 'Decision'],
                    column_config={'Confidence': st.column_config.NumberColumn(format='%.2f'),
                                   'Decision': st.column_config.SelectboxColumn(
                                       'Decision', options=[REVIEW_PENDING, REVIEW_ACCEPT] + [REVIEW_CHANGE + l for l in labels],
                                       help='Accept the assigned dimension, or change it to another one.')})
                for key, decision in zip(keys, edited['Decision']):
                    if pd.isna(decision) or decision == REVIEW_PENDING:
                        store_changed |= store.pop(key, None) is not None
                    elif store.get(key) != decision:
                        store[key] = decision
                        store_changed = True
            if store_changed:
                st.rerun()  # so the Overview, its download and the charts show the latest decisions
            if len(flagged):
                n_done = sum(review_key(c, q, i) in store for c, q, i in zip(flagged.construct, flagged.questionnaire, flagged.item_id))
                st.progress(n_done / len(flagged), text=f'{n_done} of {len(flagged)} flagged items reviewed')
        st.button('Done, back to overview', type='primary', on_click=go_to_tab, args=('Overview',), key='review_done')

with explore:
    stale_notice()
    if 'result' not in st.session_state:
        st.info('Run harmonization from the **Review & confirm** tab to explore your results.')
    else:
        result=final_result
        # Everything at once, one section per construct (dimensions differ between constructs).
        for construct in result.construct.unique():
            subset=result[result.construct==construct].copy()
            subset['dimension_label']=subset.apply(lambda r: CATALOG['DIMENSION_DESCRIPTIONS'][construct].get(str(r.dimension).split('.')[0],{}).get('label',r.dimension_label),axis=1)
            st.subheader(construct.capitalize())
            st.caption(f'{len(subset)} items · {subset.questionnaire.nunique()} questionnaires. Hover over a flow to see the item count.')
            st.plotly_chart(flow_figure(subset),width='stretch',key='flow_'+construct)
            st.markdown('**Assignment confidence**')
            st.caption('Confidence of stored inventory entries can reflect expert agreement rather than a fresh model score.')
            st.plotly_chart(confidence_figure(subset),width='stretch',key='confidence_'+construct)

with score:
    st.markdown(page_intro_html('Step 5 of 5', 'Score transformation',
                                "Turn your participants' item responses into comparable dimension scores. Everything runs on your computer."),
                unsafe_allow_html=True)
    one, two, three = st.columns(3)
    with one, st.container(border=True, key='score_step_1'):
        st.markdown(score_step_html(1, 'Download the code', 'Python code that scores your participants.'), unsafe_allow_html=True)
        st.download_button('Download code (ZIP)', build_kit_zip(), 'harmonica_score_transformation.zip', 'application/zip',
                           type='primary', width='stretch', icon=':material/download:', key='dl_kit')
    with two, st.container(border=True, key='score_step_2'):
        st.markdown(score_step_html(2, 'Prepare your responses', 'One row per participant: an ID plus one column per item.'),
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({'participant_id': ['p001', 'p002'], 'BDI_01': ['2', '0'], 'BDI_02': ['0', '3'], 'GDS_01': ['1', '']}),
                     hide_index=True, width='stretch')
        st.caption('Use the scores from your scoring lists (reverse-score first if needed). Missing: empty or -9.')
        if has_result and len(responses_template(final_result).split(b',')) > 1:
            st.download_button('Download template (CSV)', responses_template(final_result), 'responses_template.csv', 'text/csv',
                               width='stretch', key='dl_template')
    with three, st.container(border=True, key='score_step_3'):
        st.markdown(score_step_html(3, 'Run it', 'Put your two CSV files next to the script, then:'), unsafe_allow_html=True)
        st.code('python run_score_transformation.py', language='bash')
        st.caption('The files: harmonized_items.csv (from Results) and responses.csv. Needs Python 3.10+ with pandas.')
    with st.expander('What you get'):
        st.markdown('- **Dimension scores** per participant, questionnaire and dimension: raw score, proportion of the maximum, '
                    'and two percentile scores (within the questionnaire, and averaged across questionnaires).\n'
                    '- A **reliability flag** per score (how many items were answered).\n'
                    '- The same scores in a wide table, one column per dimension.')
        st.caption('A dimension score is empty if more than half of its items are missing. Percentile scores are estimated from your own '
                   'sample, so they depend on it and do not guarantee clinical equivalence.')
    unscored = unscored_questionnaires(final_result) if has_result else []
    if unscored:
        with st.expander(f'Not included: {len(unscored)} questionnaire{"s" if len(unscored) != 1 else ""} with items we have no scoring for'):
            st.caption('These items have no answer_options / scoring and are left out of the scores.')
            st.dataframe(pd.DataFrame(unscored, columns=['Construct', 'Questionnaire', 'Items without scoring', 'Items']),
                         hide_index=True, width='stretch')
