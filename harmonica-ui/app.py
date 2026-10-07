import hashlib
import io
import json
import os
import shutil
import importlib.util
import sys
import html
from visuals import comparison_figure, flow_figure, coverage_figure, confidence_figure, decorate, probabilities
import plotly.express as px
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
from backend import COLUMNS, SEPARATORS, detect_separator, inventory_check, parse_items, run_harmonica
from harmonize_workflow import append_model_predictions, persistent_inventory_path, render_manual_workflow

CATALOG = json.loads(Path(__file__).with_name('assets').joinpath('model_catalog.json').read_text())
if os.environ.get('HARMONICA_SOURCE_DIR'):
    sys.path.insert(0, os.environ['HARMONICA_SOURCE_DIR'])

st.set_page_config(page_title='HarmoniCA', page_icon='🎼', layout='wide')
# Header and card styles from the HarmoniCA Figma template (shared with the Gradio app)
st.markdown('''<style>
.hca-header {display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;
             padding:4px 0 18px;margin-bottom:12px;border-bottom:1px solid #E5E7EB;}
.hca-brand {display:flex;align-items:center;gap:12px;}
.hca-logo {width:38px;height:38px;border-radius:8px;display:grid;place-items:center;background:#F9ECEF;color:#A33B5C;}
.hca-title {font-size:24px;line-height:1.1;color:#1F2430;}
.hca-subtitle {font-size:12px;color:#6B7280;}
.hca-links {display:flex;align-items:center;gap:24px;font-size:14px;}
.hca-links a {color:#4B5563!important;text-decoration:none;}
.hca-links a:hover {color:#A33B5C!important;}
.hca-workspace {display:inline-flex;align-items:center;gap:6px;color:#A33B5C;font-weight:500;}
.hca-eyebrow {font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#A33B5C;margin-top:4px;}
.hca-lead {font-size:15px;color:#4B5563;margin:4px 0 8px;}
/* st.metric as the Figma stat cards */
[data-testid="stMetric"] {background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;padding:18px 20px;}
[data-testid="stMetricValue"] {font-weight:600;color:#1F2430;}
/* Tabs styled like the header navigation */
[data-baseweb="tab-list"] {border-bottom:1px solid #E5E7EB;gap:24px;}
[data-baseweb="tab"] {font-size:15px;color:#4B5563;padding-left:2px;padding-right:2px;}
[data-baseweb="tab"][aria-selected="true"] {color:#A33B5C;}
/* Four-step workflow indicator (ported from the Gradio stepper) */
.hca-stepper {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:20px 24px;margin:4px 0 18px;
              border:1px solid #E5E7EB;border-radius:10px;background:#FFFFFF;overflow:hidden;}
.hca-step {position:relative;display:flex;align-items:center;min-width:0;}
.hca-step:not(:last-child)::after {content:"";position:absolute;left:44px;right:10px;top:15px;height:2px;background:#EDF0F3;}
.hca-step.is-complete:not(:last-child)::after {background:#F0CBD6;}
.hca-step-circle {z-index:1;display:grid;place-items:center;flex:0 0 32px;width:32px;height:32px;margin-right:12px;
                  border-radius:999px;background:#EEF1F4;color:#9AA2AD;font-size:13px;font-weight:700;}
.is-current .hca-step-circle, .is-complete .hca-step-circle {background:#A33B5C;color:#FFFFFF;}
.hca-step-copy {z-index:2;min-width:0;padding-right:16px;background:#FFFFFF;}
.hca-step-title {color:#1F2430;font-size:14px;font-weight:650;white-space:nowrap;}
.is-current .hca-step-title {color:#A33B5C;}
.hca-step-status {color:#77808E;font-size:11px;}
@media (max-width:760px) {
  .hca-stepper {grid-template-columns:1fr;row-gap:14px;}
  .hca-step:not(:last-child)::after {left:15px;right:auto;top:36px;width:2px;height:14px;}
  .hca-step-copy {padding-right:0;}
}
/* Upload area styled like the Figma dropzone (ported from the Gradio upload styling) */
[data-testid="stFileUploaderDropzone"] {min-height:140px;border:1px dashed #E7C6D0!important;border-radius:10px!important;
                                        background:#FCF9FA!important;transition:border-color 160ms ease,background 160ms ease;}
[data-testid="stFileUploaderDropzone"]:hover, [data-testid="stFileUploaderDropzone"]:focus-within {
  border-color:#A33B5C!important;background:#FFFAFB!important;}
[data-testid="stFileUploaderDropzone"] button {color:#A33B5C!important;border-color:#E7C6D0!important;font-weight:650!important;}
[data-testid="stFileUploaderDropzoneInstructions"] svg {color:#A33B5C!important;}
/* Check & harmonize tab (Figma step 2/3/4 screens) */
.hca-h1 {font-size:32px;font-weight:600;color:#1F2430;margin:6px 0 6px;padding:0;}
.hca-stats {display:grid;grid-template-columns:repeat(var(--hca-cols,3),minmax(0,1fr));gap:20px;margin:14px 0 18px;}
@media (max-width:720px) {.hca-stats {grid-template-columns:1fr;}}
.hca-stat {background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;padding:24px;}
.hca-stat--accent {background:#F9ECEF;border-color:#F0CBD6;}
.hca-stat-value {font-size:34px;font-weight:600;color:#1F2430;line-height:1.1;}
.hca-stat--accent .hca-stat-value {color:#A33B5C;}
.hca-stat-label {font-size:15px;font-weight:600;color:#1F2430;margin-top:12px;}
.hca-stat-sub {font-size:13px;color:#6B7280;margin-top:4px;}
.hca-run-note {color:#4B5563;font-size:14px;text-align:right;margin:0;}
.hca-card {background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;padding:22px 24px;margin-bottom:18px;}
.hca-card-head {display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px;}
.hca-card-title {font-size:18px;font-weight:600;color:#1F2430;}
.hca-card-sub {font-size:13px;color:#6B7280;margin-top:2px;}
.hca-pill {font-size:12px;color:#4B5563;background:#F3F4F6;border:1px solid #E5E7EB;border-radius:6px;padding:3px 10px;white-space:nowrap;}
.hca-progress-head {display:flex;align-items:flex-end;justify-content:space-between;margin:18px 0 12px;}
.hca-big {font-size:38px;font-weight:600;color:#1F2430;}
.hca-big-total {font-size:20px;color:#6B7280;}
.hca-pct {font-size:28px;font-weight:600;color:#A33B5C;}
.hca-bar {height:8px;border-radius:999px;background:#F3F4F6;overflow:hidden;margin-bottom:10px;}
.hca-bar-fill {height:100%;background:#A33B5C;border-radius:999px;transition:width 300ms ease;}
.hca-check {display:flex;align-items:center;gap:14px;padding:12px 0;}
.hca-check-icon {flex:0 0 20px;width:20px;height:20px;border-radius:999px;border:1.5px solid #C4C9D0;
                 display:grid;place-items:center;font-size:11px;}
.hca-check--done .hca-check-icon {border-color:#2F6B57;color:#2F6B57;}
.hca-check--running .hca-check-icon {border-color:#F0CBD6;border-top-color:#A33B5C;animation:hca-spin 900ms linear infinite;}
@keyframes hca-spin {to {transform:rotate(360deg);}}
.hca-check-copy {flex:1;min-width:0;}
.hca-check-title {font-size:14px;color:#1F2430;font-weight:500;}
.hca-check-sub {font-size:12px;color:#6B7280;}
.hca-check-state {font-size:12px;color:#9AA2AD;}
.hca-check--done .hca-check-state {color:#2F6B57;}
.hca-check--running .hca-check-state {color:#A33B5C;}
.hca-log-row {display:flex;gap:18px;font-size:13px;color:#4B5563;padding:5px 0;}
.hca-log-time {font-family:"JetBrains Mono",monospace;color:#9AA2AD;min-width:52px;}
.hca-run-file {font-weight:600;color:#1F2430;margin:14px 0 10px;}
.hca-kv {display:flex;justify-content:space-between;font-size:14px;color:#4B5563;padding:7px 0;}
.hca-kv strong {color:#1F2430;}
.hca-tag {display:inline-block;margin-top:10px;font-size:12px;color:#2F6B57;background:#E8F3EE;border-radius:6px;padding:3px 10px;}
.hca-tag--off {color:#4B5563;background:#F3F4F6;}
.hca-note {background:#F9ECEF;border-radius:10px;padding:20px 24px;color:#4B5563;font-size:14px;}
.hca-note-title {color:#A33B5C;font-weight:600;margin-bottom:6px;}
.hca-note p {margin:0;}
.hca-route-bar {display:flex;height:10px;border-radius:999px;overflow:hidden;margin:22px 0 8px;background:#A33B5C;}
.hca-route-inv {background:#2F6B57;}
.hca-route-new {flex:1;background:#A33B5C;}
.hca-route-legend {display:flex;justify-content:space-between;font-size:12px;color:#6B7280;margin-bottom:8px;}
.hca-route-row {display:flex;align-items:center;gap:14px;padding:16px 0;border-bottom:1px solid #E5E7EB;}
.hca-route-icon {flex:0 0 22px;color:#6B7280;}
.hca-route-icon--queued {color:#A33B5C;}
.hca-badge {font-size:12px;border-radius:6px;padding:3px 10px;white-space:nowrap;}
.hca-badge--ready {color:#2F6B57;background:#E8F3EE;}
.hca-badge--queued {color:#A33B5C;background:#F9ECEF;}
.hca-badge--off {color:#4B5563;background:#F3F4F6;}
.hca-run-banner {display:flex;align-items:flex-start;gap:14px;margin:0 0 18px;padding:16px 20px;border:1px solid #F0CF8E;
                 border-left:6px solid #E09F1F;border-radius:10px;background:#FFF6E5;}
.hca-run-banner-icon {font-size:22px;line-height:1.2;color:#B97A0B;}
.hca-run-banner-title {font-size:16px;font-weight:700;color:#6B4200;margin-bottom:2px;}
.hca-run-banner p {margin:0;font-size:14px;color:#5C4306;}
.hca-item-row {display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding:12px 0;border-top:1px solid #EEF0F3;}
.hca-item-row:first-child {border-top:0;padding-top:4px;}
.hca-item-main {flex:1 1 0;min-width:0;}
.hca-item-meta {font-size:12px;color:#6B7280;}
.hca-item-text {font-size:15px;color:#1F2430;margin-top:2px;overflow-wrap:anywhere;}
.hca-item-side {flex:0 0 34%;display:flex;flex-direction:column;align-items:flex-end;gap:4px;text-align:right;}
.hca-item-side .hca-pill {white-space:normal;text-align:right;}
.hca-item-conf {font-size:12px;color:#6B7280;}
.hca-item-conf--low {color:#A33B5C;font-weight:600;}
@media (max-width:720px) {.hca-item-row {flex-direction:column;gap:6px;} .hca-item-side {flex:none;align-items:flex-start;text-align:left;}}
/* Framed workflow navigation; nested Results tabs retain the standard tab style. */
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {
    display:flex;gap:0;background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;
    padding:20px 24px;min-height:110px;width:100%;box-sizing:border-box;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {
    flex:1 1 0!important;width:auto!important;height:64px;padding:0 12px 14px 0;
    justify-content:flex-start;color:#1F2430;position:relative;border-radius:6px;overflow:visible;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) p {
    font-size:17px;font-weight:650;background:#FFFFFF;padding-right:14px;position:relative;z-index:2;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::before {
    display:grid;place-items:center;width:40px;height:40px;flex:0 0 40px;margin-right:12px;
    border-radius:50%;background:#EEF1F4;color:#9AA2AD;font-size:14px;font-weight:700;z-index:1;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(1)::before {content:"1";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(2)::before {content:"2";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(3)::before {content:"3";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(4)::before {content:"4";}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"])::after {
    content:"";position:absolute;left:52px;right:12px;top:24px;height:2px;background:#EDF0F3;z-index:0;
}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):nth-child(4)::after {display:none;}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):is([aria-selected="true"], [data-selected]) {color:#A33B5C;}
[data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]):is([aria-selected="true"], [data-selected])::before {background:#A33B5C;color:#FFFFFF;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {display:none;}
[data-testid="stTabs"] [data-testid="stTab"] > span {display:none;}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {
    display:flex;background:transparent;border:0;border-bottom:1px solid #E5E7EB;border-radius:0;
    padding:0;min-height:0;gap:24px;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {
    flex:0 0 auto!important;height:42px;padding:0 2px;background:transparent;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) p {
    font-size:15px;font-weight:400;background:transparent;padding-right:0;
}
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab"], [role="tab"])::before,
[data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab"], [role="tab"])::after {content:none;display:none;}
[data-testid="stTabs"] [data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-testid="stTabs"] [data-baseweb="tab-border"] {display:block;}
[data-testid="stTabs"] [data-testid="stTabs"] [data-testid="stTab"] > span {display:block;}
@media (max-width:640px) {
    [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {padding:12px;overflow-x:auto;}
    [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) :is([data-baseweb="tab"], [role="tab"]) {flex:0 0 auto;min-width:155px;}
    [data-testid="stTabs"] [data-testid="stTabs"] :is([data-baseweb="tab-list"], [role="tablist"]) {padding:0;}
}
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
        _check_row('done', 'Compare items with the inventory', f'{n_inventory} exact matches · {n_duplicate} possible duplicates'),
        _check_row('done' if finished else 'running', 'Process new items with the model',
                   f'{model_done} of {n_model} items processed'),
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


def run_card_html(file_name, n_total, n_inventory, n_model, elapsed, force):
    rows = ''.join(f'<div class="hca-kv"><span>{k}</span><strong>{v}</strong></div>' for k, v in [
        ('Total items', n_total), ('Inventory matches', n_inventory), ('Sent to the model', n_model),
        ('Elapsed time', format_elapsed(elapsed))])
    tag = 'Inventory reuse disabled' if force else 'Inventory reuse enabled'
    return (f'<div class="hca-card"><div class="hca-card-title">This run</div>'
            f'<div class="hca-run-file">{html.escape(file_name)}</div>{rows}'
            f'<span class="hca-tag{" hca-tag--off" if force else ""}">{tag}</span></div>')


_DB_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
           '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>')
_COPY_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">'
             '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>'
             '<path d="m11.5 14.5 2 2 4-4"/></svg>')
_SPARK_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">'
              '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/></svg>')


def routing_card_html(n_total, n_inventory, n_duplicate, n_model, force):
    pct_inv = 0 if n_total == 0 else 100 * n_inventory / n_total
    reuse_sub = ('Inventory reuse is off: every item goes to the model.' if force
                 else f'{n_inventory} items will use their existing inventory records.')
    rows = [
        (_DB_SVG, 'Reuse inventory matches', reuse_sub, 'Skipped' if force else 'Ready', 'off' if force else 'ready'),
        (_COPY_SVG, 'No duplicate review needed' if n_duplicate == 0 else f'{n_duplicate} possible duplicate(s)',
         '0 possible duplicates under different item IDs.' if n_duplicate == 0 else
         'Same wording as an inventory item under a different item ID · processed by the model as new items.',
         'Clear' if n_duplicate == 0 else 'Found', 'off' if n_duplicate == 0 else 'queued'),
        (_SPARK_SVG, 'Harmonize new items', f'{n_model} new items are queued for model processing.', 'Queued', 'queued'),
    ]
    return (f'<div class="hca-card"><div class="hca-card-title">Item routing</div>'
            f'<div class="hca-card-sub">{n_total} total items · Every item accounted for</div>'
            f'<div class="hca-route-bar"><div class="hca-route-inv" style="width:{pct_inv:.1f}%"></div>'
            f'<div class="hca-route-new"></div></div>'
            f'<div class="hca-route-legend"><span>{n_inventory} matched · {pct_inv:.1f}%</span>'
            f'<span>{n_model} new · {100 - pct_inv:.1f}%</span></div>'
            + ''.join(f'<div class="hca-route-row"><div class="hca-route-icon hca-route-icon--{kind}">{icon}</div>'
                      f'<div class="hca-check-copy"><div class="hca-check-title">{title}</div>'
                      f'<div class="hca-check-sub">{html.escape(sub)}</div></div>'
                      f'<span class="hca-badge hca-badge--{kind}">{badge}</span></div>'
                      for icon, title, sub, badge, kind in rows)
            + '</div>')


def source_card_html(file_name, size_bytes, n_total):
    size = f'{size_bytes / 1024:.1f} KB · ' if size_bytes else ''
    return (f'<div class="hca-card"><div class="hca-card-title">Source file</div>'
            f'<div class="hca-run-file">{html.escape(file_name)}</div>'
            f'<div class="hca-card-sub">{size}{n_total} total items</div>'
            f'<span class="hca-tag">Inventory check complete</span></div>')


KEEP_OPEN_HTML = ('<div class="hca-note"><div class="hca-note-title">&#9432; Keep this page open</div>'
                  '<p>Results will be available once processing is complete. Model suggestions should be reviewed before export.</p></div>')
RUN_BANNER_HTML = ('<div class="hca-run-banner" role="alert"><div class="hca-run-banner-icon">&#9888;</div><div>'
                   '<div class="hca-run-banner-title">Keep this page open while HarmoniCA runs</div>'
                   '<p>Closing or refreshing this tab loses the run and its results. You can switch between tabs while you wait.</p>'
                   '</div></div>')
st.markdown('''
<div class="hca-header">
  <div class="hca-brand">
    <div class="hca-logo"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linejoin="round"><path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z"/>
      <path d="m3 12 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/></svg></div>
    <div><div class="hca-title">HarmoniCA</div><div class="hca-subtitle">Harmonizing Clinical Assessments</div></div>
  </div>
  <div class="hca-links">
    <a href="https://github.com/julia-pfarr/HarmoniCA#readme" target="_blank">Documentation &#8599;</a>
  </div>
</div>
''', unsafe_allow_html=True)
engine = importlib.util.find_spec('harmonica') is not None
RESULT_VIEWS = ['Visual dashboard', 'Item inspector', 'Models & dimensions']
WORKFLOW_VIEWS = ['Prepare', 'Inventory check', 'Harmonization', 'Results']
sidebar_tab = st.session_state.get('tab_ids_by_title', {}).get(
    st.session_state.get('main_tab', 'Prepare'), st.session_state.get('main_tab', 'Prepare'))
if sidebar_tab in RESULT_VIEWS:
    st.session_state.results_tab = sidebar_tab
    sidebar_tab = 'Results'
if sidebar_tab == 'Results':
    sidebar_tab = st.session_state.get('results_tab', 'Visual dashboard')
with st.sidebar:
    st.subheader('Analysis settings')
    # Plain if/else: a one-line conditional expression would be echoed by Streamlit 'magic'
    if engine:
        st.success('Engine available')
    else:
        st.warning('Engine not found')
    # Set from 'Run settings' in the Inventory check tab (read here because Prepare runs first)
    force = st.session_state.get('force_rerun', False)
    minutes = st.number_input('Run timeout (minutes)', 1, 180, 30)
    threshold = st.session_state.get('review_threshold', 0.65)
    active_tab = st.session_state.get('tab_ids_by_title', {}).get(
        st.session_state.get('main_tab', 'Prepare'), 'Prepare')
    if sidebar_tab in RESULT_VIEWS and 'result' in st.session_state:
        st.divider()
        threshold = st.slider('Flag confidence below', 0.0, 1.0, 0.65, 0.05, key='review_threshold')
        st.caption('A review threshold, not a validated error cutoff. Confidence is an engine score, not calibrated clinical certainty.')
    st.caption('First runs can download model weights. Keep the browser open until completion.')

items = None
source_name = 'example_items.csv'
job = st.session_state.get('run_job')
running = job is not None and job['status'] == 'running'
if job is not None and job['status'] == 'done' and not job.get('collected'):
    job['collected'] = True
    st.session_state.update(result=job['result'], result_bytes=job['data'], log=job['log'], manifest=job['manifest'],
                            run_summary=job, result_fingerprint=job['fingerprint'], decisions={})
has_result = 'result' in st.session_state
tab_ids = WORKFLOW_VIEWS
tab_titles = {label: label for label in tab_ids}
stored_tab = st.session_state.get('main_tab')
selected_tab = st.session_state.get('tab_ids_by_title', {}).get(stored_tab, stored_tab)
if selected_tab in RESULT_VIEWS:
    st.session_state.results_tab = selected_tab
    selected_tab = 'Results'
st.session_state.main_tab = tab_titles.get(selected_tab, tab_titles['Prepare'])
st.session_state.tab_ids_by_title = {title: label for label, title in tab_titles.items()}
if running:
    st.markdown(RUN_BANNER_HTML, unsafe_allow_html=True)
tabs = dict(zip(tab_ids, st.tabs([tab_titles[label] for label in tab_ids], key='main_tab', on_change='rerun')))
prepare, check, harmonize, results = (tabs[label] for label in tab_ids)
with results:
    explore, review, models = st.tabs(RESULT_VIEWS, key='results_tab', on_change='rerun')


def go_to_tab(label):
    if label in RESULT_VIEWS:
        st.session_state.main_tab = tab_titles['Results']
        st.session_state.results_tab = label
    else:
        st.session_state.main_tab = tab_titles.get(label, label)

with prepare:
    st.markdown(page_intro_html('Section 1', 'Add questionnaire items',
                                'Upload a questionnaire file, choose a reference questionnaire, or enter items manually.'),
                unsafe_allow_html=True)
    mode = st.radio('Input source', ['Upload files', 'Explore reference inventory', 'Enter items manually'],
                    horizontal=True, key='prepare_input_source')
    if mode == 'Enter items manually':
        render_manual_workflow(CATALOG, lambda: go_to_tab('Inventory check'))
        manual_items = st.session_state.get('workflow_items') if st.session_state.get('workflow_stage', 1) >= 2 else None
        items = manual_items
        selected = manual_items.copy() if manual_items is not None else pd.DataFrame(columns=COLUMNS)
        constructs = sorted(selected.construct.unique()) if not selected.empty else []
        source_name = 'manual entries'
        raw = selected.to_csv(index=False).encode() if not selected.empty else b''
        fingerprint = hashlib.sha256(selected.to_csv(index=False).encode()+str(force).encode()).hexdigest()
    else:
        left, right = st.columns([3,2])
        with left:
            st.subheader('Questionnaire input')
            uploads = st.file_uploader('Upload CSV or Excel files', type=['csv','xlsx'], accept_multiple_files=True)
            st.caption('Select one format per questionnaire. Files sharing questionnaire names are combined; conflicting item IDs must be resolved.')
            sample = Path(__file__).with_name('example_items_redesign.csv').read_bytes()
            st.download_button('Download input template', sample, 'example_items.csv','text/csv')
            if mode == 'Explore reference inventory':
                seed = pd.read_csv(Path(__file__).with_name('assets')/'reference_inventory.csv',dtype=str,keep_default_na=False).drop_duplicates(['construct','questionnaire','item_id'],keep='last')
                reference_construct = st.selectbox('Reference construct',CATALOG['CONSTRUCTS'])
                choices = sorted(seed.loc[seed.construct==reference_construct,'questionnaire'].unique())
                reference_q = st.multiselect('Reference questionnaires',choices,default=choices[:2])
                raw = seed.loc[(seed.construct==reference_construct)&seed.questionnaire.isin(reference_q),COLUMNS].to_csv(index=False).encode()
                sources = [('reference_items.csv', raw)]
            else:
                sources = [(u.name, u.getvalue()) for u in uploads]
            source_name = ', '.join(name for name, _ in sources)
            frames, summaries = [], []
            raw = None
            for index, (filename, file_raw) in enumerate(sources):
                raw = file_raw
                source_name_for_file = filename
                file_key = hashlib.sha256(filename.encode()+raw).hexdigest()[:16]+'_'+str(index)
                with st.expander(filename, expanded=True):
                    try:
                        if len(raw) > 10*1024*1024:
                            raise ValueError('File exceeds 10 MB.')
                        if source_name_for_file.lower().endswith('.xlsx'):
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
                        st.caption(f'Loaded {len(frame)} rows. Match your columns to HarmoniCA fields.')
                        mapping = {}
                        cols = st.columns(2)
                        for i, field in enumerate(COLUMNS):
                            options = ['— Select —'] + list(frame.columns)
                            with cols[i % 2]:
                                mapping[field] = st.selectbox(field, options, index=options.index(field) if field in options else 0, key=f'map_{field}_{file_key}')
                        chosen = list(mapping.values())
                        if '— Select —' in chosen:
                            st.warning('Match all four columns to enable running.')
                        elif len(set(chosen)) != 4:
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
            if sources and len(frames) == len(sources):
                try:
                    items = parse_items(pd.concat(frames, ignore_index=True).to_csv(index=False).encode())
                    st.dataframe(pd.DataFrame(summaries), hide_index=True, width='stretch')
                    st.success(f'{len(sources)} files ready: {len(items)} items across {items.questionnaire.nunique()} questionnaires.')
                    st.markdown(page_intro_html('Section 2', 'Review & edit',
                                                'Check the combined item list before selecting what to harmonize.'),
                                unsafe_allow_html=True)
                    review_key = hashlib.sha256(items.to_csv(index=False).encode()).hexdigest()[:16]
                    edited_items = st.data_editor(items, hide_index=True, num_rows='dynamic', width='stretch',
                                                  key='combined_review_'+review_key)
                    items = parse_items(edited_items.to_csv(index=False).encode())
                    unknown = set(items.construct)-set(CATALOG['CONSTRUCTS'])
                    if unknown:
                        raise ValueError('Unsupported constructs: '+', '.join(sorted(unknown))+'. Supported: '+', '.join(CATALOG['CONSTRUCTS']))
                except Exception as exc:
                    items = None
                    st.error(f'Combined input needs attention: {exc}')
            elif sources:
                st.warning('Complete the column mapping and resolve errors in every file before running, or select **Enter items manually** above.')
            else:
                st.info('Upload files or choose “Explore reference inventory”.')
            raw = items.to_csv(index=False).encode() if items is not None else None
        with right:
            st.subheader('Selection')
            if items is not None:
                in_file = [c for c in CATALOG['CONSTRUCTS'] if c in set(items.construct)]
                constructs = st.multiselect('Constructs', CATALOG['CONSTRUCTS'], key='run_constructs',
                                            placeholder='Choose one or more constructs')
                missing = [c for c in constructs if c not in in_file]
                if missing:
                    st.caption('No items in your input for: '+', '.join(missing))
                q_options = sorted(items.loc[items.construct.isin(constructs), 'questionnaire'].unique())
                st.session_state.run_questionnaires = [q for q in st.session_state.get('run_questionnaires', []) if q in q_options]
                questionnaires = st.multiselect('Questionnaires', q_options, key='run_questionnaires',
                                                placeholder='Choose questionnaires' if q_options else 'Choose a construct first',
                                                disabled=not q_options)
                selected = items[items.construct.isin(constructs) & items.questionnaire.isin(questionnaires)]
                st.metric('Items ready', len(selected))
            else:
                selected = pd.DataFrame(columns=COLUMNS)
                constructs = []
            fingerprint = hashlib.sha256(selected.to_csv(index=False).encode()+str(force).encode()).hexdigest()
            if items is None:
                st.info('Upload and validate your items.')
            elif selected.empty:
                st.info('Choose the constructs and questionnaires to harmonize.')
            else:
                st.success('Ready. Continue to check the inventory and run HarmoniCA.')
            st.button('Continue to Inventory check →', type='primary', width='stretch',
                      disabled=selected.empty or running, on_click=go_to_tab, args=('Inventory check',))

# Shared numbers for the Inventory check and Harmonization tabs
if not selected.empty:
    routed = inventory_check(selected, force)
    n_total = len(routed)
    n_inventory = int((routed.route == 'inventory').sum())
    n_duplicate = int((routed.route == 'duplicate').sum())
    n_model = n_total - n_inventory
    n_groups = selected.groupby(['construct', 'questionnaire']).ngroups

# A run happens in a background thread so that switching tabs (which reruns this
# script) never interrupts it. The thread only updates the plain `job` dict; the
# results are moved into session state here, on the next rerun after it finishes.
# Results are kept when the selection changes; they're only replaced by a new run.
stale = has_result and st.session_state.get('result_fingerprint') != fingerprint
active_tab = st.session_state.get('tab_ids_by_title', {}).get(st.session_state.get('main_tab'), 'Prepare')
step_now = (3 if running else 4 if has_result and not stale else
            1 if active_tab == 'Prepare' else 2 if active_tab == 'Inventory check' else
            3)
if step_now != st.session_state.get('step', 1):
    st.session_state.step = step_now


def stale_notice():
    if stale:
        st.warning('These results are from a previous selection or run settings. They are kept until you run '
                   'harmonization again from **Inventory check**.')


def reviewed_table(result, decisions):
    """Results plus the researcher's review decisions from the Item inspector."""
    reviewed = result.copy()
    reviewed['review_status'] = 'Pending'; reviewed['reviewed_dimension'] = ''; reviewed['review_note'] = ''
    for key, decision in decisions.items():
        for field, value in decision.items():
            reviewed.loc[int(key), field] = value
    return reviewed


def item_row_html(row, threshold):
    confidence = pd.to_numeric(row.confidence, errors='coerce')
    low = bool(pd.notna(confidence) and confidence < threshold)
    confidence_text = ('Confidence unavailable' if pd.isna(confidence) else
                       f'{confidence:.1%}' + (' · flagged' if low else ''))
    return (f'<div class="hca-item-row"><div class="hca-item-main">'
            f'<div class="hca-item-meta">{html.escape(str(row.questionnaire))} · {html.escape(str(row.item_id))}</div>'
            f'<div class="hca-item-text">{html.escape(str(row.item_text))}</div></div>'
            f'<div class="hca-item-side"><span class="hca-pill">{html.escape(str(row.dimension_label))}</span>'
            f'<span class="hca-item-conf{" hca-item-conf--low" if low else ""}">{confidence_text}</span></div></div>')


def build_dashboard_html(result):
    """Standalone interactive dashboard (HTML) for all results, one section per construct."""
    parts = ['<html><head><meta charset="utf-8"><title>HarmoniCA dashboard</title>'
             '<style>body{font-family:Inter,Arial,sans-serif;color:#1F2430;margin:32px;}h1{margin-bottom:4px;}'
             'h2{color:#A33B5C;margin-top:40px;}p{color:#4B5563;}</style></head><body>'
             '<h1>HarmoniCA item assignments</h1>'
             '<p>Assignment counts and engine confidence. Not instrument equivalence or participant severity.</p>']
    plotly_js = True  # embed plotly.js once, in the first chart only
    for construct in result.construct.unique():
        subset = result[result.construct == construct].copy()
        labels = CATALOG['DIMENSION_DESCRIPTIONS'].get(construct, {})
        subset['dimension_label'] = subset.apply(
            lambda r: labels.get(str(r.dimension).split('.')[0], {}).get('label', r.dimension_label), axis=1)
        parts.append(f'<h2>{html.escape(construct)}</h2><p>{len(subset)} items · '
                     f'{subset.questionnaire.nunique()} questionnaires</p>')
        for chart in (flow_figure(subset), coverage_figure(subset, True), confidence_figure(subset)):
            parts.append(chart.to_html(full_html=False, include_plotlyjs=plotly_js))
            plotly_js = False
    parts.append('</body></html>')
    return ''.join(parts)


def download_bar(key):
    """'Download output' bar shown at the top of each results tab."""
    if not has_result:
        return
    state = st.session_state
    result, result_bytes, manifest = state.result, state.result_bytes, state.manifest
    with st.container(border=True):
        info, csv_col, dash_col = st.columns([2, 1, 1], vertical_alignment='center')
        info.markdown(f'<div class="hca-card-title">Download output</div>'
                      f'<div class="hca-card-sub">{len(result)} harmonized items · {manifest["input_file"]}</div>',
                      unsafe_allow_html=True)
        csv_col.download_button('Harmonized items (CSV)', result_bytes, 'harmonized_items.csv', 'text/csv',
                                type='primary', width='stretch', icon=':material/download:', key=f'dl_csv_{key}')
        dash_col.download_button('Interactive dashboard (HTML)', lambda: build_dashboard_html(result),
                                 'harmonica_dashboard.html', 'text/html', width='stretch',
                                 icon=':material/insert_chart:', key=f'dl_dash_{key}',
                                 help='Flow, coverage and confidence charts for every construct, viewable offline in a browser.')


def run_job(job, df, timeout):
    def on_progress(event):
        if event is not None:
            job['model_done'] += event.get('items', 0)
            if event.get('group_complete'):
                job['groups_done'] += 1
                job['activity'].append((time.monotonic() - job['started'],
                                        f"{event['questionnaire']} ({event['construct']}) complete."))
    try:
        data, result, log = run_harmonica(df, job['force'], timeout, on_progress=on_progress)
        model_keys = {tuple(key) for key in job.get('model_keys', [])}
        if model_keys:
            result_keys = list(map(tuple, result[['construct', 'questionnaire', 'item_id']].astype(str).to_numpy()))
            model_predictions = result.loc[[key in model_keys for key in result_keys]]
            added = append_model_predictions(persistent_inventory_path(), model_predictions, CATALOG['BEST_MODEL'])
            if added:
                job['activity'].append((time.monotonic() - job['started'],
                                        f'{added} new model assignment(s) added to the local inventory.'))
        job['activity'].append((time.monotonic() - job['started'], 'Results combined and ready for review.'))
        job.update(data=data, result=result, log=log, status='done')
    except Exception as exc:
        job.update(error=str(exc), status='error')
    job['elapsed'] = time.monotonic() - job['started']


def start_run(df, context):
    job = dict(context, status='running', started=time.monotonic(), elapsed=0, model_done=0, groups_done=0,
               activity=[(0, f"Run started with {context['n_model']} new items across {context['n_groups']} questionnaires.")])
    if context['n_inventory']:
        job['activity'].append((0, f"{context['n_inventory']} exact inventory matches retained."))
    st.session_state.run_job = job
    threading.Thread(target=run_job, args=(job, df, int(minutes) * 60), daemon=True).start()
    go_to_tab('Harmonization')


def run_view(job, live):
    """Model processing, activity and run cards for a running or finished job."""
    elapsed = time.monotonic() - job['started'] if live else job['elapsed']
    left_col, right_col = st.columns([2.2, 1])
    left_col.markdown(processing_card_html(job['source_name'], job['n_model'], job['model_done'], job['n_inventory'],
                                           job['n_duplicate'], job['n_total'], job['groups_done'], job['n_groups'],
                                           complete=not live), unsafe_allow_html=True)
    left_col.markdown(activity_card_html(job['activity'], live=live), unsafe_allow_html=True)
    right_col.markdown(run_card_html(job['source_name'], job['n_total'], job['n_inventory'], job['n_model'], elapsed,
                                     job['force']), unsafe_allow_html=True)
    if live:
        right_col.markdown(KEEP_OPEN_HTML, unsafe_allow_html=True)


with check:
    if selected.empty:
        st.info('Prepare your items in the **Prepare** tab first.')
    else:
        st.markdown(page_intro_html('Step 2 of 4', 'Check the inventory',
                                    'Existing items can be reused. New items will be sent to the model for harmonization.'),
                    unsafe_allow_html=True)
        st.markdown(stat_cards_html([
            (n_inventory, 'Exact ID matches', 'Already available in the inventory', False),
            (n_duplicate, 'Possible duplicates', 'Under different item IDs', False),
            (n_model, 'New items sent to the model', f'New to the inventory · {n_model / n_total:.1%} of your selection', True),
        ]), unsafe_allow_html=True)
        routing_col, side_col = st.columns([2.2, 1])
        routing_col.markdown(routing_card_html(n_total, n_inventory, n_duplicate, n_model, force), unsafe_allow_html=True)
        with side_col:
            with st.container(border=True):
                st.markdown('<div class="hca-card-title">Run settings</div>', unsafe_allow_html=True)
                st.checkbox('Ignore inventory and always run the model', key='force_rerun', disabled=running)
                st.caption('Every item will be processed by the model in this run.' if force else
                           f'Leave unchecked to reuse exact matches. Only the {n_model} new items will be processed in this run.')
            side_col.markdown(source_card_html(source_name, len(raw) if raw else 0, n_total), unsafe_allow_html=True)
        if has_result and not running:
            st.info('A previous run is kept. Running again will replace its results'
                    + (' and your review decisions.' if st.session_state.get('decisions') else '.'))
        back, note, action = st.columns([1, 2, 1], vertical_alignment='center')
        back.button('Previous: Upload', width='stretch', on_click=go_to_tab, args=('Prepare',), key='back_to_prepare')
        note.markdown(f'<p class="hca-run-note">'
                      + ('A run is in progress' if running else f'{n_model} new item(s) will be processed')
                      + ('' if engine else ' · activate the environment where harmonica --help works') + '</p>',
                      unsafe_allow_html=True)
        context = {'source_name': source_name, 'fingerprint': fingerprint, 'force': force,
                   'n_total': n_total, 'n_inventory': n_inventory, 'n_duplicate': n_duplicate, 'n_model': n_model,
                   'n_groups': n_groups,
                   'model_keys': routed.loc[routed.route != 'inventory', ['construct', 'questionnaire', 'item_id']].astype(str).values.tolist(),
                   'manifest': {'created_utc': datetime.now(timezone.utc).isoformat(), 'input_file': source_name,
                                'input_sha256': hashlib.sha256(raw).hexdigest() if raw else '',
                                'submitted_sha256': hashlib.sha256(selected.to_csv(index=False).encode()).hexdigest(),
                                'selected_items': len(selected), 'constructs': constructs, 'force_rerun': force,
                                'output_rows': len(selected), 'upstream_commit': 'b074bf07970959b4d5021e2cfbeff34a6b012385'}}
        action.button('Run harmonization →', type='primary', disabled=not engine or running, width='stretch',
                      on_click=start_run, args=(selected.copy(), context))

with harmonize:
    if running:
        st.markdown(page_intro_html('Step 3 of 4', 'Harmonizing your items',
                                    f"The model is processing new items. Your {job['n_inventory']} exact inventory matches are already ready."),
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
        back.button('Previous: Inventory check', width='stretch', on_click=go_to_tab, args=('Inventory check',),
                    key='back_to_check')
        note.markdown('<p class="hca-run-note">Available when processing completes · you can browse other tabs meanwhile</p>',
                      unsafe_allow_html=True)
        action.button('View results →', type='primary', width='stretch', disabled=True, key='view_results_wait')
    elif job is not None and job['status'] == 'error':
        st.markdown(page_intro_html('Step 3 of 4', 'Harmonizing your items', 'The last run failed.'), unsafe_allow_html=True)
        st.error('Mapping failed. See the engine details below.' + (' Your earlier results are kept.' if has_result else ''))
        st.code(job['error'], language=None)
        st.button('Previous: Inventory check', on_click=go_to_tab, args=('Inventory check',), key='back_to_check_error')
    elif has_result:
        stale_notice()
        download_bar('harmonize')
        summary = st.session_state.run_summary
        st.markdown(page_intro_html('Step 3 of 4', 'Harmonizing your items',
                                    'Processing is complete. Model suggestions should be reviewed before export.'),
                    unsafe_allow_html=True)
        run_view(summary, live=False)
        back, note, action = st.columns([1, 2, 1], vertical_alignment='center')
        back.button('Previous: Inventory check', width='stretch', on_click=go_to_tab, args=('Inventory check',),
                    key='back_to_check')
        note.markdown('<p class="hca-run-note">Results are ready</p>', unsafe_allow_html=True)
        action.button('View results →', type='primary', width='stretch', on_click=go_to_tab, args=('Visual dashboard',))
    elif selected.empty:
        st.info('Prepare your items in the **Prepare** tab first.')
    else:
        st.markdown(page_intro_html('Step 3 of 4', 'Harmonizing your items',
                                    'Start a run from the Inventory check tab. Progress will appear here.'),
                    unsafe_allow_html=True)
        st.button('Previous: Inventory check', on_click=go_to_tab, args=('Inventory check',), key='back_to_check_idle')

# Ask the browser to confirm before a refresh or close would lose a run or its results.
st.iframe('<script>window.parent.onbeforeunload = '
                + ('function (e) { e.preventDefault(); e.returnValue = ""; return ""; }' if running or has_result else 'null')
                + ';</script>', height=1)


with explore:
    stale_notice()
    if 'result' not in st.session_state:
        st.info('Run harmonization from the **Inventory check** tab to unlock the dashboard.')
    else:
        result=st.session_state.result
        download_bar('explore')
        st.subheader('Questionnaire → dimension landscape')
        a,b=st.columns(2)
        active_construct=a.selectbox('Explore construct',list(result.construct.unique()))
        subset=result[result.construct==active_construct].copy()
        qs=b.multiselect('Show questionnaires',list(subset.questionnaire.unique()),default=list(subset.questionnaire.unique()))
        subset=subset[subset.questionnaire.isin(qs)]
        subset['dimension_label']=subset.apply(lambda r: CATALOG['DIMENSION_DESCRIPTIONS'][active_construct].get(str(r.dimension).split('.')[0],{}).get('label',r.dimension_label),axis=1)
        dim_choices=list(subset.dimension_label.unique())
        dimension_filter=st.multiselect('Dimensions to display',dim_choices,default=dim_choices,key='dashboard_dimensions_'+active_construct)
        subset=subset[subset.dimension_label.isin(dimension_filter)]
        if subset.empty:
            st.info('Select a questionnaire to display its assignments.')
        else:
            numeric=pd.to_numeric(subset.confidence,errors='coerce')
            a,b,c,d=st.columns(4)
            a.metric('Mapped items',len(subset));b.metric('Questionnaires',subset.questionnaire.nunique())
            c.metric('Dimensions represented',subset.dimension_label.nunique());d.metric('Flagged for review',int((numeric<threshold).sum()))
            st.caption('Charts use catalog labels by dimension ID; original output wording is preserved in the inspector and export.')
            st.caption('Hover over flows to see item counts. Each view stays within one construct so dimensions remain comparable.')
            fig=flow_figure(subset)
            st.plotly_chart(fig,width='stretch',key='flow')
            a,b=st.columns([3,2])
            with a:
                st.subheader('Coverage map', anchor=False)
                st.caption('Coverage is item composition, not harmonized participant severity.')
                percent=st.toggle('Show percentage within each questionnaire',value=True)
                st.plotly_chart(coverage_figure(subset,percent),width='stretch',key='coverage')
            with b:
                st.subheader('Assignment confidence', anchor=False)
                st.caption('Inventory confidence may reflect stored expert agreement; full distributions are unavailable for those rows.')
                st.plotly_chart(confidence_figure(subset),width='stretch',key='confidence')
            st.subheader('Compare questionnaires')
            st.plotly_chart(comparison_figure(subset), width='stretch', key='questionnaire_comparison')
            listed=subset.head(6)
            head,jump=st.columns([3,1],vertical_alignment='bottom')
            head.subheader('Items behind the view',anchor=False)
            head.caption('Items matching the filters above' + (f' (showing the first 6 of {len(subset)})' if len(subset)>6 else f' ({len(subset)})') + '.')
            jump.button('Open Item inspector →',width='stretch',on_click=go_to_tab,args=('Item inspector',),key='open_inspector')
            with st.container(border=True):
                st.markdown(''.join(item_row_html(item,threshold) for item in listed.itertuples()),unsafe_allow_html=True)

with review:
    stale_notice()
    st.subheader('Inspect one item at a time')
    if 'result' not in st.session_state:
        st.info('Run mapping to unlock the item inspector.')
    else:
        result=st.session_state.result.reset_index(drop=True)
        download_bar('review')
        if 'decisions' not in st.session_state:
            st.session_state.decisions={}
        a,b,c=st.columns([2,2,1])
        inspect_construct=a.selectbox('Construct',list(result.construct.unique()),key='inspect_construct')
        filtered=result[result.construct==inspect_construct]
        questionnaire=b.selectbox('Questionnaire',list(filtered.questionnaire.unique()),key='inspect_q')
        filtered=filtered[filtered.questionnaire==questionnaire]
        only_flagged=c.checkbox('Flagged only')
        if only_flagged:filtered=filtered[pd.to_numeric(filtered.confidence,errors='coerce')<threshold]
        search=st.text_input('Find item wording or ID')
        if search:filtered=filtered[filtered.item_text.str.contains(search,case=False,regex=False)|filtered.item_id.str.contains(search,case=False,regex=False)]
        if filtered.empty:
            st.info('No items match these filters.')
        else:
            index=st.selectbox('Choose item',list(filtered.index),format_func=lambda i:f'{result.loc[i,"item_id"]} · {result.loc[i,"item_text"][:90]}')
            row=result.loc[index]
            a,b=st.columns([3,2])
            with a:
                with st.container(border=True):
                    st.caption(f'{row.questionnaire} / {row.item_id}')
                    st.markdown('### '+row.item_text)
                    st.write('**Assigned dimension:** '+row.dimension_label)
                    conf=pd.to_numeric(row.confidence,errors='coerce')
                    st.metric('Engine confidence',f'{conf:.1%}' if pd.notna(conf) else 'Unavailable')
                    if pd.notna(conf) and conf<threshold:
                        st.warning('Below your review threshold')
                    else:
                        st.caption('Review in the context of the construct definition.')
                    definition=CATALOG['DIMENSION_DESCRIPTIONS'].get(row.construct,{}).get(str(row.dimension).split('.')[0],{})
                    st.caption(definition.get('description','Definition not found in pinned catalog.'))
            with b:
                distribution=probabilities(row.get('probability_distribution',''))
                if distribution:
                    defs=CATALOG['DIMENSION_DESCRIPTIONS'][row.construct]
                    names=[defs.get(k,{}).get('label','Dimension '+k) for k in distribution]
                    prob_frame=pd.DataFrame({'Dimension':names,'Engine score':list(distribution.values())})
                    chart=decorate(px.bar(prob_frame,x='Engine score',y='Dimension',orientation='h',range_x=[0,1],color='Dimension'))
                    chart.update_layout(showlegend=False)
                    st.plotly_chart(chart,width='stretch',key='item_distribution')
                else:
                    st.info('This inventory assignment has no full probability distribution. No alternatives are fabricated.')
            previous=st.session_state.decisions.get(str(index),{})
            with st.form('decision_'+str(index)):
                a,b=st.columns(2)
                states=['Pending','Accepted','Changed','Uncertain']
                status=a.selectbox('Decision',states,index=states.index(previous.get('review_status','Pending')))
                options=list(dict.fromkeys([row.dimension_label]+[v['label'] for v in CATALOG['DIMENSION_DESCRIPTIONS'][row.construct].values()]))
                current=previous.get('reviewed_dimension',row.dimension_label)
                revised=b.selectbox('Reviewed dimension',options,index=options.index(current) if current in options else 0)
                note=st.text_area('Reason / note',previous.get('review_note',''))
                if st.form_submit_button('Save review decision',type='primary'):
                    if status=='Changed' and revised==row.dimension_label:
                        st.error('Choose a different dimension for a Changed decision.')
                    else:
                        st.session_state.decisions[str(index)]={'review_status':status,'reviewed_dimension':revised,'review_note':note}
                        st.success('Decision saved in this session.')
        st.divider()
        reviewed = reviewed_table(result, st.session_state.decisions)
        count = int((reviewed.review_status != 'Pending').sum())
        st.progress(count/len(reviewed), text=f'{count} / {len(reviewed)} items reviewed')
        st.caption('Review decisions are kept for this session only; they are not included in the downloads.')

with models:
    st.subheader('Models and dimension definitions')
    st.caption('Configuration inspected from julia-pfarr/HarmoniCA at commit b074bf0. This catalog does not prove model weights have downloaded successfully.')
    model_construct=st.selectbox('Browse a construct',CATALOG['CONSTRUCTS'],key='catalog_construct')
    a,b,c=st.columns(3)
    a.metric('Dimensions',len(CATALOG['DIMENSION_DESCRIPTIONS'][model_construct]))
    b.metric('Model strategy',{'ft':'Fine-tuned','ft_knn':'Fine-tuned + kNN','base_knn':'Base encoder + kNN'}[CATALOG['BEST_MODEL'][model_construct]])
    c.metric('Reference items',int((pd.read_csv(Path(__file__).with_name('assets')/'reference_inventory.csv').construct==model_construct).sum()))
    st.link_button('View upstream model repository','https://huggingface.co/'+CATALOG['HF_REPOS'][model_construct])
    if model_construct in CATALOG.get('BASE_MODEL_NAMES',{}):
        st.link_button('View base encoder','https://huggingface.co/'+CATALOG['BASE_MODEL_NAMES'][model_construct])
    for dimension,definition in CATALOG['DIMENSION_DESCRIPTIONS'][model_construct].items():
        with st.container(border=True):
            st.markdown('**'+dimension+' · '+definition['label']+'**')
            st.write(definition['description'])
