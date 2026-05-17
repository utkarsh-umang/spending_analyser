from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.analysis.agent import run_analyzer
from backend.analysis.correction_agent import plan_correction
from backend.analysis.corrections import apply_correction
from backend.config import get_db_path
from backend.web.service import (
    TABLE_META,
    build_status,
    export_transactions_csv,
    fetch_table,
    list_tables,
)

WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "web"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Spending Analyzer", docs_url="/api/docs", redoc_url=None)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class AnalyzeResponse(BaseModel):
    answer: str


class CorrectionPlanRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=4000)


class SavePayeeModel(BaseModel):
    name: str
    group: str = "known"
    relation: str = "merchant"
    extra_patterns: list[str] = Field(default_factory=list)


class CorrectionApplyRequest(BaseModel):
    transaction_ids: list[int] = Field(..., min_length=1)
    new_category: str = Field(..., min_length=1)
    new_type: str | None = None
    merchant_patterns: list[str] = Field(default_factory=list)
    save_payee: SavePayeeModel | None = None


def _db_locked_response(exc: duckdb.IOException) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Database is in use by another process (e.g. statement processing). "
            "Wait for it to finish, or stop the CLI job, then refresh."
        ),
    )


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_ROOT / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="web/index.html not found")
    return FileResponse(index_path)


@app.get("/api/status")
def api_status() -> dict:
    return build_status()


@app.get("/api/export/transactions.csv")
def api_export_csv() -> Response:
    try:
        content, filename = export_transactions_csv()
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/tables")
def api_list_tables() -> dict:
    try:
        return list_tables()
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise


@app.get("/api/tables/{table_name}")
def api_table_data(
    table_name: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    if table_name not in TABLE_META:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown table. Valid: {', '.join(TABLE_META)}",
        )
    try:
        return fetch_table(table_name, limit=limit, offset=offset)
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/corrections/plan")
def api_correction_plan(body: CorrectionPlanRequest) -> dict:
    try:
        return plan_correction(body.request.strip(), db_path=get_db_path(None))
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/corrections/apply")
def api_correction_apply(body: CorrectionApplyRequest) -> dict:
    try:
        save_payee = body.save_payee.model_dump() if body.save_payee else None
        return apply_correction(
            transaction_ids=body.transaction_ids,
            new_category=body.new_category.strip(),
            new_type=body.new_type,
            merchant_patterns=body.merchant_patterns,
            save_payee=save_payee,
            db_path=get_db_path(None),
        )
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/analyze", response_model=AnalyzeResponse)
def api_analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    try:
        answer = run_analyzer(body.question.strip(), db_path=get_db_path(None))
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            raise _db_locked_response(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return AnalyzeResponse(answer=answer)
