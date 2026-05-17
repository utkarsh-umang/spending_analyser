from __future__ import annotations

import json

import duckdb

from backend.config import AccountKind, CategoriesConfig
from backend.db import merchant_rules as mr
from backend.llm.client import call_with_tool, load_prompt
from backend.llm.schemas import CLASSIFICATION_TOOL
from backend.memory.merchant_keywords import match_merchant_keyword
from backend.memory.payee_store import PayeeStore
from backend.memory.upi import extract_payee, is_likely_p2p_transfer
from backend.memory.upi_amount_rules import match_upi_amount_rule
from backend.models import (
    ClassifiedTransaction,
    ClassificationBatchResult,
    RawTransaction,
    TransactionType,
    UncertainTransaction,
)


class Classifier:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        categories: CategoriesConfig,
        payee_store: PayeeStore | None = None,
        account_kind: AccountKind = "bank",
    ):
        self.conn = conn
        self.categories = categories
        self.payees = payee_store or PayeeStore()
        self.account_kind = account_kind

    def classify(self, transactions: list[RawTransaction]) -> ClassificationBatchResult:
        rules = mr.fetch_all_rules(self.conn)
        self.payees.reload()
        classified: list[ClassifiedTransaction] = []
        uncertain: list[UncertainTransaction] = []
        needs_llm: list[RawTransaction] = []

        for tx in transactions:
            allowed = self.categories.categories_for_type(tx.type, self.account_kind)
            category = mr.match_rule(tx.description, rules, tx.type, self.categories)
            confidence: str = "rule"

            if not category:
                payee_entry = self.payees.match(tx.description, tx.type, allowed)
                if payee_entry:
                    category = payee_entry.category
                    confidence = "payee"

            if not category:
                category = match_merchant_keyword(
                    tx.description, self.categories, tx.type
                )
                if category:
                    confidence = "keyword"

            if not category:
                category = match_upi_amount_rule(tx, self.categories)
                if category:
                    confidence = "amount_rule"

            if category:
                if not self.categories.is_valid_category(
                    category, tx.type, self.account_kind
                ):
                    category = None
                else:
                    classified.append(
                        ClassifiedTransaction(
                            date=tx.date,
                            description=tx.description,
                            amount=tx.amount,
                            type=tx.type,
                            category=category,
                            confidence=confidence,  # type: ignore[arg-type]
                        )
                    )
                    continue

            if self._should_force_hitl(tx):
                payee = extract_payee(tx.description)
                uncertain.append(
                    UncertainTransaction(
                        date=tx.date,
                        description=tx.description,
                        amount=tx.amount,
                        type=tx.type,
                        reason=self._hitl_reason(tx),
                        payee_name=payee,
                        is_p2p=is_likely_p2p_transfer(tx.description),
                    )
                )
                continue

            needs_llm.append(tx)

        if needs_llm:
            expenses = [t for t in needs_llm if t.type == TransactionType.EXPENSE]
            incomes = [t for t in needs_llm if t.type == TransactionType.INCOME]
            if expenses:
                batch = self._classify_with_llm(expenses, TransactionType.EXPENSE)
                classified.extend(batch.classified)
                uncertain.extend(batch.uncertain)
            if incomes:
                batch = self._classify_with_llm(incomes, TransactionType.INCOME)
                classified.extend(batch.classified)
                uncertain.extend(batch.uncertain)

        return ClassificationBatchResult(classified=classified, uncertain=uncertain)

    def _hitl_reason(self, tx: RawTransaction) -> str:
        if (
            tx.type == TransactionType.INCOME
            and self.account_kind == "credit_card"
        ):
            return (
                "Credit on card statement — confirm bill payment (Credit Card Payment) "
                "or refund/chargeback (Refunds)"
            )
        return "UPI/P2P transfer — payee not in memory; needs your category"

    def _should_force_hitl(self, tx: RawTransaction) -> bool:
        if match_upi_amount_rule(tx, self.categories):
            return False
        if tx.type == TransactionType.EXPENSE and is_likely_p2p_transfer(tx.description):
            return True
        if tx.type == TransactionType.INCOME and self.account_kind == "credit_card":
            return True
        if tx.type == TransactionType.INCOME:
            payee = extract_payee(tx.description)
            if payee and is_likely_p2p_transfer(tx.description):
                allowed = self.categories.categories_for_type(
                    tx.type, self.account_kind
                )
                if not self.payees.match(tx.description, tx.type, allowed):
                    return True
        return False

    def _classify_with_llm(
        self,
        transactions: list[RawTransaction],
        tx_type: TransactionType,
    ) -> ClassificationBatchResult:
        system = load_prompt("classifier")
        allowed = self.categories.categories_for_type(tx_type, self.account_kind)
        tx_payload = [
            {
                "date": t.date,
                "description": t.description,
                "amount": t.amount,
                "type": t.type.value,
            }
            for t in transactions
        ]
        kind = "income (credit)" if tx_type == TransactionType.INCOME else "expense (debit)"
        account_note = ""
        if tx_type == TransactionType.INCOME and self.account_kind == "credit_card":
            account_note = (
                "\nThis batch is from a CREDIT CARD statement. Credits are usually "
                "Credit Card Payment (bill pay) or Refunds — never Salary.\n"
            )
        user_text = (
            f"Classify these {kind} transactions.{account_note}\n"
            f"Use ONLY these categories:\n{json.dumps(allowed)}\n\n"
            f"Rules:\n{self.categories.rules_for_type(tx_type)}\n\n"
            f"Transactions:\n{json.dumps(tx_payload, indent=2)}"
        )
        result = call_with_tool(
            system=system,
            user_content=[{"type": "text", "text": user_text}],
            tool=CLASSIFICATION_TOOL,
        )
        results = result.get("results", [])
        by_description = {t.description: t for t in transactions}

        classified: list[ClassifiedTransaction] = []
        uncertain: list[UncertainTransaction] = []
        seen_descriptions: set[str] = set()

        for item in results:
            desc = item.get("description", "")
            seen_descriptions.add(desc)
            tx = by_description.get(desc)
            if tx is None:
                continue

            if item.get("uncertain") or not item.get("category"):
                uncertain.append(
                    self._uncertain_tx(
                        tx,
                        item.get("reason") or "LLM could not classify",
                    )
                )
                continue

            cat = item["category"]
            if not self.categories.is_valid_category(
                cat, tx.type, self.account_kind
            ):
                uncertain.append(
                    self._uncertain_tx(
                        tx, f"invalid category for {tx.type.value}: {cat}"
                    )
                )
                continue

            if self._needs_income_review(tx, cat):
                uncertain.append(
                    self._uncertain_tx(
                        tx,
                        f"Small credit (₹{tx.amount:,.0f}) — confirm income category",
                    )
                )
                continue

            if self._should_force_hitl(tx):
                uncertain.append(
                    self._uncertain_tx(tx, self._hitl_reason(tx))
                )
                continue

            classified.append(
                ClassifiedTransaction(
                    date=tx.date,
                    description=tx.description,
                    amount=tx.amount,
                    type=tx.type,
                    category=cat,
                    confidence="llm",
                )
            )
            mr.upsert_rule(
                self.conn,
                mr.pattern_from_description(tx.description),
                cat,
                "llm",
            )

        for tx in transactions:
            if tx.description not in seen_descriptions:
                uncertain.append(
                    self._uncertain_tx(tx, "missing from LLM response")
                )

        return ClassificationBatchResult(classified=classified, uncertain=uncertain)

    def _uncertain_tx(self, tx: RawTransaction, reason: str) -> UncertainTransaction:
        payee = extract_payee(tx.description)
        return UncertainTransaction(
            date=tx.date,
            description=tx.description,
            amount=tx.amount,
            type=tx.type,
            reason=reason,
            payee_name=payee,
            is_p2p=is_likely_p2p_transfer(tx.description),
        )

    def _needs_income_review(self, tx: RawTransaction, category: str) -> bool:
        if tx.type != TransactionType.INCOME:
            return False
        if category == "Salary" and tx.amount < self.categories.income_salary_min_amount:
            return True
        return False
