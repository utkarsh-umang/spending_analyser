# Spending Analyzer — project context

## What this is

A local Python tool that reads bank and credit card statements, extracts every transaction, classifies each one into a spending category, stores everything in a DuckDB database, and then runs a separate analysis pass to generate insights about spending habits over time.

The statements come from multiple banks and credit card issuers. Some are PDFs, some are CSVs. There are roughly four years of data. The goal is a clean, queryable transaction database that can answer questions about month-over-month trends, category breakdowns, biggest expense areas, and savings rate relative to a fixed monthly income.

---

## Folder structure

Statements are organized on disk before the tool runs. The folder layout is:

```
statements/
  bank_name_or_card_name/
    YYYY-MM/
      statement.pdf   (or statement.csv)
```

The tool processes one document at a time and is run manually per document. It does not walk the entire folder tree automatically. The user decides the order and invokes the pipeline per file.

---

## Pipeline overview

The pipeline has two phases that run separately.

**Phase 1: Extraction and storage (run per document)**

Five steps run in sequence for every statement file:

1. `PDFExtractor` reads the document and pulls raw transaction fields.
2. `Validator` checks that each extracted row is well-formed.
3. `Classifier` assigns a spending category to each transaction.
4. The HITL loop runs if the Classifier flagged any transactions as uncertain.
5. `TransactionProcessor` writes the resolved transactions to DuckDB.

**Phase 2: Analysis (run separately, after all documents are processed)**

`AnalyzerAgent` queries the DuckDB database and generates insights. It runs independently of Phase 1 and has no dependency on any particular document. The user runs it whenever they want a report.

---

## Phase 1 components in detail

### PDFExtractor

The extractor's only job is to read the source document and return raw transaction rows. It does not classify, interpret, or infer anything beyond what is on the page.

For PDF files, the raw file is passed to an LLM as a document. For CSV files, the text content is passed directly. The LLM is prompted to return a structured list of transactions with exactly four fields per row: date, description, amount (always a positive number), and transaction type (either "expense" or "income"). Nothing else.

Income transactions include salary credits, interest, refunds, and cashback. Everything else is an expense. Opening and closing balance rows are skipped entirely.

The extractor does not attempt to handle deduplication. It returns whatever is on the document, faithfully.

### Validator

The validator is pure Python with no LLM involvement. It takes the list of raw rows from the extractor and checks each one against a fixed set of rules:

- Date must parse to a valid calendar date and convert cleanly to ISO 8601 (YYYY-MM-DD).
- Amount must be a positive number.
- Transaction type must be exactly "expense" or "income".
- Description must be a non-empty string.

Rows that fail any check are logged to a separate rejection file with the reason for failure. They are never passed downstream. Valid rows continue to the Classifier.

### Classifier

The Classifier is the only component with an agentic loop. Its job is to assign a category to each validated transaction.

Before calling the LLM, the Classifier checks a `merchant_rules` table in DuckDB. This table stores patterns (partial merchant name strings) mapped to categories, sourced either from prior user decisions or from past high-confidence LLM classifications. If a transaction description matches a known pattern, the category is assigned directly without an LLM call.

For transactions that don't match any known pattern, the LLM is called. The LLM receives the transaction description, amount, date, the full list of valid categories, and the user's classification rules. It returns one of two things: a category with high confidence, or an explicit declaration that it cannot decide.

The LLM is instructed never to guess when uncertain. Guessing and marking it high confidence is the failure mode to avoid.

After processing all transactions in a document, the Classifier checks whether any came back as uncertain. If none did, processing continues immediately to the TransactionProcessor. If any did, the HITL loop runs before anything is written to the database.

### HITL loop

The HITL loop is not per-transaction. It is per-document, meaning the pipeline processes the entire document first, collects all uncertain transactions into a batch, and then presents them to the user at once.

For each uncertain transaction, the user sees the date, the full description, the amount, and a numbered list of the available categories. The user types the number corresponding to their choice. The loop accepts the input, assigns the category, and records the decision in the `merchant_rules` table so the same merchant is resolved automatically in the future.

After the user has resolved every uncertain transaction in the batch, control returns to the main pipeline and the TransactionProcessor runs.

The user can also mark a transaction as "skip" if they want to exclude it entirely. Skipped transactions are logged but not written to the database.

### TransactionProcessor

The processor takes the fully resolved transaction list (every row now has a date, description, amount, type, and category) and writes it to DuckDB.

Before writing, it checks for duplicates against existing rows in the database. Deduplication uses a combination of date, description, and amount. If a matching row already exists, the incoming row is skipped and logged. This makes it safe to re-run the pipeline on the same document without corrupting the database.

The processor also records the source filename and the processing timestamp for every row it writes.

After writing transactions, it updates the `processed_files` table with the document path and a hash of the file contents. On future runs, the pipeline can check this table and skip files that have already been processed, if the user chooses to enable that check.

---

## DuckDB tables

There are three tables in the database.

**transactions** stores one row per transaction. Fields include date, description, amount, type (expense or income), category, source filename, and a processing timestamp.

**merchant_rules** stores pattern-to-category mappings. Each row has a description pattern (a partial string), the category it maps to, and the source of the mapping ("user" for HITL decisions, "llm" for high-confidence LLM decisions that the user has not overridden). The Classifier reads this table before every LLM call.

**processed_files** stores one row per document that has been successfully processed. Fields include the file path, a SHA-256 hash of the file contents, and the timestamp of processing. This table supports idempotency.

---

## Categories

Categories are defined by the user in a separate configuration file (not hardcoded in the pipeline). The Classifier reads this file at runtime and injects the full category list and any associated classification rules into the LLM prompt.

The configuration file also contains the user's rules for ambiguous cases: for example, which merchants should always be treated as groceries versus food and dining, or how to handle transactions that could be either travel or transport. These rules are written in plain language and are part of the LLM prompt context.

The number of categories and their names are controlled entirely by this config file. The pipeline makes no assumptions about what categories exist.

---

## Phase 2: AnalyzerAgent

The AnalyzerAgent runs against the completed DuckDB database. It has access to one tool: a function that executes a SQL query against the database and returns the result. It has no access to the raw statement files and no dependency on Phase 1 components.

The agent operates in a loop. Given a user request (for example, "summarize my spending in 2024" or "which month did I spend the most on food"), it plans which queries to run, executes them using the tool, reasons over the results, and either produces a final answer or runs additional queries if the first pass revealed something worth investigating further.

The agent knows the schema of the transactions table and the available categories. It does not need to be told what SQL to write; it generates queries based on what the user asks.

The agent also knows the user's monthly income figure (provided at runtime) so it can calculate savings rate, over-budget months, and income-versus-spend comparisons.

---

## What the user provides at runtime

Before running Phase 1 on a document, the user provides:

- The path to the statement file.
- Their monthly take-home income (used only by the AnalyzerAgent; can be stored once and reused).

The category configuration file is written once and updated manually as needed. It is not a runtime input per document.

---

## What is explicitly out of scope

The tool does not have a web interface or dashboard. All interaction is via the command line.

The tool does not fetch statements automatically from any bank or API. All files are provided by the user.

The tool does not support multi-user access. It is a single-user local tool.

The tool does not send any data to external services other than the Anthropic API for LLM calls. The DuckDB database is a local file.

---

## Key design constraints

The pipeline processes one document at a time by design. There is no batch mode for Phase 1. This keeps error handling simple (a failure on one document doesn't affect others) and makes the HITL loop tractable (the user resolves uncertain transactions per document, not as a giant batch at the end of all files).

The Classifier checks `merchant_rules` before every LLM call. Over time, as the user resolves more uncertain transactions, the number of LLM calls per document should decrease. The system gets faster with use.

All LLM calls use structured output. The extractor, classifier, and analyzer each use explicit output schemas so the downstream Python code never has to parse free-form text.

Rejected rows (from the Validator) and skipped transactions (from the HITL loop) are written to a log file, not silently dropped. The user can inspect this log to catch extraction failures or revisit skip decisions.
