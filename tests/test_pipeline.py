import csv
import json
import subprocess
import sys
from zipfile import ZipFile

import pytest

from harmonica.pipeline import generate_pipeline, save_bundle
from harmonica.local_scoring import load_pipeline, score_rows


def make_pipeline():
    assignments = [dict(construct='depression', questionnaire=q, item_id=i,
                        dimension=1, dimension_label='Mood', confidence=0.9)
                   for q, i in [('Q', 'a'), ('Q', 'b'), ('R', 'c')]]
    definitions = [dict(**{k: a[k] for k in ('construct', 'questionnaire', 'item_id')},
                        answer_options='[0, 1, 2]', scoring='[2, 1, 0]' if a['item_id']=='a' else '[0, 1, 2]')
                   for a in assignments]
    return generate_pipeline(assignments, definitions)


def test_generate_download_and_execute_without_site_packages(tmp_path):
    bundle = tmp_path / 'download.zip'
    pipeline = make_pipeline()
    save_bundle(pipeline, bundle)
    with ZipFile(bundle) as archive:
        archive.extractall(tmp_path)
    assert load_pipeline(tmp_path / 'pipeline.json') == pipeline
    responses = tmp_path / 'responses.csv'
    responses.write_text('participant_id,questionnaire,a,b,c\np1,Q,0,2,\np2,Q,2,0,\np3,R,,,0\np4,R,,,2\n')
    result = subprocess.run([sys.executable, '-I', '-S', str(tmp_path/'score_transformation.py'),
                             '--responses', str(responses), '--pipeline', str(tmp_path/'pipeline.json'),
                             '--output', str(tmp_path/'scores.csv')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with open(tmp_path/'scores.csv') as handle:
        rows = list(csv.DictReader(handle))
    assert float(rows[0]['raw_score']) == 4  # reverse scoring is applied
    assert float(rows[0]['proportion_score']) == 1
    assert float(rows[0]['q_cdf_score']) == .75
    assert float(rows[0]['av_cdf_score']) == 1
    assert float(rows[1]['av_cdf_score']) == 0


def test_missing_and_invalid_inputs():
    pipeline = make_pipeline()
    row = dict(participant_id='p', questionnaire='Q', a='0', b='')
    scored = score_rows(pipeline, [row], list(row))[0]
    assert scored['raw_score'] == 2
    assert scored['max_possible_score'] == 2
    assert scored['proportion_score'] == 1
    row['a'] = ''
    assert score_rows(pipeline, [row], list(row))[0]['proportion_score'] is None
    with pytest.raises(ValueError, match='Missing item columns'):
        score_rows(pipeline, [row], ['participant_id', 'questionnaire', 'a'])
    row['a'] = '99'
    with pytest.raises(ValueError, match='invalid answer'):
        score_rows(pipeline, [row], list(row))
    with pytest.raises(ValueError, match='Missing required columns'):
        score_rows(pipeline, [row], ['a', 'b'])


def test_invalid_pipeline_version(tmp_path):
    path = tmp_path/'pipeline.json'
    path.write_text(json.dumps(dict(schema_version=999)))
    with pytest.raises(ValueError, match='schema_version'):
        load_pipeline(path)


def test_scoring_rule_mismatch():
    assignment = dict(construct='sleep', questionnaire='Q', item_id='a', dimension=1,
                      dimension_label='Sleep', confidence=1)
    definition = dict(construct='sleep', questionnaire='Q', item_id='a',
                      answer_options='[0,1]', scoring='[0]')
    with pytest.raises(ValueError, match='lengths differ'):
        generate_pipeline([assignment], [definition])


def test_midpoint_ties_and_average_interpolation():
    from harmonica.local_scoring import percentile, interpolate
    assert percentile([0, 0, 1, 2], 0) == .25
    assert interpolate(.5, [.25, .75], [0, 1]) == .5


def test_unknown_questionnaire_and_duplicate_rows():
    pipeline = make_pipeline()
    row = dict(participant_id='p', questionnaire='unknown', a='0', b='1')
    with pytest.raises(ValueError, match='Unknown questionnaires'):
        score_rows(pipeline, [row], list(row))
    row['questionnaire'] = 'Q'
    with pytest.raises(ValueError, match='duplicate'):
        score_rows(pipeline, [row, row], list(row))


def test_nonfinite_scores_rejected():
    pipeline = make_pipeline()
    pipeline['items'][0]['response_scores']['0'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        score_rows(pipeline, [], ['participant_id', 'questionnaire'])


def test_cli_generates_bundle(tmp_path, monkeypatch):
    from harmonica import harmonize
    from harmonica.harmonica import HarmoniCA
    import pandas as pd
    definitions = tmp_path/'items.csv'
    pd.DataFrame([dict(construct='depression', questionnaire='Q', item_id='a',
                       item_text='Sad', answer_options='[0,1]', scoring='[0,1]')]).to_csv(definitions, index=False)
    inventory = tmp_path/'inventory.csv'
    pd.DataFrame(columns=['questionnaire', 'construct', 'item_id']).to_csv(inventory, index=False)
    monkeypatch.setattr(HarmoniCA, 'harmonize', lambda *args, **kwargs: dict(
        assignments=[dict(item_id='a', item_text='Sad', dimension=1, dimension_label='Mood', confidence=.9)],
        source='model'))
    bundle = tmp_path/'scoring.zip'
    monkeypatch.setattr(sys, 'argv', ['harmonica', '--items', str(definitions),
                                   '--inventory', str(inventory), '--scoring-bundle', str(bundle)])
    harmonize.main()
    with ZipFile(bundle) as archive:
        assert json.loads(archive.read('pipeline.json'))['items'][0]['item_id'] == 'a'
