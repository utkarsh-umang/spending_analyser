from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TransactionType(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"


class RawTransaction(BaseModel):
    date: str
    description: str
    amount: float
    type: TransactionType

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class ClassifiedTransaction(BaseModel):
    date: str
    description: str
    amount: float
    type: TransactionType
    category: str
    confidence: Literal[
        "rule", "llm", "user", "payee", "keyword", "agent", "amount_rule"
    ] = "llm"


class UncertainTransaction(BaseModel):
    date: str
    description: str
    amount: float
    type: TransactionType
    reason: str | None = None
    payee_name: str | None = None
    is_p2p: bool = False


class ExtractionResult(BaseModel):
    transactions: list[RawTransaction] = Field(default_factory=list)


class ClassificationBatchResult(BaseModel):
    classified: list[ClassifiedTransaction] = Field(default_factory=list)
    uncertain: list[UncertainTransaction] = Field(default_factory=list)


class LLMClassificationItem(BaseModel):
    description: str
    category: str | None = None
    uncertain: bool = False
    reason: str | None = None


class LLMClassificationResponse(BaseModel):
    results: list[LLMClassificationItem]


class PipelineResult(BaseModel):
    source_file: str
    account_id: str
    extracted: int = 0
    rejected: int = 0
    classified: int = 0
    agent_resolved: int = 0
    uncertain_resolved: int = 0
    skipped: int = 0
    written: int = 0
    duplicates_skipped: int = 0
    dry_run: bool = False


class ProcessedFileRecord(BaseModel):
    file_path: str
    file_hash: str
    account_id: str
    processed_at: datetime
