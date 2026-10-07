"""
Data Harmonizer: lets users submit questionnaire items (typed in or as a CSV)
under the same rules the Harmonize tab applies in "Check inventory".

Layout (each module has one job, only ``tab`` knows about Gradio):

  rules.py            what a valid items file or row is (columns, constructs, empty cells and so on)
  inventory_check.py  compare items with the inventory: already there / duplicate / new
                      (shared with the Harmonize tab, so both give the same answer)
  runner.py           run harmonization over the checked items (shared with the Harmonize tab)
  tab.py              the Gradio tab that wires the above together
"""
from .rules import UPLOAD_COLUMNS

# ``tab.UploaderTab`` is imported directly (``from harmonica.uploader.tab import UploaderTab``)
# so that the rules / inventory check / runner stay usable without Gradio installed.
__all__ = ["UPLOAD_COLUMNS"]
