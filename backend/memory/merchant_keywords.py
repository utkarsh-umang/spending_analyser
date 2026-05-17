from __future__ import annotations

from backend.config import CategoriesConfig
from backend.models import TransactionType


def _match_keywords(
    description: str,
    merchants: dict[str, list[str]],
    valid_categories: list[str],
) -> str | None:
    if not merchants:
        return None
    desc_lower = description.lower()
    best: tuple[int, str] | None = None
    for category, keywords in merchants.items():
        if category not in valid_categories:
            continue
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in desc_lower:
                if best is None or len(kw_lower) > best[0]:
                    best = (len(kw_lower), category)
    return best[1] if best else None


def match_merchant_keyword(
    description: str,
    categories: CategoriesConfig,
    tx_type: TransactionType,
) -> str | None:
    if tx_type == TransactionType.EXPENSE:
        return _match_keywords(
            description, categories.category_merchants, categories.expense_categories
        )
    if tx_type == TransactionType.INCOME:
        return _match_keywords(
            description, categories.income_merchants, categories.income_categories
        )
    return None
