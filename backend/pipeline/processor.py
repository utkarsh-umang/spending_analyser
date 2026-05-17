from __future__ import annotations

from pathlib import Path

import duckdb

from backend.db import processed_files as pf
from backend.db import transactions as txdb
from backend.models import ClassifiedTransaction
from backend.utils.files import sha256_file


class TransactionProcessor:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def write(
        self,
        transactions: list[ClassifiedTransaction],
        *,
        source_file: Path,
        account_id: str,
        dry_run: bool = False,
        mark_processed: bool = True,
    ) -> tuple[int, int]:
        written = 0
        duplicates = 0
        source_str = str(source_file.resolve())

        for tx in transactions:
            if txdb.exists_duplicate(self.conn, tx.date, tx.description, tx.amount):
                duplicates += 1
                continue
            if not dry_run:
                txdb.insert_transaction(self.conn, tx, account_id, source_str)
            written += 1

        if not dry_run and mark_processed:
            file_hash = sha256_file(source_file)
            pf.mark_processed(self.conn, source_str, file_hash, account_id)

        return written, duplicates
