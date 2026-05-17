from __future__ import annotations

import duckdb
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from backend.config import CategoriesConfig
from backend.db import merchant_rules as mr
from backend.memory.payee_store import PayeeStore
from backend.memory.upi import extract_payee, is_likely_p2p_transfer
from backend.models import ClassifiedTransaction, TransactionType, UncertainTransaction


def run_hitl(
    conn: duckdb.DuckDBPyConnection,
    uncertain: list[UncertainTransaction],
    categories: CategoriesConfig,
    payee_store: PayeeStore | None = None,
    console: Console | None = None,
) -> tuple[list[ClassifiedTransaction], list[dict]]:
    console = console or Console()
    payees = payee_store or PayeeStore()
    resolved: list[ClassifiedTransaction] = []
    skipped: list[dict] = []

    if not uncertain:
        return resolved, skipped

    income_count = sum(1 for t in uncertain if t.type == TransactionType.INCOME)
    expense_count = len(uncertain) - income_count
    summary = f"{len(uncertain)} transaction(s) need your input"
    if income_count and expense_count:
        summary += f" ({expense_count} debit, {income_count} credit)"
    elif income_count:
        summary += f" ({income_count} credit)"
    else:
        summary += f" ({expense_count} debit)"

    console.print(Panel(summary, title="Human review", border_style="yellow"))

    for i, tx in enumerate(uncertain, 1):
        cat_list = categories.categories_for_type(tx.type)
        is_income = tx.type == TransactionType.INCOME
        tx_label = "Credit (income)" if is_income else "Debit (expense)"
        payee = tx.payee_name or extract_payee(tx.description)
        is_p2p = tx.is_p2p or is_likely_p2p_transfer(tx.description)

        table = Table(show_header=False, box=None)
        table.add_row("Date", tx.date)
        table.add_row("Description", tx.description)
        table.add_row("Amount", f"₹{tx.amount:,.2f}")
        table.add_row("Direction", tx_label)
        if payee:
            table.add_row("Detected payee", payee)
        if tx.reason:
            table.add_row("Note", tx.reason)
        console.print(Panel(table, title=f"Transaction {i}/{len(uncertain)}"))

        if is_income:
            console.print(
                "[bold]What type of income is this credit?[/bold]"
            )
        elif is_p2p and payee:
            console.print(
                f"[bold]UPI/transfer to {payee}[/bold] — pick category "
                f"(you can save this payee to memory after)"
            )
        else:
            console.print("[bold]Pick a category:[/bold]")

        for idx, cat in enumerate(cat_list, 1):
            console.print(f"  [{idx}] {cat}")
        console.print("  [s] skip this transaction")

        while True:
            choice = console.input("[bold]Your choice (number or s):[/bold] ").strip().lower()
            if choice == "s":
                skipped.append(
                    {
                        "date": tx.date,
                        "description": tx.description,
                        "amount": tx.amount,
                        "type": tx.type.value,
                    }
                )
                console.print("[dim]Skipped.[/dim]")
                break
            try:
                num = int(choice)
                if 1 <= num <= len(cat_list):
                    category = cat_list[num - 1]
                    if (
                        is_income
                        and category == "Salary"
                        and tx.amount < categories.income_salary_min_amount
                    ):
                        console.print(
                            f"[red]Salary not allowed for credits under "
                            f"₹{categories.income_salary_min_amount:,.0f}.[/red]"
                        )
                        continue

                    resolved.append(
                        ClassifiedTransaction(
                            date=tx.date,
                            description=tx.description,
                            amount=tx.amount,
                            type=tx.type,
                            category=category,
                            confidence="user",
                        )
                    )
                    mr.upsert_rule(
                        conn,
                        mr.pattern_from_description(tx.description),
                        category,
                        "user",
                    )
                    console.print(f"[green]Assigned: {category}[/green]")

                    _maybe_remember_payee(
                        console, payees, payee, category, is_p2p, tx.description
                    )
                    break
                console.print("[red]Invalid number. Try again.[/red]")
            except ValueError:
                console.print("[red]Enter a category number or 's' to skip.[/red]")

    return resolved, skipped


def _maybe_remember_payee(
    console: Console,
    payees: PayeeStore,
    payee: str | None,
    category: str,
    is_p2p: bool,
    description: str,
) -> None:
    if not is_p2p:
        remember = console.input(
            "[dim]Save description pattern to merchant rules only (already done). "
            "Remember a payee name for future UPI? [y/N]:[/dim] "
        ).strip().lower()
        if remember != "y":
            return
        payee = payee or console.input("[bold]Payee name to remember:[/bold] ").strip()
        if not payee:
            return
    elif not payee:
        payee = console.input("[bold]Payee name for this transfer:[/bold] ").strip()
        if not payee:
            return
    else:
        save = console.input(
            f"[bold]Remember '{payee}' → {category} for future transfers? [Y/n]:[/bold] "
        ).strip().lower()
        if save == "n":
            return

    console.print("  [1] Family  [2] Known person (roommate/friend)  [3] Other known person")
    group_choice = console.input("[bold]Which list?[/bold] ").strip()
    if group_choice == "1":
        group = "family"
        relation = console.input(
            "[bold]Relation (e.g. brother, mother):[/bold] "
        ).strip()
    elif group_choice in ("2", "3"):
        group = "known"
        relation = console.input(
            "[bold]Relation (e.g. roommate, friend, colleague):[/bold] "
        ).strip()
    else:
        console.print("[dim]Invalid list — not saved to payee memory.[/dim]")
        return

    notes = console.input("[dim]Notes (optional):[/dim] ").strip()
    entry = payees.add_or_update(
        name=payee,
        category=category,
        group=group,  # type: ignore[arg-type]
        relation=relation,
        notes=notes,
        extra_patterns=[payee.upper(), description[:40]],
    )
    file_name = "family.json" if group == "family" else "known_people.json"
    console.print(
        f"[green]Saved to config/payees/{file_name}:[/green] "
        f"{entry.name} → {entry.category}"
    )
