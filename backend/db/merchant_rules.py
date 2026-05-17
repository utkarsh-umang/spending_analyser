from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from backend.config import CategoriesConfig
from backend.models import TransactionType


def fetch_all_rules(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT pattern, category, source FROM merchant_rules ORDER BY LENGTH(pattern) DESC"
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def match_rule(
    description: str,
    rules: list[tuple[str, str, str]],
    tx_type: TransactionType,
    categories: CategoriesConfig,
) -> str | None:
    desc_upper = description.upper()
    for pattern, category, _source in rules:
        if not categories.is_valid_category(category, tx_type):
            continue
        if pattern.upper() in desc_upper:
            return category
    return None


def upsert_rule(
    conn: duckdb.DuckDBPyConnection,
    pattern: str,
    category: str,
    source: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM merchant_rules WHERE pattern = ?", [pattern]
    ).fetchone()
    now = datetime.now(timezone.utc)
    if existing:
        conn.execute(
            "UPDATE merchant_rules SET category = ?, source = ?, created_at = ? WHERE pattern = ?",
            [category, source, now, pattern],
        )
    else:
        conn.execute(
            """
            INSERT INTO merchant_rules (id, pattern, category, source, created_at)
            VALUES (nextval('merchant_rules_id_seq'), ?, ?, ?, ?)
            """,
            [pattern, category, source, now],
        )


def pattern_from_description(description: str, max_len: int = 40) -> str:
    cleaned = " ".join(description.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len]
