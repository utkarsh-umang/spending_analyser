from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from backend.config import CategoriesConfig, get_db_path, load_categories_config
from backend.models import TransactionType
from backend.db import merchant_rules as mr
from backend.db.connection import get_connection
from backend.db.schema import init_schema
from backend.memory.payee_store import PayeeStore


def fetch_transactions_by_ids(
    conn: duckdb.DuckDBPyConnection, ids: list[int]
) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    result = conn.execute(
        f"""
        SELECT id, date, description, amount, type, category, account_id, source_file
        FROM transactions
        WHERE id IN ({placeholders})
        ORDER BY date DESC, id DESC
        """,
        ids,
    )
    columns = [d[0] for d in result.description] if result.description else []
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def validate_proposal(
    proposal: dict[str, Any],
    *,
    categories: CategoriesConfig | None = None,
) -> dict[str, Any]:
    """Enrich agent proposal with full transaction rows and validation errors."""
    categories = categories or load_categories_config()
    status = proposal.get("status", "not_found")
    message = proposal.get("message", "")
    ids = [int(i) for i in proposal.get("transaction_ids") or []]
    new_category = proposal.get("new_category")
    new_type = proposal.get("new_type")
    patterns = list(proposal.get("merchant_patterns") or [])
    save_payee = proposal.get("save_payee")

    errors: list[str] = []
    transactions: list[dict[str, Any]] = []

    db = get_db_path(None)
    if db.exists() and ids:
        with get_connection(db, read_only=True) as conn:
            transactions = [
                _serialize_row(r) for r in fetch_transactions_by_ids(conn, ids)
            ]
        found_ids = {t["id"] for t in transactions}
        missing = [i for i in ids if i not in found_ids]
        if missing:
            errors.append(f"Transaction id(s) not in database: {missing}")

    if status in ("ready", "ambiguous") and new_category:
        if not transactions:
            errors.append("No matching transactions loaded.")
        else:
            for tx in transactions:
                tx_type = TransactionType(new_type or tx["type"])
                if not categories.is_valid_category(new_category, tx_type):
                    errors.append(
                        f"'{new_category}' is not valid for type '{tx_type}'."
                    )
                    break

    return {
        "status": status,
        "message": message,
        "transaction_ids": ids,
        "new_category": new_category,
        "new_type": new_type,
        "merchant_patterns": patterns,
        "save_payee": save_payee,
        "transactions": transactions,
        "errors": errors,
        "can_apply": status in ("ready", "ambiguous")
        and bool(transactions)
        and bool(new_category)
        and not errors,
    }


def apply_correction(
    *,
    transaction_ids: list[int],
    new_category: str,
    new_type: str | None = None,
    merchant_patterns: list[str] | None = None,
    save_payee: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Apply a confirmed correction to the database."""
    categories = load_categories_config()
    if not transaction_ids:
        raise ValueError("No transaction ids to update.")

    db = get_db_path(str(db_path) if db_path else None)
    if not db.exists():
        raise FileNotFoundError("Database not found.")

    patterns = list(merchant_patterns or [])
    updated = 0

    with get_connection(db) as conn:
        init_schema(conn)
        rows = fetch_transactions_by_ids(conn, transaction_ids)
        if len(rows) != len(set(transaction_ids)):
            found = {r["id"] for r in rows}
            missing = [i for i in transaction_ids if i not in found]
            raise ValueError(f"Transaction id(s) not found: {missing}")

        for row in rows:
            tx_type = TransactionType(new_type or row["type"])
            if not categories.is_valid_category(new_category, tx_type):
                raise ValueError(
                    f"Invalid category '{new_category}' for type '{tx_type}'."
                )

        for tx_id in transaction_ids:
            if new_type:
                conn.execute(
                    "UPDATE transactions SET category = ?, type = ? WHERE id = ?",
                    [new_category, new_type, tx_id],
                )
            else:
                conn.execute(
                    "UPDATE transactions SET category = ? WHERE id = ?",
                    [new_category, tx_id],
                )
            updated += 1

            row = next(r for r in rows if r["id"] == tx_id)
            desc = str(row["description"])
            if desc and desc.upper() not in [p.upper() for p in patterns]:
                patterns.append(mr.pattern_from_description(desc))

        for p in patterns:
            if p.strip():
                rule = p.strip() if len(p.strip()) <= 40 else p.strip()[:40]
                mr.upsert_rule(conn, rule, new_category, "user")

    payee_saved = None
    if save_payee and save_payee.get("name"):
        store = PayeeStore()
        group = save_payee.get("group", "known")
        if group not in ("known", "family"):
            group = "known"
        entry = store.add_or_update(
            name=str(save_payee["name"]),
            category=new_category,
            group=group,  # type: ignore[arg-type]
            relation=str(save_payee.get("relation") or "merchant"),
            notes="Saved via correction assistant",
            extra_patterns=save_payee.get("extra_patterns") or patterns,
        )
        payee_saved = entry.name

    return {
        "updated_count": updated,
        "transaction_ids": transaction_ids,
        "new_category": new_category,
        "new_type": new_type,
        "merchant_patterns_saved": len(patterns),
        "payee_saved": payee_saved,
    }
