# Spending Analyzer

Local app to import bank/credit card statements, classify transactions, and browse or query spending via a web UI and CLI.

You should have received the **full project folder**, including statement CSVs, `config/`, and `data/spending.duckdb` (if processing was already done). Follow the steps below to run it on your machine.

---

## Prerequisites

- **macOS, Linux, or Windows**
- **Python 3.11 or newer** — check with `python3 --version`
- **Internet** — only needed for AI features (see [API keys](#api-keys))

---

## Setup (first time)

Open a terminal in the project folder (the one that contains `pyproject.toml`).

### 1. Create a virtual environment

```bash
cd spending_analyser   # use your actual folder name

python3 -m venv .venv
source .venv/bin/activate
```

On **Windows** (Command Prompt or PowerShell):

```cmd
python -m venv .venv
.venv\Scripts\activate
```

> If the sender included a `.venv` folder, ignore it and create a fresh one on your machine — copied virtualenvs often break across computers.

### 2. Install dependencies

```bash
pip install -e .
```

This installs the `spending` command and all required packages.

### 3. API keys

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

| Variable | Used for |
|----------|----------|
| `ANTHROPIC_API_KEY` | PDF statements and CSV formats without a built-in parser |
| `OPENAI_API_KEY` | Auto-classification of uncertain transactions; web UI “ask” and correction features |

Optional settings (defaults are fine to start):

```env
OPENAI_MODEL=gpt-4o
HITL_AGENT_ENABLED=true
HITL_AGENT_CONFIDENCE_THRESHOLD=0.75
```

**If a `.env` file was already included** in the folder you received, you can use it as-is to get started. For your own API billing and security, replace the keys with yours when you can.

**Without API keys:** you can still open the web UI and browse/export data if `data/spending.duckdb` is present. You cannot process new PDFs, run natural-language analysis, or use AI corrections until keys are set.

---

## Run the web UI

With the virtual environment activated:

```bash
spending serve
```

Open in your browser:

**http://127.0.0.1:8765/**

Stop the server with `Ctrl+C`.

The UI shows transaction tables, export to CSV, status of statement files, and (with `OPENAI_API_KEY`) natural-language questions about your spending.

---

## Process statement files (CLI)

If `data/spending.duckdb` is missing or you want to import new statements, run these from the project root with the venv activated.

### Initialize the database (only if needed)

```bash
spending init-db
```

Skip this if `data/spending.duckdb` already exists in the folder you received.

### See which files are pending

```bash
spending list
```

Shows each account folder and whether each CSV/PDF is already processed.

### Process one file

```bash
spending process "ICICIbank_2025_2026.csv" -a icici_bank
```

Account ids (from `config/accounts.yaml`):

| Account id | Folder |
|------------|--------|
| `icici_bank` | `ICICI bank/` |
| `icici_card` | `ICICI card/` |
| `sbi_bank` | `SBI bank/` |
| `sbi_card` | `SBI card/` |

### Process every file in an account

```bash
spending process-account sbi_bank
```

The tool pauses between files so you can review HITL prompts in the terminal. Press **Enter** to continue to the next file.

### Useful flags

```bash
spending process-account icici_bank --force      # reprocess even if already done
spending process-account sbi_bank --no-agent     # skip OpenAI; only terminal prompts for uncertain rows
```

**Built-in CSV parsers (no Anthropic key needed):** SBI bank, ICICI bank, ICICI card.  
**PDFs and other CSV layouts** require `ANTHROPIC_API_KEY`.

---

## Other CLI commands

```bash
spending analyze "How much did I spend on food in 2025?"
spending payees
spending correct --desc "SWIGGY" --category "Food & Dining"
```

| Command | What it does |
|---------|----------------|
| `spending serve` | Start web UI |
| `spending list` | Statement files + processed status |
| `spending process FILE -a ACCOUNT` | Process one statement |
| `spending process-account ACCOUNT` | Process all files in a folder |
| `spending analyze "…"` | Ask a question about the database (needs OpenAI key) |
| `spending payees` | List saved payee / UPI patterns |
| `spending init-db` | Create empty database |

---

## Project layout

```
spending_analyser/
├── ICICI bank/          # Statement CSVs/PDFs
├── ICICI card/
├── SBI bank/
├── SBI card/
├── backend/             # Application code
├── config/
│   ├── accounts.yaml    # Account → folder mapping
│   ├── categories.yaml  # Spending categories
│   └── payees/          # Known people / merchants for UPI matching
├── data/
│   ├── spending.duckdb  # All classified transactions
│   └── logs/            # Rejected rows, agent logs
├── web/                 # Web UI assets
├── .env.example         # Template for API keys
├── pyproject.toml
└── README.md            # This file
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `spending: command not found` | Activate the venv: `source .venv/bin/activate`, then run `pip install -e .` again |
| `python3: command not found` | Install Python 3.11+ from [python.org](https://www.python.org/downloads/) |
| Web UI is empty | Check that `data/spending.duckdb` exists; run `spending list` and process pending files |
| `Database is locked` | Close other terminals running `spending serve` or `spending process` |
| `ANTHROPIC_API_KEY is not set` | Add key to `.env`, or only process SBI/ICICI CSVs listed above |
| `OPENAI_API_KEY is not set` | Add key to `.env`, or use `--no-agent` and answer prompts in the terminal |
| Pip install fails on Apple Silicon | Try `pip install --upgrade pip` then `pip install -e .` again |

---

## Privacy

This folder contains real bank data, payee names, and a local database. Keep the copy on a trusted machine; do not upload `.env` or statement files to public repos.

For how the pipeline works internally, see [CONTEXT.md](CONTEXT.md).
