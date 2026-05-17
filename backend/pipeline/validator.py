from __future__ import annotations

from datetime import datetime

from backend.models import RawTransaction, TransactionType


def _parse_date(value: str) -> str | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validate_row(row: dict) -> tuple[RawTransaction | None, str | None]:
    raw_date = row.get("date")
    description = row.get("description")
    amount = row.get("amount")
    tx_type = row.get("type")

    if not isinstance(description, str) or not description.strip():
        return None, "description must be a non-empty string"

    iso_date = _parse_date(str(raw_date)) if raw_date is not None else None
    if iso_date is None:
        return None, f"invalid date: {raw_date!r}"

    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        return None, f"invalid amount: {amount!r}"

    if amount_f <= 0:
        return None, "amount must be positive"

    type_str = str(tx_type).lower().strip() if tx_type is not None else ""
    if type_str not in ("expense", "income"):
        return None, f"type must be expense or income, got {tx_type!r}"

    try:
        tx = RawTransaction(
            date=iso_date,
            description=description.strip(),
            amount=amount_f,
            type=TransactionType(type_str),
        )
    except Exception as e:
        return None, str(e)

    return tx, None


def validate_rows(rows: list[dict]) -> tuple[list[RawTransaction], list[dict]]:
    valid: list[RawTransaction] = []
    rejected: list[dict] = []
    for row in rows:
        tx, reason = validate_row(row)
        if tx is None:
            rejected.append({"row": row, "reason": reason})
        else:
            valid.append(tx)
    return valid, rejected
