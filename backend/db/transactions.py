from __future__ import annotations

from datetime import datetime

import duckdb

from backend.models import ClassifiedTransaction


def exists_duplicate(
    conn: duckdb.DuckDBPyConnection,
    date: str,
    description: str,
    amount: float,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM transactions
        WHERE date = ? AND description = ? AND amount = ?
        LIMIT 1
        """,
        [date, description, amount],
    ).fetchone()
    return row is not None


def insert_transaction(
    conn: duckdb.DuckDBPyConnection,
    tx: ClassifiedTransaction,
    account_id: str,
    source_file: str,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            id, date, description, amount, type, category,
            account_id, source_file, processed_at
        ) VALUES (
            nextval('transactions_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            tx.date,
            tx.description,
            tx.amount,
            tx.type.value,
            tx.category,
            account_id,
            source_file,
            datetime.utcnow(),
        ],
    )


def count_transactions(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    return int(row[0]) if row else 0
