from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb


@contextmanager
def get_connection(db_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        yield conn
    finally:
        conn.close()
