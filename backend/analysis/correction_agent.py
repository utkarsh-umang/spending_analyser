from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.analysis.agent import run_sql
from backend.analysis.corrections import validate_proposal
from backend.config import get_db_path, load_categories_config
from backend.db.connection import get_connection
from backend.llm.client import call_agent_loop, load_prompt
from backend.llm.schemas import ANALYZER_TOOL, PROPOSE_CORRECTION_TOOL


def plan_correction(
    request: str,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Find transaction(s) and propose a category fix from natural language."""
    db = get_db_path(str(db_path) if db_path else None)
    categories = load_categories_config()

    if not db.exists():
        return validate_proposal(
            {
                "status": "not_found",
                "message": "No database yet. Process statements first.",
                "transaction_ids": [],
            },
            categories=categories,
        )

    with get_connection(db, read_only=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        if not count or count[0] == 0:
            return validate_proposal(
                {
                    "status": "not_found",
                    "message": "No transactions in the database yet.",
                    "transaction_ids": [],
                },
                categories=categories,
            )

    expense_cats = ", ".join(categories.expense_categories)
    income_cats = ", ".join(categories.income_categories)
    proposal_holder: dict[str, Any] = {}

    def tool_handler(name: str, tool_input: dict) -> dict:
        if name == "run_sql":
            with get_connection(db, read_only=True) as conn:
                return run_sql(conn, tool_input.get("query", ""))
        if name == "propose_correction":
            proposal_holder.clear()
            proposal_holder.update(tool_input)
            return {"ok": True, "message": "Proposal recorded."}
        return {"error": f"Unknown tool: {name}"}

    system = load_prompt("correction")
    user_message = (
        f"User request: {request.strip()}\n\n"
        f"Valid expense categories: {expense_cats}\n"
        f"Valid income categories: {income_cats}\n\n"
        "Search with SQL, then call propose_correction with the result."
    )

    tools = [ANALYZER_TOOL, PROPOSE_CORRECTION_TOOL]
    call_agent_loop(
        system=system,
        user_message=user_message,
        tools=tools,
        tool_handler=tool_handler,
    )

    if not proposal_holder:
        return validate_proposal(
            {
                "status": "not_found",
                "message": (
                    "Could not build a correction plan. Try being more specific "
                    "(date, amount, merchant, or description text)."
                ),
                "transaction_ids": [],
            },
            categories=categories,
        )

    return validate_proposal(proposal_holder, categories=categories)
