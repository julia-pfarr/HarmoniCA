"""Run the real upstream API in an isolated process and inventory copy."""
import json
import os
import sys
from pathlib import Path
import pandas as pd

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
    result=engine.harmonize(questionnaire=questionnaire,construct=construct,items=group[['item_id','item_text']].to_dict('records'),force_rerun=force=='1',confirm_match=lambda user,reference:False)
    for item in result['assignments']:
        item=dict(item)
        if 'probability_distribution' in item:
            item['probability_distribution']=json.dumps(item['probability_distribution'])
        item.update(construct=construct,questionnaire=questionnaire,source=result['source'])
        rows.append(item)
    # Progress line read by backend.run_harmonica (prefix must match PROGRESS_PREFIX there)
    print('@@HARMONICA_PROGRESS '+json.dumps({'construct':construct,'questionnaire':questionnaire,'items':len(group)}),flush=True)
pd.DataFrame(rows).to_csv(output,index=False)
