"""Portable offline scoring runner. Uses only the Python standard library."""

import argparse
import bisect
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def validate_pipeline(pipeline):
    if pipeline.get('schema_version') != 1:
        raise ValueError('Unsupported pipeline schema_version; expected 1.')
    threshold = pipeline.get('missing_threshold')
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('missing_threshold must be between 0 and 1.')
    items = pipeline.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('Pipeline must contain scoring items.')
    seen = set()
    for item in items:
        for key in ('questionnaire', 'construct', 'item_id', 'dimension_label'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f'Invalid item field: {key}.')
        if type(item.get('dimension')) is not int or item['dimension'] < 0:
            raise ValueError('Scored dimensions must be nonnegative integers.')
        key = (item['questionnaire'], item['construct'], item['item_id'])
        if key in seen:
            raise ValueError(f'Duplicate scoring item: {key}.')
        seen.add(key)
        lookup = item.get('response_scores')
        if not isinstance(lookup, dict) or not lookup:
            raise ValueError(f'Missing response scoring rules for {item["item_id"]}.')
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
               for v in lookup.values()):
            raise ValueError('Item scores must be finite and nonnegative.')
        if max(lookup.values()) <= 0:
            raise ValueError(f'Item {item["item_id"]} must have a positive maximum score.')
    return pipeline


def load_pipeline(path):
    with open(path, encoding='utf-8') as handle:
        return validate_pipeline(json.load(handle))


def response_key(value):
    text = str(value).strip()
    try:
        number = float(text)
        if math.isfinite(number):
            return format(number, '.15g')
    except ValueError:
        pass
    return text


def percentile(sorted_values, value):
    left = bisect.bisect_left(sorted_values, value)
    right = bisect.bisect_right(sorted_values, value)
    return (left + 0.5 * (right - left)) / len(sorted_values)


def interpolate(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    right = bisect.bisect_right(xs, x)
    left = right - 1
    return ys[left] + (ys[right] - ys[left]) * (x - xs[left]) / (xs[right] - xs[left])


def score_rows(pipeline, rows, columns, missing_values=()):
    """Score raw answer values; estimate CDFs from this local sample only."""
    validate_pipeline(pipeline)
    required = {'participant_id', 'questionnaire'}
    if not required.issubset(columns):
        raise ValueError(f'Missing required columns: {sorted(required - set(columns))}')
    groups = defaultdict(list)
    for item in pipeline['items']:
        groups[(item['questionnaire'], item['construct'], item['dimension'],
                item['dimension_label'])].append(item)
    known = {key[0] for key in groups}
    present_questionnaires = {row['questionnaire'] for row in rows}
    if present_questionnaires - known:
        raise ValueError(f'Unknown questionnaires: {sorted(present_questionnaires - known)}')
    needed = {item['item_id'] for item in pipeline['items']
              if item['questionnaire'] in present_questionnaires}
    if needed - set(columns):
        raise ValueError(f'Missing item columns: {sorted(needed - set(columns))}')
    missing = {'', *(response_key(v) for v in missing_values)}
    results = []
    seen = set()
    for line, row in enumerate(rows, 2):
        identity = (row['participant_id'], row['questionnaire'])
        if not identity[0] or identity in seen:
            raise ValueError(f'Row {line}: empty or duplicate participant/questionnaire identifier.')
        seen.add(identity)
        for (questionnaire, construct, dimension, label), items in groups.items():
            if questionnaire != row['questionnaire']:
                continue
            answered = []
            for item in items:
                value = response_key(row.get(item['item_id'], ''))
                if value in missing:
                    continue
                lookup = item['response_scores']
                if value not in lookup:
                    raise ValueError(f'Row {line}, {item["item_id"]}: invalid answer {value!r}; '
                                     f'allowed answers: {list(lookup)}')
                answered.append((lookup[value], max(lookup.values())))
            n = len(answered)
            valid = n > 0 and (len(items) - n) / len(items) <= pipeline['missing_threshold']
            raw = sum(v for v, _ in answered) if valid else None
            maximum = sum(v for _, v in answered) if valid else None
            results.append(dict(participant_id=identity[0], questionnaire=questionnaire,
                                construct=construct, dimension=dimension, dimension_label=label,
                                n_items_mapped=len(items), n_items_responded=n,
                                n_items_missing=len(items)-n, raw_score=raw,
                                max_possible_score=maximum,
                                proportion_score=raw/maximum if valid else None,
                                reliability='high' if n >= 4 else 'moderate' if n >= 2
                                else 'low' if n == 1 else 'none',
                                q_cdf_score=None, pooled_cdf_score=None, av_cdf_score=None,
                                cdf_reference='own_local_sample'))
    per_q = defaultdict(list)
    pooled = defaultdict(list)
    for row in results:
        if row['proportion_score'] is not None:
            key = (row['construct'], row['dimension'])
            per_q[(*key, row['questionnaire'])].append(row['proportion_score'])
            pooled[key].append(row['proportion_score'])
    per_q = {k: sorted(v) for k, v in per_q.items()}
    pooled = {k: sorted(v) for k, v in pooled.items()}
    for row in results:
        value = row['proportion_score']
        if value is None:
            continue
        key = (row['construct'], row['dimension'])
        row['q_cdf_score'] = percentile(per_q[(*key, row['questionnaire'])], value)
        row['pooled_cdf_score'] = percentile(pooled[key], value)
        distributions = [v for k, v in per_q.items() if k[:2] == key and len(v) >= 2]
        own = per_q[(*key, row['questionnaire'])]
        if len(distributions) >= 2 and len(own) >= 2:
            grid = sorted({v for distribution in distributions for v in distribution})
            average = [sum(percentile(d, x) for d in distributions)/len(distributions)
                       for x in grid]
            row['av_cdf_score'] = interpolate(row['q_cdf_score'], average, grid)
    return results


def main():
    parser = argparse.ArgumentParser(description='Score participant responses locally, without models or network access.')
    parser.add_argument('--pipeline', default='pipeline.json')
    parser.add_argument('--responses', required=True)
    parser.add_argument('--output', default='dimension_scores.csv')
    parser.add_argument('--missing-values', nargs='*', default=[])
    args = parser.parse_args()
    try:
        pipeline = load_pipeline(args.pipeline)
        with open(args.responses, newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            if len(columns) != len(set(columns)):
                raise ValueError('Duplicate response column names.')
            rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError('Response CSV rows must have the same number of fields as the header.')
        if not rows:
            raise ValueError('Response CSV contains no participant rows.')
        results = score_rows(pipeline, rows, columns, args.missing_values)
        with open(args.output, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    print(f'Saved local scores to {Path(args.output)}')


if __name__ == '__main__':
    main()
