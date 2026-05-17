from __future__ import annotations

import duckdb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    description VARCHAR NOT NULL,
    amount DOUBLE NOT NULL,
    type VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    processed_at TIMESTAMP NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS transactions_id_seq START 1;

CREATE TABLE IF NOT EXISTS merchant_rules (
    id INTEGER PRIMARY KEY,
    pattern VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS merchant_rules_id_seq START 1;

CREATE TABLE IF NOT EXISTS processed_files (
    id INTEGER PRIMARY KEY,
    file_path VARCHAR NOT NULL UNIQUE,
    file_hash VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    processed_at TIMESTAMP NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS processed_files_id_seq START 1;
"""


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(SCHEMA_SQL)
