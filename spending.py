#!/usr/bin/env python3
"""CLI launcher — run from project root: python spending.py <command>"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
