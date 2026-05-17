from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from backend.config import get_db_path, load_accounts_config
from backend.db.connection import get_connection
from backend.db.schema import init_schema
from backend.db import processed_files as pf
from backend.db import transactions as txdb
from backend.utils.files import list_statement_files


def build_status(*, db_path: Path | None = None) -> dict[str, Any]:
    """Statement folders/files with processed vs pending status."""
    _, accounts = load_accounts_config()
    db = get_db_path(str(db_path) if db_path else None)
    processed: set[str] = set()
    transaction_count = 0

    if db.exists():
        with get_connection(db) as conn:
            init_schema(conn)
            processed = pf.list_processed_paths(conn)
            transaction_count = txdb.count_transactions(conn)

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
        "accounts": account_rows,
    }


def export_transactions_csv(*, db_path: Path | None = None) -> tuple[bytes, str]:
    """Export all transactions as CSV bytes and a suggested filename."""
    db = get_db_path(str(db_path) if db_path else None)
    if not db.exists():
        raise FileNotFoundError("Database not found. Run init-db and process statements first.")

    buffer = io.StringIO()
    with get_connection(db) as conn:
        init_schema(conn)
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
