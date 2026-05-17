from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI
from pydantic import BaseModel, Field

DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env for the classification agent."
        )
    return OpenAI(api_key=api_key)


def load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text()


class AgentClassificationOutput(BaseModel):
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    merchant_name: str | None = None
    reasoning: str = ""
    learning_notes: str = ""
    merchant_pattern: str = ""


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web to identify the real merchant or business behind "
            "an unclear bank statement description. Use focused queries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'ZOMATO food delivery India'",
                }
            },
            "required": ["query"],
        },
    },
}

SUBMIT_CLASSIFICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_classification",
        "description": (
            "Submit the final category assignment with a calibrated confidence score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "confidence": {
                    "type": "number",
                    "description": "0.0–1.0; use <0.75 when genuinely unsure",
                },
                "merchant_name": {
                    "type": ["string", "null"],
                    "description": "Identified merchant or payee, if any",
                },
                "reasoning": {"type": "string"},
                "learning_notes": {
                    "type": "string",
                    "description": "Notes for future auto-classification of similar lines",
                },
                "merchant_pattern": {
                    "type": "string",
                    "description": (
                        "Short uppercase-friendly substring from the description "
                        "to match similar future transactions (e.g. ZOMATO, BLINKIT)"
                    ),
                },
            },
            "required": [
                "category",
                "confidence",
                "reasoning",
                "learning_notes",
                "merchant_pattern",
            ],
        },
    },
}


def run_classification_agent(
    *,
    system: str,
    user_message: str,
    tool_handler: Callable[[str, dict[str, Any]], str],
    model: str | None = None,
    max_turns: int = 8,
) -> AgentClassificationOutput | None:
    """
    Run GPT with web_search + submit_classification tools.
    Returns parsed classification or None if agent did not submit.
    """
    client = get_openai_client()
    model = model or DEFAULT_OPENAI_MODEL
    tools = [WEB_SEARCH_TOOL, SUBMIT_CLASSIFICATION_TOOL]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )
        choice = response.choices[0]
        message = choice.message
        if not message.tool_calls:
            break

        messages.append(message.model_dump(exclude_none=True))

        for tool_call in message.tool_calls:
            fn = tool_call.function
            name = fn.name
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "submit_classification":
                return AgentClassificationOutput.model_validate(args)

            result_str = tool_handler(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
            )

    return None
