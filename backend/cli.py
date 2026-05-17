from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from backend.analysis.agent import run_analyzer
from backend.config import (
    get_db_path,
    load_accounts_config,
    load_categories_config,
    resolve_account,
    resolve_statement_path,
)
from backend.db.connection import get_connection
from backend.db import processed_files as pf
from backend.db.schema import init_schema
from backend.db import merchant_rules as mr
from backend.db import transactions as txdb
from backend.pipeline.orchestrator import run_document
from backend.memory.payee_store import PayeeStore
from backend.utils.files import list_statement_files

app = typer.Typer(
    name="spending",
    help="Spending Analyzer — classify credits (income) and debits (expenses) from statements.",
    no_args_is_help=True,
)
console = Console()


def _db_opt(db_path: Optional[str]) -> Path:
    return get_db_path(db_path)


@app.command("init-db")
def init_db(
    db_path: Optional[str] = typer.Option(None, "--db-path", help="Path to DuckDB file"),
) -> None:
    """Create the database and tables if they do not exist."""
    path = _db_opt(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        init_schema(conn)
    console.print(f"[green]Database ready:[/green] {path}")


@app.command("list")
def list_files(
    account: Optional[str] = typer.Option(
        None, "--account", "-a", help="Account id (e.g. icici_bank)"
    ),
    db_path: Optional[str] = typer.Option(None, "--db-path"),
) -> None:
    """List statement files and processing status."""
    _, accounts = load_accounts_config()
    db = _db_opt(db_path)
    processed: set[str] = set()
    if db.exists():
        with get_connection(db) as conn:
            init_schema(conn)
            processed = pf.list_processed_paths(conn)

    targets = {account: accounts[account]} if account else accounts
    if account and account not in accounts:
        raise typer.BadParameter(f"Unknown account. Valid: {', '.join(sorted(accounts))}")

    table = Table(title="Statement files")
    table.add_column("Account")
    table.add_column("File")
    table.add_column("Status")

    for acc_id, acc in sorted(targets.items()):
        files = list_statement_files(acc.path)
        if not files:
            table.add_row(acc.label, "(no files)", "-")
            continue
        for f in files:
            resolved = str(f.resolve())
            status = "[green]processed[/green]" if resolved in processed else "[dim]pending[/dim]"
            table.add_row(acc_id, f.name, status)

    console.print(table)


@app.command("process")
def process_file(
    file: str = typer.Argument(..., help="Statement file path"),
    account: str = typer.Option(..., "--account", "-a", help="Account id"),
    db_path: Optional[str] = typer.Option(None, "--db-path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Extract and validate only"),
    skip_processed: bool = typer.Option(True, "--skip-processed/--no-skip-processed"),
    force: bool = typer.Option(False, "--force", help="Reprocess even if already done"),
    no_agent: bool = typer.Option(
        False, "--no-agent", help="Skip GPT classification agent; go straight to human HITL"
    ),
) -> None:
    """Run Phase 1 pipeline on a single statement file."""
    if no_agent:
        import os

        os.environ["HITL_AGENT_ENABLED"] = "false"
    acc = resolve_account(account)
    path = resolve_statement_path(file, acc)
    result = run_document(
        file_path=path,
        account_id=account,
        db_path=_db_opt(db_path),
        dry_run=dry_run,
        skip_if_processed=skip_processed,
        force=force,
        console=console,
    )
    _print_result(result)


@app.command("process-account")
def process_account(
    account: str = typer.Argument(..., help="Account id (e.g. sbi_card)"),
    db_path: Optional[str] = typer.Option(None, "--db-path"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    skip_processed: bool = typer.Option(True, "--skip-processed/--no-skip-processed"),
    force: bool = typer.Option(False, "--force"),
    no_agent: bool = typer.Option(
        False, "--no-agent", help="Skip GPT classification agent; go straight to human HITL"
    ),
) -> None:
    """Process all files in an account folder, pausing between each."""
    if no_agent:
        import os

        os.environ["HITL_AGENT_ENABLED"] = "false"
    acc = resolve_account(account)
    files = list_statement_files(acc.path)
    if not files:
        console.print(f"[yellow]No statement files in {acc.path}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold]Account:[/bold] {acc.label} ({len(files)} file(s))")
    db = _db_opt(db_path)

    for i, file_path in enumerate(files, 1):
        console.rule(f"File {i}/{len(files)}: {file_path.name}")
        try:
            result = run_document(
                file_path=file_path,
                account_id=account,
                db_path=db,
                dry_run=dry_run,
                skip_if_processed=skip_processed,
                force=force,
                console=console,
            )
            _print_result(result)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Progress saved for completed files.[/yellow]")
            raise typer.Exit(130)
        except Exception as e:
            console.print(f"[red]Error processing {file_path.name}:[/red] {e}")
            if not typer.confirm("Continue with next file?", default=False):
                raise typer.Exit(1)

        if i < len(files):
            console.input("\n[bold]Press Enter to continue to the next file...[/bold] ")

    with get_connection(db) as conn:
        total = txdb.count_transactions(conn)
    console.print(f"\n[green]Done.[/green] Total transactions in database: {total}")


@app.command("payees")
def list_payees() -> None:
    """Show payee memory (family + known people) used for UPI classification."""
    store = PayeeStore()
    table = Table(title="Payee memory (config/payees/)")
    table.add_column("Group")
    table.add_column("Name")
    table.add_column("Relation")
    table.add_column("Category")
    table.add_column("Patterns")
    for entry in store.list_all():
        table.add_row(
            entry.group,
            entry.name,
            entry.relation,
            entry.category,
            ", ".join(entry.patterns[:5]),
        )
    if not store.list_all():
        console.print("[dim]No payees yet — they are added during HITL.[/dim]")
    else:
        console.print(table)


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8765, "--port", "-p", help="Port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
) -> None:
    """Start the local web UI (status, CSV export, natural-language queries)."""
    import uvicorn

    console.print(f"[green]Web UI:[/green] http://{host}:{port}/")
    uvicorn.run(
        "backend.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command("correct")
def correct_transaction(
    category: str = typer.Option(..., "--category", "-c", help="Correct category name"),
    tx_id: Optional[int] = typer.Option(None, "--id", help="Transaction id"),
    desc: Optional[str] = typer.Option(
        None, "--desc", help="Match description containing this text"
    ),
    date: Optional[str] = typer.Option(None, "--date", help="Optional date YYYY-MM-DD"),
    amount: Optional[float] = typer.Option(None, "--amount", help="Optional amount"),
    patterns: Optional[list[str]] = typer.Option(
        None,
        "--pattern",
        "-p",
        help="Merchant rule pattern (repeat -p for multiple). Defaults to --desc if omitted.",
    ),
    db_path: Optional[str] = typer.Option(None, "--db-path"),
) -> None:
    """Fix category on stored transaction(s) and save merchant rules for future runs."""
    categories = load_categories_config()
    if category not in categories.categories:
        raise typer.BadParameter(
            f"Unknown category '{category}'. Use a name from config/categories.yaml."
        )

    if tx_id is None and not desc:
        raise typer.BadParameter("Provide --id or --desc to identify the transaction(s).")

    rule_patterns: list[str] = list(patterns or [])
    if desc and desc.upper() not in [p.upper() for p in rule_patterns]:
        rule_patterns.append(desc)

    db = _db_opt(db_path)
    with get_connection(db) as conn:
        init_schema(conn)
        n = txdb.update_category(
            conn,
            transaction_id=tx_id,
            description_contains=desc,
            date=date,
            amount=amount,
            category=category,
        )
        for p in rule_patterns:
            rule_pattern = p if len(p) <= 40 else p[:40]
            mr.upsert_rule(conn, rule_pattern, category, "user")

    console.print(
        f"[green]Updated {n} transaction(s) → {category}[/green]"
        + (f"; saved {len(rule_patterns)} merchant rule(s)" if rule_patterns else "")
    )


@app.command("analyze")
def analyze(
    question: str = typer.Argument(..., help="Question about your spending"),
    db_path: Optional[str] = typer.Option(None, "--db-path"),
) -> None:
    """Run Phase 2 analysis agent against the database (income derived from credits)."""
    console.print("[bold]Analyzing...[/bold]")
    answer = run_analyzer(question, db_path=_db_opt(db_path))
    console.print()
    console.print(answer)


def _print_result(result) -> None:
    console.print(
        f"  Extracted: {result.extracted} | Rejected: {result.rejected} | "
        f"Classified: {result.classified} | "
        f"Agent: {result.agent_resolved} | Human HITL: {result.uncertain_resolved} | "
        f"Skipped: {result.skipped} | Written: {result.written} | "
        f"Duplicates skipped: {result.duplicates_skipped}"
        + (" [dry-run]" if result.dry_run else "")
    )


if __name__ == "__main__":
    app()
