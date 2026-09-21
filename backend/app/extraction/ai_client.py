"""Wrapper around the Anthropic API enforcing structured (schema-constrained)
output. We use tool-use with `tool_choice` forced to a single tool whose input
schema is the JSON schema we want back - the model cannot return free-form text
instead of the shape we require.

Per section 22 this is the ONLY way AI output reaches the rest of the pipeline:
AI -> this module (forced JSON) -> pydantic validation (schemas.py) -> business
rules (validation/rules.py) -> database. Nothing here writes to the database.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import anthropic

from ..config import settings

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _image_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(png_bytes).decode(),
        },
    }


def build_content_blocks(text: str, images: list[bytes]) -> list[dict]:
    blocks: list[dict] = []
    for img in images:
        blocks.append(_image_block(img))
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def call_structured(
    system_prompt: str,
    content_blocks: list[dict],
    tool_name: str,
    tool_schema: dict,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Calls Claude with a forced tool call so the response is guaranteed-shape
    JSON (still validated downstream by pydantic - never trust blindly)."""
    client = _get_client()
    response = client.messages.create(
        model=settings.AI_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        tools=[{"name": tool_name, "description": f"Return {tool_name} data.", "input_schema": tool_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": content_blocks}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise ValueError("AI response did not contain the expected tool_use block")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
