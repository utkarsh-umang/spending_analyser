from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb


@contextmanager
def get_connection(
    db_path: Path,
    *,
    read_only: bool = False,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open DuckDB. Use read_only=True for concurrent access while CLI processes."""
    if read_only:
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        conn = duckdb.connect(str(db_path), read_only=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(db_path))
    try:
        yield conn
    finally:
        conn.close()
