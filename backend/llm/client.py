from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anthropic

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic(api_key=api_key)


def load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text()


def call_with_tool(
    *,
    system: str,
    user_content: list[dict[str, Any]],
    tool: dict[str, Any],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
) -> dict[str, Any]:
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input
    raise RuntimeError(f"Expected tool use '{tool['name']}' in response")


def call_agent_loop(
    *,
    system: str,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_handler: Any,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    max_turns: int = 15,
) -> str:
    client = get_client()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]
    for _ in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        assistant_content: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        final_answer: str | None = None

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                if block.name == "final_answer":
                    final_answer = block.input.get("answer", "")
                else:
                    result = tool_handler(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        }
                    )

        messages.append({"role": "assistant", "content": assistant_content})

        if final_answer is not None:
            return final_answer

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            break
        else:
            break

    return "Unable to produce an answer within the turn limit."
