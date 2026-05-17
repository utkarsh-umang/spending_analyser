from __future__ import annotations

import csv
import io
import re
from datetime import datetime

_SNO_RE = re.compile(r"^\d+$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def is_icici_bank_csv(text: str) -> bool:
    return (
        "DETAILED STATEMENT" in text
        and "Withdrawal Amount(INR)" in text
        and "Deposit Amount(INR)" in text
        and "Transaction Remarks" in text
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


def _row_cells(line: str) -> list[str]:
    return next(csv.reader(io.StringIO(line)))


def parse_icici_bank_csv(text: str) -> list[dict]:
    """
    Parse ICICI bank “Detailed Statement” CSV exports.

    Rows have a leading empty column. Withdrawal = expense, Deposit = income.
  """
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if "Transaction Remarks" in line and "S No." in line:
            start = i + 1
            break
    else:
        return []

    rows: list[dict] = []
    current: dict | None = None

    for line in lines[start:]:
        if not line.strip():
            continue
        if "Legends Used" in line:
            break

        cells = _row_cells(line)
        if len(cells) < 8:
            continue

        # Leading empty column → S No. at index 1
        sno = cells[1].strip() if len(cells) > 1 else ""
        remarks = cells[5].strip() if len(cells) > 5 else ""
        withdrawal = _parse_amount(cells[6]) if len(cells) > 6 else 0.0
        deposit = _parse_amount(cells[7]) if len(cells) > 7 else 0.0

        if sno and _SNO_RE.match(sno):
            value_date = cells[2].strip() if len(cells) > 2 else ""
            iso = _parse_date(value_date)
            if not iso or not remarks:
                current = None
                continue

            if withdrawal > 0 and deposit > 0:
                amount = max(withdrawal, deposit)
                tx_type = "expense" if withdrawal >= deposit else "income"
            elif withdrawal > 0:
                amount = withdrawal
                tx_type = "expense"
            elif deposit > 0:
                amount = deposit
                tx_type = "income"
            else:
                current = None
                continue

            current = {
                "date": iso,
                "description": remarks,
                "amount": amount,
                "type": tx_type,
            }
            rows.append(current)
            continue

        # Continuation line (wrapped transaction remark)
        if current and remarks and not withdrawal and not deposit:
            current["description"] = f"{current['description']} {remarks}".strip()

    return rows
