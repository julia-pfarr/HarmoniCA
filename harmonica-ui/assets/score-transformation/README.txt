HarmoniCA score transformation
==============================

Turns your participants' item responses into comparable dimension scores, using the
item -> dimension assignments in your harmonized CSV from HarmoniCA. Everything runs
on your computer; nothing is uploaded anywhere.

1. Install (once, Python 3.10 or newer)
   python -m pip install -r requirements.txt

2. Put two files in this folder, next to run_score_transformation.py
   harmonized_items.csv   the file you downloaded from HarmoniCA (Results > Download output)
   responses.csv          your participants' answers (see below)

3. Run
   python run_score_transformation.py

   Other file names or locations: add --harmonized path/to/file.csv and/or
   --responses path/to/file.csv. Results go to a folder called "scores"
   (change it with --output).

responses.csv
-------------
One row per participant. Columns: participant_id, then one column per item, named
exactly like the item IDs in the harmonized CSV (for example BDI_01). Any other
columns (site, age, ...) are carried through to the output.

  participant_id,site,BDI_01,BDI_02,GDS_01
  p001,A,2,0,1
  p002,B,0,3,-9

Item values must be numeric item scores, i.e. values from the item's `scoring` list
(already reverse-scored where needed). Missing: an empty cell or -9
(use --missing-values to change the code).

What you get (in the output folder)
-----------------------------------
dimension_scores.csv        one row per participant x questionnaire x dimension:
                            raw_score, max_possible_score, proportion_score,
                            q_cdf_score (percentile within the questionnaire),
                            av_cdf_score (questionnaire-averaged percentile),
                            n_items_responded / n_items_missing and a reliability flag
dimension_scores_wide.csv   the same scores, one column per dimension
item_dimension_mapping.csv  which items were scored, and their dimension and maximum score
max_dimension_scores.csv    maximum possible score per questionnaire x dimension
cdf_norms.json              the percentile reference built from your sample

Good to know
------------
- Items without answer_options/scoring in the harmonized CSV, and items assigned to
  dimension -1 ("does not fit"), are left out. The run tells you which.
- A dimension score is empty if more than half of its items are missing.
- Percentile scores (q_cdf_score, av_cdf_score) are estimated from your own sample.
  They are sample-dependent, not a guarantee of clinical equivalence.
- Reliability flag: high = 4+ items answered, moderate = 2-3, low = 1, none = 0. It only
  counts items; it is not a psychometric reliability coefficient.
- research_code/ holds the research score transformation, unchanged. You only ever
  run run_score_transformation.py.
