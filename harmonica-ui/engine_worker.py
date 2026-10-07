"""Run the real upstream API in an isolated process and inventory copy."""
import json
import os
import sys
from pathlib import Path
import pandas as pd
from backend import PROGRESS_PREFIX, run_items_with_progress

if os.environ.get('HARMONICA_SOURCE_DIR'):
    sys.path.insert(0, os.environ['HARMONICA_SOURCE_DIR'])
from harmonica.harmonica import HarmoniCA

source, output, inventory, models, force = sys.argv[1:]
items = pd.read_csv(source,dtype=str,keep_default_na=False)
engine = HarmoniCA(models_dir=models,inventory_path=inventory)
# Upstream inventory matches IDs without checking wording. Remove stale ID matches
# when the uploaded wording differs, retaining all other reference-pool items.
normalize = lambda text: ' '.join(str(text).strip().lower().split()).strip(' .?!"\'')
for row in items.to_dict('records'):
    matching = (engine.inventory.questionnaire == row['questionnaire']) & (engine.inventory.construct == row['construct']) & (engine.inventory.item_id == row['item_id'])
    stale = matching & (engine.inventory.item_text.map(normalize) != normalize(row['item_text']))
    engine.inventory = engine.inventory.loc[~stale].copy()
rows=[]
for (construct,questionnaire),group in items.groupby(['construct','questionnaire'],sort=False):
    # Text matches under different IDs are not silently reused and never prompt
    # on a hidden terminal; they are processed as new items.
    original_run_model = engine._run_model

    def report_progress(event):
        print(PROGRESS_PREFIX+json.dumps(event), flush=True)

    def run_model_with_item_progress(model_construct, model_items):
        return run_items_with_progress(original_run_model, model_construct, questionnaire,
                                       model_items, report_progress)

    engine._run_model = run_model_with_item_progress
    confirmed_ids = set()
    if 'reuse_match' in group.columns:
        confirmed_ids = set(group.loc[group['reuse_match'].astype(str).str.lower().isin(('true', '1', 'yes')),
                                      'item_id'])
    result=engine.harmonize(questionnaire=questionnaire,construct=construct,items=group[['item_id','item_text']].to_dict('records'),
                            force_rerun=force=='1',
                            confirm_match=lambda user,reference: user['item_id'] in confirmed_ids)
    engine._run_model = original_run_model
    for item in result['assignments']:
        item=dict(item)
        if 'probability_distribution' in item:
            item['probability_distribution']=json.dumps(item['probability_distribution'])
        item.update(construct=construct,questionnaire=questionnaire,source=result['source'])
        rows.append(item)
    print(PROGRESS_PREFIX+json.dumps({
        'construct': construct,
        'questionnaire': questionnaire,
        'items': 0,
        'group_complete': True,
    }), flush=True)
pd.DataFrame(rows).to_csv(output,index=False)
