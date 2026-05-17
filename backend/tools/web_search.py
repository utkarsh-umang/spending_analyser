from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote_plus

import httpx


def web_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
    """
    Search the web to identify merchants. Uses Google Custom Search when configured,
    otherwise DuckDuckGo (no API key required).
    """
    query = query.strip()
    if not query:
        return {"query": query, "results": [], "error": "Empty query"}

    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")
    if api_key and cse_id:
        return _google_custom_search(query, api_key, cse_id, max_results=max_results)
    return _duckduckgo_search(query, max_results=max_results)


def _google_custom_search(
    query: str, api_key: str, cse_id: str, *, max_results: int
) -> dict[str, Any]:
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "num": min(max_results, 10),
    }
    try:
        resp = httpx.get(url, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items") or []
        results = [
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            }
            for item in items[:max_results]
        ]
        return {"query": query, "engine": "google", "results": results}
    except Exception as e:
        return {"query": query, "engine": "google", "results": [], "error": str(e)}


def _duckduckgo_search(query: str, *, max_results: int) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    last_error: str | None = None
    for import_path in ("ddgs", "duckduckgo_search"):
        try:
            if import_path == "ddgs":
                from ddgs import DDGS  # type: ignore[import-untyped]
            else:
                from duckduckgo_search import DDGS  # type: ignore[import-untyped]

            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    results.append(
                        {
                            "title": item.get("title", ""),
                            "snippet": item.get("body", item.get("snippet", "")),
                            "link": item.get("href", item.get("link", "")),
                        }
                    )
            if results:
                return {"query": query, "engine": import_path, "results": results}
        except Exception as e:
            last_error = str(e)
            continue
    return {
        "query": query,
        "engine": "duckduckgo",
        "results": results,
        "error": last_error or "No results",
    }
