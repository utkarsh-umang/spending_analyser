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


def update_category(
    conn: duckdb.DuckDBPyConnection,
    *,
    transaction_id: int | None = None,
    description_contains: str | None = None,
    date: str | None = None,
    amount: float | None = None,
    category: str,
) -> int:
    """Update category on matching rows. Returns number of rows updated."""
    if transaction_id is not None:
        before = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE id = ?", [transaction_id]
        ).fetchone()
        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            [category, transaction_id],
        )
        return int(before[0]) if before else 0

    if not description_contains:
        raise ValueError("Provide transaction_id or description_contains")

    where = "description ILIKE ?"
    params: list = [f"%{description_contains}%"]
    if date is not None:
        where += " AND date = ?"
        params.append(date)
    if amount is not None:
        where += " AND amount = ?"
        params.append(amount)

    before = conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE {where}", params
    ).fetchone()
    conn.execute(
        f"UPDATE transactions SET category = ? WHERE {where}",
        [category, *params],
    )
    return int(before[0]) if before else 0
