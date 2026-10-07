Extract this ZIP and run:
python score_transformation.py --pipeline pipeline.json --responses responses.csv --output scores.csv

CSV columns: participant_id, questionnaire, and item IDs for questionnaires present.
Answers must match the configured raw answer options; do not reverse-score them first.
Empty cells are missing. Add --missing-values -9 for a missing sentinel.
All computation stays local. No models, network, or package installation required.
CDFs use your local sample; they are not fixed population norms.
Averaged CDF scores require two questionnaires with at least two valid scores each.
