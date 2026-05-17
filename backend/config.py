from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv

from backend.models import TransactionType

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "spending.duckdb"
DEFAULT_LOGS_DIR = PROJECT_ROOT / "data" / "logs"
ACCOUNTS_CONFIG = PROJECT_ROOT / "config" / "accounts.yaml"
CATEGORIES_CONFIG = PROJECT_ROOT / "config" / "categories.yaml"
LEARNED_CATEGORIES_CONFIG = PROJECT_ROOT / "config" / "categories_learned.yaml"

AccountKind = Literal["bank", "credit_card"]


@dataclass
class AccountConfig:
    id: str
    label: str
    path: Path
    kind: AccountKind = "bank"


@dataclass
class CategoriesConfig:
    expense_categories: list[str]
    income_categories: list[str]
    expense_rules: str
    income_rules: str
    income_salary_min_amount: float = 10000.0
    category_merchants: dict[str, list[str]] = field(default_factory=dict)
    income_merchants: dict[str, list[str]] = field(default_factory=dict)
    category_flags: dict[str, dict[str, bool]] = field(default_factory=dict)
    credit_card_income_categories: list[str] = field(default_factory=list)
    learned_expense: set[str] = field(default_factory=set)
    learned_income: set[str] = field(default_factory=set)

    @property
    def categories(self) -> list[str]:
        """All categories (expense + income) for DB / analyzer reference."""
        return self.expense_categories + self.income_categories

    def counts_as_income(self, category: str) -> bool:
        """Whether an income-category credit counts toward total income in analysis."""
        flags = self.category_flags.get(category, {})
        if "counts_as_income" in flags:
            return bool(flags["counts_as_income"])
        return True

    def income_categories_for_analysis(self) -> list[str]:
        return [c for c in self.income_categories if self.counts_as_income(c)]

    def income_excluded_from_totals(self) -> list[str]:
        return [c for c in self.income_categories if not self.counts_as_income(c)]

    def categories_for_type(
        self,
        tx_type: TransactionType,
        account_kind: AccountKind | None = None,
    ) -> list[str]:
        if (
            tx_type == TransactionType.INCOME
            and account_kind == "credit_card"
            and self.credit_card_income_categories
        ):
            seen: set[str] = set()
            ordered: list[str] = []
            for cat in self.credit_card_income_categories:
                if cat not in seen:
                    seen.add(cat)
                    ordered.append(cat)
            for cat in self.income_categories:
                if cat in self.learned_income and cat not in seen:
                    seen.add(cat)
                    ordered.append(cat)
            return ordered
        if tx_type == TransactionType.INCOME:
            return list(self.income_categories)
        return list(self.expense_categories)

    def rules_for_type(self, tx_type: TransactionType) -> str:
        if tx_type == TransactionType.INCOME:
            return self.income_rules
        return self.expense_rules

    def is_valid_category(
        self,
        category: str,
        tx_type: TransactionType,
        account_kind: AccountKind | None = None,
    ) -> bool:
        return category in self.categories_for_type(tx_type, account_kind)

    def add_learned_category(
        self,
        name: str,
        tx_type: TransactionType,
        *,
        counts_as_income: bool | None = None,
    ) -> bool:
        """Append a category to learned config and this in-memory config. Returns False if duplicate."""
        name = name.strip()
        if not name:
            raise ValueError("Category name cannot be empty")

        if tx_type == TransactionType.INCOME:
            if name in self.income_categories:
                return False
            self.income_categories.append(name)
            self.learned_income.add(name)
            key = "income_categories"
            if counts_as_income is not None:
                self.category_flags.setdefault(name, {})["counts_as_income"] = counts_as_income
        else:
            if name in self.expense_categories:
                return False
            self.expense_categories.append(name)
            self.learned_expense.add(name)
            key = "expense_categories"

        _append_learned_to_file(name, key)
        if counts_as_income is not None and tx_type == TransactionType.INCOME:
            _set_learned_flag(name, counts_as_income)
        return True


def _append_learned_to_file(name: str, list_key: str) -> None:
    LEARNED_CATEGORIES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if LEARNED_CATEGORIES_CONFIG.exists():
        raw = yaml.safe_load(LEARNED_CATEGORIES_CONFIG.read_text(encoding="utf-8")) or {}
    else:
        raw = {
            "description": "Categories added during HITL — merged with categories.yaml",
            "expense_categories": [],
            "income_categories": [],
            "category_flags": {},
        }
    items: list[str] = list(raw.get(list_key) or [])
    if name not in items:
        items.append(name)
    raw[list_key] = items
    LEARNED_CATEGORIES_CONFIG.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _set_learned_flag(category: str, counts_as_income: bool) -> None:
    raw = yaml.safe_load(LEARNED_CATEGORIES_CONFIG.read_text(encoding="utf-8")) or {}
    flags = raw.get("category_flags") or {}
    flags.setdefault(category, {})["counts_as_income"] = counts_as_income
    raw["category_flags"] = flags
    LEARNED_CATEGORIES_CONFIG.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _merge_category_flags(
    base: dict[str, dict[str, bool]],
    learned: dict[str, dict[str, bool]],
) -> dict[str, dict[str, bool]]:
    merged = {k: dict(v) for k, v in base.items()}
    for cat, flags in learned.items():
        merged.setdefault(cat, {}).update(flags)
    return merged


def load_categories_config() -> CategoriesConfig:
    with CATEGORIES_CONFIG.open() as f:
        raw = yaml.safe_load(f)

    learned_raw: dict = {}
    if LEARNED_CATEGORIES_CONFIG.exists():
        learned_raw = yaml.safe_load(LEARNED_CATEGORIES_CONFIG.read_text(encoding="utf-8")) or {}

    expense = list(raw.get("expense_categories") or raw.get("categories", []))
    income = list(raw.get("income_categories") or ["Salary", "Refunds", "Other Income"])

    learned_expense = set(learned_raw.get("expense_categories") or [])
    learned_income = set(learned_raw.get("income_categories") or [])

    for cat in learned_expense:
        if cat not in expense:
            expense.append(cat)
    for cat in learned_income:
        if cat not in income:
            income.append(cat)

    base_flags = raw.get("category_flags") or {}
    learned_flags = learned_raw.get("category_flags") or {}
    category_flags = _merge_category_flags(base_flags, learned_flags)

    return CategoriesConfig(
        expense_categories=expense,
        income_categories=income,
        expense_rules=raw.get("expense_rules", raw.get("rules", "")).strip(),
        income_rules=raw.get("income_rules", "").strip(),
        income_salary_min_amount=float(raw.get("income_salary_min_amount", 10000)),
        category_merchants=raw.get("category_merchants") or {},
        income_merchants=raw.get("income_merchants") or {},
        category_flags=category_flags,
        credit_card_income_categories=list(raw.get("credit_card_income_categories") or []),
        learned_expense=learned_expense,
        learned_income=learned_income,
    )


def get_db_path(override: str | None = None) -> Path:
    if override:
        p = Path(override)
        return p if p.is_absolute() else PROJECT_ROOT / p
    env = os.getenv("DB_PATH")
    if env:
        p = Path(env)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DEFAULT_DB_PATH


def get_logs_dir() -> Path:
    DEFAULT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_LOGS_DIR


def _path_suggests_credit_card(*parts: str) -> bool:
    """Folders/paths with 'card' in the name are credit card statements."""
    return any("card" in p.lower() for p in parts if p)


def _parse_account_kind(account_id: str, info: dict) -> AccountKind:
    explicit = info.get("kind") or info.get("account_kind")
    if explicit in ("bank", "credit_card"):
        return explicit  # type: ignore[return-value]
    path = str(info.get("path", ""))
    label = str(info.get("label", ""))
    if _path_suggests_credit_card(account_id, path, label):
        return "credit_card"
    return "bank"


def load_accounts_config() -> tuple[Path, dict[str, AccountConfig]]:
    with ACCOUNTS_CONFIG.open() as f:
        raw = yaml.safe_load(f)
    root = PROJECT_ROOT / raw.get("statements_root", ".")
    accounts: dict[str, AccountConfig] = {}
    for account_id, info in raw.get("accounts", {}).items():
        accounts[account_id] = AccountConfig(
            id=account_id,
            label=info["label"],
            path=(root / info["path"]).resolve(),
            kind=_parse_account_kind(account_id, info),
        )
    return root, accounts


def resolve_account(account_id: str) -> AccountConfig:
    _, accounts = load_accounts_config()
    if account_id not in accounts:
        valid = ", ".join(sorted(accounts))
        raise ValueError(f"Unknown account '{account_id}'. Valid: {valid}")
    return accounts[account_id]


def resolve_statement_path(file_arg: str, account: AccountConfig | None = None) -> Path:
    p = Path(file_arg)
    if p.is_absolute():
        return p.resolve()
    candidate = PROJECT_ROOT / p
    if candidate.exists():
        return candidate.resolve()
    if account is not None:
        candidate = account.path / p
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Statement file not found: {file_arg}")
