"""Generate portable scoring bundles from definitions and harmonized assignments."""

import ast
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from .local_scoring import response_key, validate_pipeline


def parse_list(value, field, item_id):
    try:
        parsed = ast.literal_eval(value) if isinstance(value, str) else value
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f'{item_id}: invalid {field} list.') from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f'{item_id}: {field} must be a nonempty list.')
    return parsed


def generate_pipeline(assignments, definitions, missing_threshold=0.5):
    """Inputs are definition records only; participant data is never required."""
    lookup = {}
    for definition in definitions:
        key = tuple(definition[k] for k in ('construct', 'questionnaire', 'item_id'))
        if key in lookup:
            raise ValueError(f'Duplicate item definition: {key}.')
        lookup[key] = definition
    items = []
    for assignment in assignments:
        if int(assignment['dimension']) == -1:
            continue
        key = tuple(assignment[k] for k in ('construct', 'questionnaire', 'item_id'))
        if key not in lookup:
            raise ValueError(f'Missing scoring definition for {key}.')
        definition = lookup[key]
        options = parse_list(definition.get('answer_options'), 'answer_options', key[-1])
        scores = parse_list(definition.get('scoring'), 'scoring', key[-1])
        if len(options) != len(scores):
            raise ValueError(f'{key[-1]}: answer_options and scoring lengths differ.')
        keys = [response_key(v) for v in options]
        if len(set(keys)) != len(keys) or '' in keys:
            raise ValueError(f'{key[-1]}: duplicate or empty answer options.')
        try:
            response_scores = dict(zip(keys, [float(v) for v in scores]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{key[-1]}: scoring values must be numeric.') from exc
        items.append(dict(construct=key[0], questionnaire=key[1], item_id=key[2],
                          dimension=int(assignment['dimension']),
                          dimension_label=assignment['dimension_label'],
                          response_scores=response_scores,
                          source=str(assignment.get('source', 'unspecified')),
                          mapping_confidence=float(assignment['confidence'])))
    return validate_pipeline(dict(schema_version=1, missing_threshold=missing_threshold,
                                  items=items, cdf_reference='own_local_sample'))


def save_bundle(pipeline, path):
    """Write an application-downloadable ZIP with a standalone stdlib runner."""
    validate_pipeline(pipeline)
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('pipeline.json', json.dumps(pipeline, indent=2, allow_nan=False))
        archive.write(Path(__file__).with_name('local_scoring.py'), 'score_transformation.py')
        archive.writestr('requirements.txt', '# Python 3.10+; standard library only. No packages required.\n')
        archive.writestr('README.txt',
            'Extract this ZIP and run:\n'
            'python score_transformation.py --pipeline pipeline.json --responses responses.csv --output scores.csv\n\n'
            'CSV columns: participant_id, questionnaire, and item IDs for questionnaires present.\n'
            'Answers must match the configured raw answer options; do not reverse-score them first.\n'
            'Empty cells are missing. Add --missing-values -9 for a missing sentinel.\n'
            'All computation stays local. No models, network, or package installation required.\n'
            'CDFs use your local sample; they are not fixed population norms.\n'
            'Averaged CDF scores require two questionnaires with at least two valid scores each.\n')
