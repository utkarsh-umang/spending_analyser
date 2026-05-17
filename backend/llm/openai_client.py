from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")


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


def use_openai_native_web_search() -> bool:
    """Use OpenAI's built-in web_search tool (Responses API). Default: true."""
    return os.getenv("OPENAI_NATIVE_WEB_SEARCH", "true").lower() not in (
        "0",
        "false",
        "no",
    )


class AgentClassificationOutput(BaseModel):
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    merchant_name: str | None = None
    reasoning: str = ""
    learning_notes: str = ""
    merchant_pattern: str = ""

    @field_validator("merchant_name", mode="before")
    @classmethod
    def _empty_merchant_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


SUBMIT_PARAMETERS = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "confidence": {
            "type": "number",
            "description": "0.0–1.0; use <0.75 when genuinely unsure",
        },
        "merchant_name": {
            "type": "string",
            "description": "Identified merchant or payee; use empty string if unknown",
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
        "merchant_name",
        "reasoning",
        "learning_notes",
        "merchant_pattern",
    ],
    "additionalProperties": False,
}


def _submit_tool_responses() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "submit_classification",
        "description": (
            "Submit the final category assignment with a calibrated confidence score. "
            "Call this after you have identified the merchant (use web search if needed)."
        ),
        "parameters": SUBMIT_PARAMETERS,
        "strict": True,
    }


def _parse_submit_from_response(response: Any) -> AgentClassificationOutput | None:
    for item in response.output or []:
        item_type = getattr(item, "type", None)
        if item_type == "function_call":
            name = getattr(item, "name", "")
            if name == "submit_classification":
                raw = getattr(item, "arguments", "{}")
                if isinstance(raw, str):
                    return AgentClassificationOutput.model_validate(json.loads(raw))
                return AgentClassificationOutput.model_validate(raw)
        if item_type == "message":
            content = getattr(item, "content", []) or []
            for block in content:
                if getattr(block, "type", None) == "output_text":
                    text = getattr(block, "text", "") or ""
                    if text.strip().startswith("{"):
                        try:
                            return AgentClassificationOutput.model_validate(
                                json.loads(text)
                            )
                        except (json.JSONDecodeError, ValueError):
                            pass
    return None


def _run_with_openai_web_search(
    *,
    system: str,
    user_message: str,
    model: str,
    max_turns: int,
) -> AgentClassificationOutput | None:
    """OpenAI Responses API with hosted web_search — no Google API keys needed."""
    client = get_openai_client()
    tools: list[dict[str, Any]] = [
        {"type": "web_search", "search_context_size": "low"},
        _submit_tool_responses(),
    ]
    instructions = (
        system
        + "\n\nUse the built-in web search tool when the merchant is unclear. "
        "When ready, you MUST call submit_classification with your final answer."
    )
    input_items: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]
    previous_response_id: str | None = None

    for _ in range(max_turns):
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "tools": tools,
            "temperature": 0.2,
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
            kwargs["input"] = [
                {
                    "role": "user",
                    "content": (
                        "Call submit_classification now with your final category, "
                        "confidence, merchant_name, reasoning, learning_notes, "
                        "and merchant_pattern."
                    ),
                }
            ]
        else:
            kwargs["input"] = input_items

        response = client.responses.create(**kwargs)
        previous_response_id = response.id

        result = _parse_submit_from_response(response)
        if result is not None:
            return result

    return None


# Legacy: custom web_search function tool (DuckDuckGo / Google CSE) via Chat Completions
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web to identify the real merchant or business behind "
            "an unclear bank statement description."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
}

SUBMIT_CLASSIFICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_classification",
        "description": "Submit the final category assignment with a calibrated confidence score.",
        "parameters": SUBMIT_PARAMETERS,
    },
}


def _run_with_custom_web_search(
    *,
    system: str,
    user_message: str,
    tool_handler: Callable[[str, dict[str, Any]], str],
    model: str,
    max_turns: int,
) -> AgentClassificationOutput | None:
    client = get_openai_client()
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
        message = response.choices[0].message
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


def run_classification_agent(
    *,
    system: str,
    user_message: str,
    tool_handler: Callable[[str, dict[str, Any]], str],
    model: str | None = None,
    max_turns: int = 8,
) -> AgentClassificationOutput | None:
    """
  Run GPT to classify a transaction.
  By default uses OpenAI's built-in web_search (Responses API) — only OPENAI_API_KEY required.
  Set OPENAI_NATIVE_WEB_SEARCH=false to use a custom DuckDuckGo/Google search tool instead.
    """
    model = model or DEFAULT_OPENAI_MODEL

    if use_openai_native_web_search():
        return _run_with_openai_web_search(
            system=system,
            user_message=user_message,
            model=model,
            max_turns=max_turns,
        )

    return _run_with_custom_web_search(
        system=system,
        user_message=user_message,
        tool_handler=tool_handler,
        model=model,
        max_turns=max_turns,
    )
