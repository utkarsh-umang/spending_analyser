from __future__ import annotations

import re

# Common Indian bank / UPI narration patterns
_UPI_PATTERNS = [
    # SBI: UPI/CR/{ref}/{payee}/{bank}/... or UPI/DR/{ref}/{payee}/...
    re.compile(
        r"UPI[-/](?:CR|DR)[-/]\d+[-/](?P<payee>[A-Za-z][A-Za-z0-9\s]{0,20}?)(?:[-/]|@)",
        re.I,
    ),
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


def extract_payee_tokens(description: str) -> list[str]:
    """Payee-like tokens from UPI/IMPS paths (SBI, ICICI, etc.)."""
    desc = description.strip()
    tokens: list[str] = []
    seen: set[str] = set()
    for pattern in _UPI_PATTERNS:
        m = pattern.search(desc)
        if m:
            payee = m.group("payee").strip(" -./")
            payee = re.sub(r"\s+", " ", payee)
            if len(payee) >= 2:
                key = payee.upper()
                if key not in seen:
                    seen.add(key)
                    tokens.append(payee)
    return tokens


def extract_payee(description: str) -> str | None:
    """Best-effort payee name from a transaction description."""
    tokens = extract_payee_tokens(description)
    return tokens[0].upper() if tokens else None


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
