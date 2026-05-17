EXTRACTION_TOOL = {
    "name": "report_transactions",
    "description": "Return all transactions extracted from the statement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Transaction date as YYYY-MM-DD"},
                        "description": {"type": "string"},
                        "amount": {"type": "number", "description": "Positive number"},
                        "type": {
                            "type": "string",
                            "enum": ["expense", "income"],
                        },
                    },
                    "required": ["date", "description", "amount", "type"],
                },
            }
        },
        "required": ["transactions"],
    },
}

CLASSIFICATION_TOOL = {
    "name": "classify_transactions",
    "description": "Classify each transaction or mark as uncertain.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "category": {"type": ["string", "null"]},
                        "uncertain": {"type": "boolean"},
                        "reason": {"type": ["string", "null"]},
                    },
                    "required": ["description", "uncertain"],
                },
            }
        },
        "required": ["results"],
    },
}

ANALYZER_TOOL = {
    "name": "run_sql",
    "description": "Execute a read-only SQL query against the transactions database.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SELECT query only"},
            "reason": {"type": "string", "description": "Why this query is needed"},
        },
        "required": ["query", "reason"],
    },
}

FINAL_ANSWER_TOOL = {
    "name": "final_answer",
    "description": "Provide the final answer to the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
        },
        "required": ["answer"],
    },
}

PROPOSE_CORRECTION_TOOL = {
    "name": "propose_correction",
    "description": "Propose a category/type fix for specific transaction row(s) after searching the database.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ready", "ambiguous", "not_found", "not_a_correction"],
            },
            "message": {
                "type": "string",
                "description": "Short explanation for the user",
            },
            "transaction_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Database ids to update (one or more candidates)",
            },
            "new_category": {"type": ["string", "null"]},
            "new_type": {
                "type": ["string", "null"],
                "enum": ["expense", "income", None],
            },
            "merchant_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Description substrings for merchant_rules",
            },
            "save_payee": {
                "type": ["object", "null"],
                "properties": {
                    "name": {"type": "string"},
                    "group": {"type": "string", "enum": ["known", "family"]},
                    "relation": {"type": "string"},
                    "extra_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "required": ["status", "message", "transaction_ids"],
    },
}
