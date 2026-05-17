from __future__ import annotations

import re

# Common Indian bank / UPI narration patterns
_UPI_PATTERNS = [
    re.compile(r"UPI[-/](?P<payee>[A-Z0-9][A-Z0-9\s\.\-]{1,40}?)(?:[-/]|@|\d)", re.I),
    re.compile(r"UPI[-/]DR[-/](?P<payee>[A-Z0-9][A-Z0-9\s\.\-]{1,40}?)(?:[-/]|@)", re.I),
    re.compile(r"Paid to (?P<payee>[A-Za-z][A-Za-z\s\.]{1,40})", re.I),
    re.compile(r"Money sent to (?P<payee>[A-Za-z][A-Za-z\s\.]{1,40})", re.I),
    re.compile(r"IMPS/(?:P2A|P2P)?/?[A-Z0-9]*/(?P<payee>[A-Z][A-Z0-9\s\.\-]{1,40})", re.I),
    re.compile(r"NEFT[-/](?P<payee>[A-Z][A-Z0-9\s\.\-]{2,40})", re.I),
    re.compile(r"To:(?P<payee>[A-Za-z][A-Za-z\s\.]{2,40})", re.I),
]

_P2P_MARKERS = re.compile(
    r"\b(UPI|IMPS|P2P|P2A|NEFT|RTGS|Money sent|Paid to|Transfer to)\b",
    re.I,
)

_BUSINESS_MARKERS = re.compile(
    r"\b(PVT|LTD|LIMITED|ENTERPRISES|STORE|SHOP|MART|CAFE|RESTAURANT|"
    r"HOSPITAL|PHARMACY|PAYMENT GATEWAY|PG)\b",
    re.I,
)


def extract_payee(description: str) -> str | None:
    """Best-effort payee name from a transaction description."""
    desc = description.strip()
    for pattern in _UPI_PATTERNS:
        m = pattern.search(desc)
        if m:
            payee = m.group("payee").strip(" -./")
            payee = re.sub(r"\s+", " ", payee)
            if len(payee) >= 2:
                return payee.upper()
    return None


def is_likely_p2p_transfer(description: str) -> bool:
    """True when narration looks like a transfer to a person, not a merchant."""
    if not _P2P_MARKERS.search(description):
        return False
    if _BUSINESS_MARKERS.search(description):
        return False
    payee = extract_payee(description)
    if payee and len(payee.split()) <= 4:
        return True
    if re.search(r"UPI[-/].*@\w+", description, re.I):
        return True
    return bool(_P2P_MARKERS.search(description) and not _BUSINESS_MARKERS.search(description))
