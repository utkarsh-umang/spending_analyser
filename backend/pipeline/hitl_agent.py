from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import duckdb
from rich.console import Console

from backend.config import AccountKind, CategoriesConfig, get_logs_dir
from backend.db import merchant_rules as mr
from backend.llm.openai_client import (
    AgentClassificationOutput,
    load_prompt,
    run_classification_agent,
)
from backend.memory.payee_store import PayeeStore
from backend.memory.upi import extract_payee
from backend.models import ClassifiedTransaction, TransactionType, UncertainTransaction
from backend.tools.web_search import web_search


def hitl_agent_enabled() -> bool:
    if os.getenv("HITL_AGENT_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    return bool(os.getenv("OPENAI_API_KEY"))


def confidence_threshold() -> float:
    return float(os.getenv("HITL_AGENT_CONFIDENCE_THRESHOLD", "0.75"))


def _tool_handler(name: str, args: dict[str, Any]) -> str:
    if name == "web_search":
        result = web_search(args.get("query", ""))
        return json.dumps(result, default=str)
    return json.dumps({"error": f"Unknown tool: {name}"})


def _log_agent_decision(record: dict[str, Any]) -> None:
    path = get_logs_dir() / "agent_classification.jsonl"
    record["logged_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _apply_learning(
    conn: duckdb.DuckDBPyConnection,
    output: AgentClassificationOutput,
    tx: UncertainTransaction,
    payee_store: PayeeStore,
) -> None:
    pattern = (output.merchant_pattern or "").strip()
    if not pattern:
        pattern = mr.pattern_from_description(tx.description)
    if len(pattern) >= 3:
        mr.upsert_rule(conn, pattern.upper() if pattern.isascii() else pattern, output.category, "agent")

    payee = output.merchant_name or tx.payee_name or extract_payee(tx.description)
    if payee and tx.is_p2p and output.confidence >= 0.85:
        try:
            payee_store.add_or_update(
                name=payee,
                category=output.category,
                group="known",
                relation="inferred",
                notes=output.learning_notes or "Auto-saved by classification agent",
                extra_patterns=[payee.upper(), pattern[:40] if pattern else payee.upper()],
            )
        except Exception:
            pass


def _classify_one(
    tx: UncertainTransaction,
    categories: CategoriesConfig,
    account_kind: AccountKind,
    account_id: str,
) -> AgentClassificationOutput | None:
    allowed = categories.categories_for_type(tx.type, account_kind)
    kind = "credit (income)" if tx.type == TransactionType.INCOME else "debit (expense)"
    account_ctx = (
        "CREDIT CARD statement — credits are usually Credit Card Payment (bill pay) "
        "or Refunds/Cashback, not Salary."
        if account_kind == "credit_card" and tx.type == TransactionType.INCOME
        else f"Account kind: {account_kind}"
    )
    user_message = (
        f"Classify this {kind} transaction.\n"
        f"{account_ctx}\n"
        f"Account id: {account_id}\n"
        f"Date: {tx.date}\n"
        f"Amount: ₹{tx.amount:,.2f}\n"
        f"Description: {tx.description}\n"
        f"Prior note: {tx.reason or 'none'}\n"
        f"Detected payee: {tx.payee_name or 'none'}\n"
        f"P2P transfer: {tx.is_p2p}\n\n"
        f"Allowed categories (pick exactly one):\n{json.dumps(allowed, indent=2)}\n\n"
        f"Classification rules:\n{categories.rules_for_type(tx.type)}\n\n"
        f"Confidence threshold for auto-accept: {confidence_threshold():.2f}\n"
        "Use web_search if needed, then submit_classification."
    )
    return run_classification_agent(
        system=load_prompt("hitl_agent"),
        user_message=user_message,
        tool_handler=_tool_handler,
    )


def run_hitl_agent(
    conn: duckdb.DuckDBPyConnection,
    uncertain: list[UncertainTransaction],
    categories: CategoriesConfig,
    payee_store: PayeeStore,
    *,
    account_kind: AccountKind,
    account_id: str,
    console: Console | None = None,
) -> tuple[list[ClassifiedTransaction], list[UncertainTransaction]]:
    """
    Attempt GPT + web search classification. High-confidence results are auto-applied
    with merchant_rules learning; the rest are returned for human HITL.
    """
    console = console or Console()
    if not uncertain or not hitl_agent_enabled():
        return [], list(uncertain)

    threshold = confidence_threshold()
    console.print(
        f"[cyan]Classification agent[/cyan] reviewing {len(uncertain)} transaction(s) "
        f"(auto-accept at ≥{threshold:.0%} confidence)..."
    )

    resolved: list[ClassifiedTransaction] = []
    still_uncertain: list[UncertainTransaction] = []

    for i, tx in enumerate(uncertain, 1):
        console.print(
            f"  [dim]({i}/{len(uncertain)})[/dim] {tx.date} ₹{tx.amount:,.0f} — "
            f"{tx.description[:50]}{'…' if len(tx.description) > 50 else ''}"
        )
        try:
            output = _classify_one(tx, categories, account_kind, account_id)
        except Exception as e:
            console.print(f"    [red]Agent error:[/red] {e}")
            still_uncertain.append(tx)
            continue

        if output is None:
            console.print("    [yellow]No classification submitted → human review[/yellow]")
            still_uncertain.append(tx)
            _log_agent_decision(
                {
                    "description": tx.description,
                    "status": "no_submit",
                    "account_id": account_id,
                }
            )
            continue

        allowed = categories.categories_for_type(tx.type, account_kind)
        valid_cat = output.category in allowed or output.category in categories.categories
        log_record: dict[str, Any] = {
            "description": tx.description,
            "date": tx.date,
            "amount": tx.amount,
            "type": tx.type.value,
            "category": output.category,
            "confidence": output.confidence,
            "merchant_name": output.merchant_name,
            "reasoning": output.reasoning,
            "learning_notes": output.learning_notes,
            "merchant_pattern": output.merchant_pattern,
            "account_id": account_id,
        }

        if not valid_cat:
            console.print(
                f"    [yellow]Invalid category '{output.category}' → human review[/yellow]"
            )
            log_record["status"] = "invalid_category"
            _log_agent_decision(log_record)
            still_uncertain.append(
                UncertainTransaction(
                    date=tx.date,
                    description=tx.description,
                    amount=tx.amount,
                    type=tx.type,
                    reason=f"Agent suggested invalid category: {output.category}",
                    payee_name=tx.payee_name,
                    is_p2p=tx.is_p2p,
                )
            )
            continue

        if output.confidence < threshold:
            console.print(
                f"    [yellow]Low confidence {output.confidence:.0%} "
                f"({output.category}) → human review[/yellow]"
            )
            log_record["status"] = "below_threshold"
            _log_agent_decision(log_record)
            still_uncertain.append(
                UncertainTransaction(
                    date=tx.date,
                    description=tx.description,
                    amount=tx.amount,
                    type=tx.type,
                    reason=(
                        f"Agent {output.confidence:.0%}: {output.category} — "
                        f"{output.reasoning}"
                    ),
                    payee_name=output.merchant_name or tx.payee_name,
                    is_p2p=tx.is_p2p,
                )
            )
            continue

        _apply_learning(conn, output, tx, payee_store)
        log_record["status"] = "accepted"
        _log_agent_decision(log_record)
        console.print(
            f"    [green]✓ {output.category}[/green] "
            f"({output.confidence:.0%}) — {output.merchant_name or 'merchant n/a'}"
        )
        resolved.append(
            ClassifiedTransaction(
                date=tx.date,
                description=tx.description,
                amount=tx.amount,
                type=tx.type,
                category=output.category,
                confidence="agent",
            )
        )

    console.print(
        f"[cyan]Agent:[/cyan] {len(resolved)} auto-classified, "
        f"{len(still_uncertain)} need human review"
    )
    return resolved, still_uncertain
