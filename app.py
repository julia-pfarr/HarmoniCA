"""
Hugging Face Spaces entry point.

Spaces run this file directly (see `app_file` in this repo's README.md Space
metadata). It just makes the `src/` layout importable and launches the same
Gradio app used by the `harmonica-ui` console script — see
src/harmonica/app.py for the actual UI code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from harmonica.app import CSS, THEME, build_app

demo = build_app()

if __name__ == '__main__':
    demo.launch(theme=THEME, css=CSS)
