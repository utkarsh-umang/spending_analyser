from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.analysis.agent import run_analyzer
from backend.config import get_db_path
from backend.web.service import build_status, export_transactions_csv

WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "web"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Spending Analyzer", docs_url="/api/docs", redoc_url=None)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class AnalyzeResponse(BaseModel):
    answer: str


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
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
def api_analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    try:
        answer = run_analyzer(body.question.strip(), db_path=get_db_path(None))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return AnalyzeResponse(answer=answer)
