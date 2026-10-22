"""Run the real upstream API in an isolated process and inventory copy."""
import json
import os
import sys
from pathlib import Path
import pandas as pd

if os.environ.get('HARMONICA_SOURCE_DIR'):
    sys.path.insert(0, os.environ['HARMONICA_SOURCE_DIR'])
from harmonica.harmonica import HarmoniCA

source, output, inventory, models = sys.argv[1:5]
# Optional answers from the UI: items confirmed as the same item (reused), and exact matches the user said are not the same (re-run)
decisions = json.loads(Path(sys.argv[5]).read_text(encoding='utf-8')) if len(sys.argv) > 5 else {}
same_items = {tuple(key) for key in decisions.get('same_items', [])}
rerun_items = {tuple(key) for key in decisions.get('rerun_items', [])}
items = pd.read_csv(source,dtype=str,keep_default_na=False)
engine = HarmoniCA(models_dir=models,inventory_path=inventory)
# Upstream inventory matches IDs without checking wording. Remove stale ID matches
# when the uploaded wording differs, retaining all other reference-pool items.
normalize = lambda text: ' '.join(str(text).strip().lower().split()).strip(' .?!"\'')
for row in items.to_dict('records'):
    matching = (engine.inventory.questionnaire == row['questionnaire']) & (engine.inventory.construct == row['construct']) & (engine.inventory.item_id == row['item_id'])
    stale = matching & (engine.inventory.item_text.map(normalize) != normalize(row['item_text']))
    engine.inventory = engine.inventory.loc[~stale].copy()
# Exact matches the user said are not the same item must not be reused: drop them from this run's inventory copy.
if rerun_items:
    keep = [(c, q, i) not in rerun_items for c, q, i in zip(engine.inventory.construct, engine.inventory.questionnaire, engine.inventory.item_id)]
    engine.inventory = engine.inventory.loc[keep].copy()
rows=[]
for (construct,questionnaire),group in items.groupby(['construct','questionnaire'],sort=False):
    # Text matches under different IDs never prompt on a hidden terminal: they are reused only
    # when the user confirmed them as the same item, otherwise processed as new items.
    result=engine.harmonize(questionnaire=questionnaire,construct=construct,items=group[['item_id','item_text']].to_dict('records'),
                            confirm_match=lambda user,reference,c=construct,q=questionnaire:(c,q,user['item_id']) in same_items)
    for item in result['assignments']:
        item=dict(item)
        if 'probability_distribution' in item:
            item['probability_distribution']=json.dumps(item['probability_distribution'])
        item.update(construct=construct,questionnaire=questionnaire,source=result['source'])
        rows.append(item)
    # Progress line read by backend.run_harmonica (prefix must match PROGRESS_PREFIX there)
    print('@@HARMONICA_PROGRESS '+json.dumps({'construct':construct,'questionnaire':questionnaire,'items':len(group)}),flush=True)
pd.DataFrame(rows).to_csv(output,index=False)
