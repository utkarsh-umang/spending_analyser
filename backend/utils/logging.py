from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import get_logs_dir


def _log_path(prefix: str) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return get_logs_dir() / f"{prefix}_{ts}.jsonl"


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_rejected(rows: list[dict[str, Any]], source_file: str) -> Path:
    path = _log_path("rejected")
    for row in rows:
        append_jsonl(path, {"source_file": source_file, **row})
    return path


def log_skipped(rows: list[dict[str, Any]], source_file: str) -> Path:
    path = _log_path("skipped")
    for row in rows:
        append_jsonl(path, {"source_file": source_file, **row})
    return path
