"""Streamlit Cloud entrypoint."""
from __future__ import annotations

import runpy
from pathlib import Path


runpy.run_path(str(Path(__file__).parent / "app" / "streamlit_app.py"), run_name="__main__")
