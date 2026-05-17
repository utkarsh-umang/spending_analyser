from __future__ import annotations

import csv
import io
import re
from datetime import datetime

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_HEADER_MARKER = "Date,Details,Ref No/Cheque No,Debit,Credit,Balance"


def is_sbi_bank_csv(text: str) -> bool:
    return (
        _HEADER_MARKER in text
        and ("State Bank of India" in text or "SBIN" in text)
        and "Savings Account" in text
    )


def _parse_amount(raw: str) -> float:
    raw = raw.strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_date(raw: str) -> str | None:
    raw = raw.strip()
    if not _DATE_RE.match(raw):
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _normalize_description(raw: str) -> str:
    return " ".join(raw.split())


def parse_sbi_bank_csv(text: str) -> list[dict]:
    """
    Parse SBI savings account statement CSV exports.

    Header: Date, Details, Ref No/Cheque No, Debit, Credit, Balance
    Details may span multiple lines inside quoted CSV fields.
    Debit = expense, Credit = income.
    """
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("Date,Details,") and "Debit" in line and "Credit" in line:
            start = i
            break
    else:
        return []

    body = "\n".join(lines[start:])
    reader = csv.reader(io.StringIO(body))
    next(reader, None)  # skip header

    rows: list[dict] = []
    for cells in reader:
        if len(cells) < 6:
            continue

        date_raw = cells[0].strip()
        details = _normalize_description(cells[1])
        debit = _parse_amount(cells[3])
        credit = _parse_amount(cells[4])

        iso = _parse_date(date_raw)
        if not iso or not details:
            continue

        if debit > 0 and credit > 0:
            amount = max(debit, credit)
            tx_type = "expense" if debit >= credit else "income"
        elif debit > 0:
            amount = debit
            tx_type = "expense"
        elif credit > 0:
            amount = credit
            tx_type = "income"
        else:
            continue

        rows.append(
            {
                "date": iso,
                "description": details,
                "amount": amount,
                "type": tx_type,
            }
        )

    return rows
