from __future__ import annotations

import re
from pathlib import Path

import duckdb

from backend.config import get_db_path, load_categories_config
from backend.db.connection import get_connection
from backend.db.schema import init_schema
from backend.llm.client import call_agent_loop, load_prompt
from backend.llm.schemas import ANALYZER_TOOL, FINAL_ANSWER_TOOL

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|COPY)\b",
    re.IGNORECASE,
)


def _validate_query(query: str) -> None:
    q = query.strip()
    if not q.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN_SQL.search(q):
        raise ValueError("Query contains forbidden keywords.")


def run_sql(conn: duckdb.DuckDBPyConnection, query: str) -> dict:
    _validate_query(query)
    try:
        result = conn.execute(query)
        columns = [d[0] for d in result.description] if result.description else []
        rows = result.fetchall()
        data = [dict(zip(columns, row)) for row in rows[:500]]
        return {
            "columns": columns,
            "rows": data,
            "row_count": len(rows),
            "truncated": len(rows) > 500,
        }
    except Exception as e:
        return {"error": str(e)}


def run_analyzer(
    question: str,
    *,
    db_path: Path | None = None,
) -> str:
    db = get_db_path(str(db_path) if db_path else None)
    categories = load_categories_config()

    with get_connection(db) as conn:
        init_schema(conn)
        tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        if not tx_count or tx_count[0] == 0:
            return "No transactions in the database. Process statements first with `spending process`."

        income_cats = ", ".join(categories.income_categories)
        expense_cats = ", ".join(categories.expense_categories)

        system = load_prompt("analyzer")
        user_message = (
            f"Question: {question}\n\n"
            f"Income categories (type='income'): {income_cats}\n"
            f"Expense categories (type='expense'): {expense_cats}\n\n"
            "Compute all income and savings figures from transaction data. "
            "Do not assume a fixed monthly salary."
        )

        def tool_handler(name: str, tool_input: dict) -> dict:
            if name == "run_sql":
                query = tool_input.get("query", "")
                return run_sql(conn, query)
            return {"error": f"Unknown tool: {name}"}

        tools = [ANALYZER_TOOL, FINAL_ANSWER_TOOL]
        return call_agent_loop(
            system=system,
            user_message=user_message,
            tools=tools,
            tool_handler=tool_handler,
        )
