from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console

from backend.config import (
    CategoriesConfig,
    get_db_path,
    load_categories_config,
    resolve_account,
)
from backend.db import processed_files as pf
from backend.db.connection import get_connection
from backend.db.schema import init_schema
from backend.models import PipelineResult, TransactionType
from backend.memory.payee_store import PayeeStore
from backend.pipeline.classifier import Classifier
from backend.pipeline.extractor import StatementExtractor
from backend.pipeline.hitl import run_hitl
from backend.pipeline.processor import TransactionProcessor
from backend.pipeline.validator import validate_rows
from backend.utils.files import sha256_file
from backend.utils.logging import log_rejected, log_skipped


def run_document(
    *,
    file_path: Path,
    account_id: str,
    db_path: Path | None = None,
    dry_run: bool = False,
    skip_if_processed: bool = True,
    force: bool = False,
    console: Console | None = None,
) -> PipelineResult:
    console = console or Console()
    db = get_db_path(str(db_path) if db_path else None)
    source_str = str(file_path.resolve())

    with get_connection(db) as conn:
        init_schema(conn)

        if skip_if_processed and not force and pf.is_processed(conn, source_str):
            stored_hash = pf.get_processed_hash(conn, source_str)
            current_hash = sha256_file(file_path)
            if stored_hash == current_hash:
                console.print(f"[yellow]Already processed, skipping:[/yellow] {file_path.name}")
                return PipelineResult(
                    source_file=source_str,
                    account_id=account_id,
                    dry_run=dry_run,
                )

        console.print(f"[bold]Extracting[/bold] {file_path.name}...")
        extractor = StatementExtractor()
        raw_rows = extractor.extract(file_path)

        valid, rejected = validate_rows(raw_rows)
        if rejected:
            log_rejected(rejected, source_str)
            console.print(f"[red]Rejected {len(rejected)} row(s)[/red] — see data/logs/")

        credits = sum(1 for t in valid if t.type == TransactionType.INCOME)
        debits = sum(1 for t in valid if t.type == TransactionType.EXPENSE)
        console.print(
            f"  Valid rows: {len(valid)} "
            f"([green]{credits} credits[/green], [cyan]{debits} debits[/cyan])"
        )

        account = resolve_account(account_id)
        categories: CategoriesConfig = load_categories_config()
        payee_store = PayeeStore()
        classifier = Classifier(
            conn, categories, payee_store, account_kind=account.kind
        )
        batch = classifier.classify(valid)

        uncertain_resolved = 0
        skipped = 0
        if batch.uncertain:
            resolved, skipped_rows = run_hitl(
                conn,
                batch.uncertain,
                categories,
                payee_store,
                console,
                account_kind=account.kind,
            )
            batch.classified.extend(resolved)
            uncertain_resolved = len(resolved)
            skipped = len(skipped_rows)
            if skipped_rows:
                log_skipped(skipped_rows, source_str)

        written = 0
        duplicates = 0
        if not dry_run and batch.classified:
            processor = TransactionProcessor(conn)
            written, duplicates = processor.write(
                batch.classified,
                source_file=file_path,
                account_id=account_id,
                dry_run=False,
            )
        elif dry_run:
            processor = TransactionProcessor(conn)
            written, duplicates = processor.write(
                batch.classified,
                source_file=file_path,
                account_id=account_id,
                dry_run=True,
            )

        result = PipelineResult(
            source_file=source_str,
            account_id=account_id,
            extracted=len(raw_rows),
            rejected=len(rejected),
            classified=len(batch.classified),
            uncertain_resolved=uncertain_resolved,
            skipped=skipped,
            written=written,
            duplicates_skipped=duplicates,
            dry_run=dry_run,
        )
        return result
