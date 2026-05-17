from __future__ import annotations

import csv
import io
import re
from datetime import datetime

_DATE_RE = re.compile(r"^\d{2}-[A-Z]{3}-\d{2}$", re.I)
_CARD_LINE_RE = re.compile(r"^\d{4}\s+X{4}", re.I)

_PAYMENT_MARKERS = re.compile(
    r"\b(payment received|bbps payment|payment thank|autopay|bill payment)\b",
    re.I,
)
_REFUND_MARKERS = re.compile(r"\b(reversal|refund)\b", re.I)


def is_icici_card_csv(text: str) -> bool:
    return (
        "Transaction Details:" in text
        and "Amount(in Rs)" in text
        and "BillingAmountSign" in text
    )


def parse_icici_card_csv(text: str) -> list[dict]:
    """Parse ICICI credit card export CSV into raw transaction dicts."""
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == '"Transaction Details:"':
            start = i + 1
            break
    else:
        return []

    # Header row after "Transaction Details:"
    body = "\n".join(lines[start:])
    reader = csv.reader(io.StringIO(body))
    rows: list[dict] = []

    for row in reader:
        if not row or len(row) < 6:
            continue
        date_raw = row[0].strip().strip('"')
        if not _DATE_RE.match(date_raw):
            continue
        desc = row[2].strip().strip('"') if len(row) > 2 else ""
        if not desc or _CARD_LINE_RE.match(desc):
            continue

        amount_raw = row[5].strip().strip('"').replace(",", "")
        try:
            signed = float(amount_raw)
        except ValueError:
            continue
        if signed == 0:
            continue

        iso_date = datetime.strptime(date_raw.upper(), "%d-%b-%y").strftime("%Y-%m-%d")
        amount = abs(signed)
        if signed < 0:
            tx_type = "income"
        else:
            tx_type = "expense"

        rows.append(
            {
                "date": iso_date,
                "description": desc,
                "amount": amount,
                "type": tx_type,
            }
        )

    return rows
