from __future__ import annotations

import re
from backend.config import CategoriesConfig
from backend.memory.merchant_keywords import match_merchant_keyword
from backend.models import RawTransaction, TransactionType

_UPI_MARKERS = re.compile(r"\b(UPI|UPL|IMPS)\b", re.I)


def is_upi_transaction(description: str) -> bool:
    return bool(_UPI_MARKERS.search(description))


def should_apply_upi_amount_rules(
    tx: RawTransaction, categories: CategoriesConfig
) -> bool:
    """Apply amount heuristics for UPI debits without a clear merchant keyword match."""
    if tx.type != TransactionType.EXPENSE:
        return False
    rules = categories.upi_amount_rules
    if not rules or not rules.enabled:
        return False
    if not is_upi_transaction(tx.description):
        return False
    if match_merchant_keyword(tx.description, categories, tx.type):
        return False
    return True


def match_upi_amount_rule(
    tx: RawTransaction, categories: CategoriesConfig
) -> str | None:
    if not should_apply_upi_amount_rules(tx, categories):
        return None

    rules = categories.upi_amount_rules
    assert rules is not None
    amount = tx.amount

    if amount in rules.exact_amounts:
        cat = rules.exact_amounts[amount]
        if cat in categories.expense_categories:
            return cat

    for band in rules.ranges:
        lo = band.get("min")
        hi = band.get("max")
        cat = band.get("category", "")
        if cat not in categories.expense_categories:
            continue
        if lo is not None and amount < float(lo):
            continue
        if hi is not None and amount >= float(hi):
            continue
        return cat

    return None
