from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from backend.config import PROJECT_ROOT
from backend.models import TransactionType

PAYEES_DIR = PROJECT_ROOT / "config" / "payees"
FAMILY_FILE = PAYEES_DIR / "family.json"
KNOWN_FILE = PAYEES_DIR / "known_people.json"

PayeeGroup = Literal["family", "known"]


@dataclass
class PayeeEntry:
    name: str
    patterns: list[str]
    relation: str
    category: str
    notes: str = ""
    group: PayeeGroup = "known"
    source: str = "user"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def matches(self, description: str) -> bool:
        desc_upper = description.upper()
        for pattern in self.patterns:
            if pattern.upper() in desc_upper:
                return True
        if self.name.upper() in desc_upper:
            return True
        return False


class PayeeStore:
    def __init__(self) -> None:
        self._entries: list[PayeeEntry] = []
        self.reload()

    def reload(self) -> None:
        self._entries = []
        self._entries.extend(self._load_family())
        self._entries.extend(self._load_known())

    def _load_family(self) -> list[PayeeEntry]:
        return self._load_file(FAMILY_FILE, "members", "family")

    def _load_known(self) -> list[PayeeEntry]:
        return self._load_file(KNOWN_FILE, "people", "known")

    def _load_file(self, path: Path, key: str, group: PayeeGroup) -> list[PayeeEntry]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        entries: list[PayeeEntry] = []
        for item in data.get(key, []):
            patterns = list(item.get("patterns") or [])
            name = item.get("name", "").strip()
            if name and name.upper() not in [p.upper() for p in patterns]:
                patterns.insert(0, name.upper())
            entries.append(
                PayeeEntry(
                    name=name,
                    patterns=patterns,
                    relation=item.get("relation", ""),
                    category=item.get("category", "Other"),
                    notes=item.get("notes", ""),
                    group=group,
                    source=item.get("source", "user"),
                    updated_at=item.get("updated_at", ""),
                )
            )
        return entries

    def find_matches(self, description: str) -> list[PayeeEntry]:
        return [e for e in self._entries if e.matches(description)]

    def match(
        self,
        description: str,
        tx_type: TransactionType,
        valid_categories: list[str],
    ) -> PayeeEntry | None:
        """Return best payee match; prefer valid category, then longest pattern."""
        matches = self.find_matches(description)
        if not matches:
            return None

        def best_key(entry: PayeeEntry) -> tuple[int, int]:
            valid = 1 if entry.category in valid_categories else 0
            longest = max((len(p) for p in entry.patterns), default=len(entry.name))
            return (valid, longest)

        return max(matches, key=best_key)

    def add_or_update(
        self,
        *,
        name: str,
        category: str,
        group: PayeeGroup,
        relation: str = "",
        notes: str = "",
        extra_patterns: list[str] | None = None,
    ) -> PayeeEntry:
        patterns = [name.upper()]
        if extra_patterns:
            patterns.extend(p.upper() for p in extra_patterns if p)
        patterns = list(dict.fromkeys(patterns))

        path = FAMILY_FILE if group == "family" else KNOWN_FILE
        key = "members" if group == "family" else "people"
        PAYEES_DIR.mkdir(parents=True, exist_ok=True)

        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"description": "", key: []}

        items: list[dict] = data.get(key, [])
        name_lower = name.strip().lower()
        updated = False
        now = datetime.now(timezone.utc).isoformat()

        for item in items:
            if item.get("name", "").strip().lower() == name_lower:
                existing_patterns = set(p.upper() for p in item.get("patterns", []))
                existing_patterns.update(patterns)
                item["patterns"] = sorted(existing_patterns)
                item["category"] = category
                item["relation"] = relation or item.get("relation", "")
                item["notes"] = notes or item.get("notes", "")
                item["source"] = "user"
                item["updated_at"] = now
                updated = True
                break

        if not updated:
            items.append(
                {
                    "name": name.strip(),
                    "patterns": patterns,
                    "relation": relation,
                    "category": category,
                    "notes": notes,
                    "source": "user",
                    "updated_at": now,
                }
            )

        data[key] = items
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.reload()
        entry = next(e for e in self._entries if e.name.lower() == name_lower)
        return entry

    def list_all(self) -> list[PayeeEntry]:
        return list(self._entries)
