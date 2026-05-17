from __future__ import annotations

import hashlib
from pathlib import Path

STATEMENT_EXTENSIONS = {".pdf", ".csv"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def list_statement_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in STATEMENT_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())
