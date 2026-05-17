from __future__ import annotations

import base64
from pathlib import Path

from backend.llm.client import call_with_tool, load_prompt
from backend.llm.schemas import EXTRACTION_TOOL
from backend.models import RawTransaction, TransactionType
from backend.pipeline.parsers.icici_bank_csv import is_icici_bank_csv, parse_icici_bank_csv
from backend.pipeline.parsers.icici_card_csv import is_icici_card_csv, parse_icici_card_csv
from backend.pipeline.parsers.sbi_bank_csv import is_sbi_bank_csv, parse_sbi_bank_csv


class StatementExtractor:
    def extract(self, file_path: Path) -> list[dict]:
        suffix = file_path.suffix.lower()
        system = load_prompt("extractor")
        if suffix == ".pdf":
            return self._extract_pdf(file_path, system)
        if suffix == ".csv":
            return self._extract_csv(file_path, system)
        raise ValueError(f"Unsupported file type: {suffix}")

    def _extract_pdf(self, file_path: Path, system: str) -> list[dict]:
        data = base64.standard_b64encode(file_path.read_bytes()).decode("utf-8")
        user_content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": data,
                },
            },
            {
                "type": "text",
                "text": f"Extract all transactions from this statement PDF: {file_path.name}",
            },
        ]
        result = call_with_tool(
            system=system,
            user_content=user_content,
            tool=EXTRACTION_TOOL,
        )
        return result.get("transactions", [])

    def _extract_csv(self, file_path: Path, system: str) -> list[dict]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if is_sbi_bank_csv(text):
            rows = parse_sbi_bank_csv(text)
            if rows:
                return rows
        if is_icici_bank_csv(text):
            rows = parse_icici_bank_csv(text)
            if rows:
                return rows
        if is_icici_card_csv(text):
            rows = parse_icici_card_csv(text)
            if rows:
                return rows
        if len(text) > 200_000:
            text = text[:200_000] + "\n... [truncated]"
        user_content = [
            {
                "type": "text",
                "text": (
                    f"Extract all transactions from this CSV statement: {file_path.name}\n\n"
                    f"```csv\n{text}\n```"
                ),
            },
        ]
        result = call_with_tool(
            system=system,
            user_content=user_content,
            tool=EXTRACTION_TOOL,
        )
        return result.get("transactions", [])


def raw_dicts_to_transactions(rows: list[dict]) -> list[RawTransaction]:
    """Convert validated dicts to RawTransaction if already validated."""
    return [
        RawTransaction(
            date=r["date"],
            description=r["description"],
            amount=float(r["amount"]),
            type=TransactionType(r["type"]),
        )
        for r in rows
    ]
