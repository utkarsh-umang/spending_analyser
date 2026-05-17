from __future__ import annotations

from datetime import datetime

import duckdb


def is_processed(conn: duckdb.DuckDBPyConnection, file_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM processed_files WHERE file_path = ? LIMIT 1",
        [file_path],
    ).fetchone()
    return row is not None


def get_processed_hash(conn: duckdb.DuckDBPyConnection, file_path: str) -> str | None:
    row = conn.execute(
        "SELECT file_hash FROM processed_files WHERE file_path = ?",
        [file_path],
    ).fetchone()
    return row[0] if row else None


def mark_processed(
    conn: duckdb.DuckDBPyConnection,
    file_path: str,
    file_hash: str,
    account_id: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM processed_files WHERE file_path = ?", [file_path]
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE processed_files
            SET file_hash = ?, account_id = ?, processed_at = ?
            WHERE file_path = ?
            """,
            [file_hash, account_id, datetime.utcnow(), file_path],
        )
    else:
        conn.execute(
            """
            INSERT INTO processed_files (id, file_path, file_hash, account_id, processed_at)
            VALUES (nextval('processed_files_id_seq'), ?, ?, ?, ?)
            """,
            [file_path, file_hash, account_id, datetime.utcnow()],
        )


def list_processed_paths(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("SELECT file_path FROM processed_files").fetchall()
    return {r[0] for r in rows}
