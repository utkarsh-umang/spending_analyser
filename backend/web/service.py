from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import duckdb

from backend.config import get_db_path, load_accounts_config
from backend.db.connection import get_connection
from backend.db import processed_files as pf
from backend.db import transactions as txdb
from backend.utils.files import list_statement_files

TABLE_META: dict[str, dict[str, str]] = {
    "transactions": {
        "label": "Transactions",
        "order_by": "date DESC, id DESC",
    },
    "merchant_rules": {
        "label": "Merchant rules",
        "order_by": "created_at DESC, id DESC",
    },
    "processed_files": {
        "label": "Processed files",
        "order_by": "processed_at DESC, id DESC",
    },
}


def _read_conn(db: Path):
    """Read-only connection so the web UI can run while CLI holds a write lock."""
    return get_connection(db, read_only=True)


def _is_lock_error(exc: BaseException) -> bool:
    return isinstance(exc, duckdb.IOException) and "lock" in str(exc).lower()


def build_status(*, db_path: Path | None = None) -> dict[str, Any]:
    """Statement folders/files with processed vs pending status."""
    _, accounts = load_accounts_config()
    db = get_db_path(str(db_path) if db_path else None)
    processed: set[str] = set()
    transaction_count = 0
    db_locked = False

    if db.exists():
        try:
            with _read_conn(db) as conn:
                processed = pf.list_processed_paths(conn)
                transaction_count = txdb.count_transactions(conn)
        except duckdb.IOException as e:
            if _is_lock_error(e):
                db_locked = True
            else:
                raise

    account_rows: list[dict[str, Any]] = []
    pending_count = 0
    processed_count = 0

    for acc_id, acc in sorted(accounts.items(), key=lambda x: x[1].label):
        files = list_statement_files(acc.path)
        file_rows: list[dict[str, Any]] = []
        for f in files:
            resolved = str(f.resolve())
            status = "processed" if resolved in processed else "pending"
            if status == "processed":
                processed_count += 1
            else:
                pending_count += 1
            file_rows.append(
                {
                    "name": f.name,
                    "path": resolved,
                    "relative_path": str(f.relative_to(acc.path)) if f.is_relative_to(acc.path) else f.name,
                    "status": status,
                }
            )
        account_rows.append(
            {
                "id": acc_id,
                "label": acc.label,
                "path": str(acc.path),
                "kind": acc.kind,
                "file_count": len(file_rows),
                "files": file_rows,
            }
        )

    return {
        "db_path": str(db),
        "db_exists": db.exists(),
        "transaction_count": transaction_count,
        "processed_file_count": processed_count,
        "pending_file_count": pending_count,
        "db_locked": db_locked,
        "accounts": account_rows,
    }


def export_transactions_csv(*, db_path: Path | None = None) -> tuple[bytes, str]:
    """Export all transactions as CSV bytes and a suggested filename."""
    db = get_db_path(str(db_path) if db_path else None)
    if not db.exists():
        raise FileNotFoundError("Database not found. Run init-db and process statements first.")

    buffer = io.StringIO()
    with _read_conn(db) as conn:
        result = conn.execute(
            """
            SELECT date, description, amount, type, category, account_id, source_file, processed_at
            FROM transactions
            ORDER BY date DESC, id DESC
            """
        )
        columns = [d[0] for d in result.description] if result.description else []
        rows = result.fetchall()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        writer.writerows(rows)

    filename = f"transactions_{db.stem}.csv"
    return buffer.getvalue().encode("utf-8"), filename


def list_tables(*, db_path: Path | None = None) -> dict[str, Any]:
    db = get_db_path(str(db_path) if db_path else None)
    tables: list[dict[str, Any]] = []
    if not db.exists():
        return {"db_exists": False, "db_locked": False, "tables": tables}

    try:
        with _read_conn(db) as conn:
            for table_id, meta in TABLE_META.items():
                row = conn.execute(f"SELECT COUNT(*) FROM {table_id}").fetchone()
                count = int(row[0]) if row else 0
                tables.append({"id": table_id, "label": meta["label"], "count": count})
    except duckdb.IOException as e:
        if not _is_lock_error(e):
            raise
        tables = [
            {"id": table_id, "label": meta["label"], "count": None}
            for table_id, meta in TABLE_META.items()
        ]
        return {"db_exists": True, "db_locked": True, "tables": tables}

    return {"db_exists": True, "db_locked": False, "tables": tables}


def fetch_table(
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    db_path: Path | None = None,
) -> dict[str, Any]:
    if table not in TABLE_META:
        raise ValueError(f"Unknown table: {table}")

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    meta = TABLE_META[table]
    db = get_db_path(str(db_path) if db_path else None)
    if not db.exists():
        raise FileNotFoundError("Database not found.")

    with _read_conn(db) as conn:
        total_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        total = int(total_row[0]) if total_row else 0
        result = conn.execute(
            f"SELECT * FROM {table} ORDER BY {meta['order_by']} LIMIT ? OFFSET ?",
            [limit, offset],
        )
        columns = [d[0] for d in result.description] if result.description else []
        rows = [
            {col: _serialize_cell(val) for col, val in zip(columns, row)}
            for row in result.fetchall()
        ]

    return {
        "table": table,
        "label": meta["label"],
        "columns": columns,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _serialize_cell(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
