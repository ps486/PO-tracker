"""Wrapper around the Gemini API enforcing structured (schema-constrained)
output. We pass our JSON Schema tool definitions straight to Gemini's
`response_json_schema` (a genai SDK field that accepts standard JSON Schema,
including the `additionalProperties` and nullable-type-union patterns our
schemas already use - no format conversion needed) alongside
`response_mime_type="application/json"`, which forces the model to return
exactly that shape - it cannot return free-form text instead.

Per section 22 this is the ONLY way AI output reaches the rest of the pipeline:
AI -> this module (forced JSON) -> pydantic validation (schemas.py) -> business
rules (validation/rules.py) -> database. Nothing here writes to the database.
"""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from .. import runtime_config


def _get_client() -> genai.Client:
    # Not cached: the key can change at any time via the Settings screen
    # (runtime_config.save()), and constructing the client does no network
    # I/O, so there's no cost to reading the current key on every call.
    return genai.Client(api_key=runtime_config.GEMINI_API_KEY)


def _image_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": png_bytes,  # kept as raw bytes here; base64-encoded only if/when a provider needs that
        },
    }


def build_content_blocks(text: str, images: list[bytes]) -> list[dict]:
    blocks: list[dict] = []
    for img in images:
        blocks.append(_image_block(img))
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def _to_gemini_parts(content_blocks: list[dict]) -> list[types.Part]:
    parts: list[types.Part] = []
    for block in content_blocks:
        if block["type"] == "image":
            parts.append(types.Part.from_bytes(data=block["source"]["data"], mime_type=block["source"]["media_type"]))
        elif block["type"] == "text":
            parts.append(types.Part.from_text(text=block["text"]))
    return parts


def call_structured(
    system_prompt: str,
    content_blocks: list[dict],
    tool_name: str,
    tool_schema: dict,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Calls Gemini with a JSON schema forcing the response into a guaranteed
    shape (still validated downstream by pydantic - never trust blindly).
    `tool_name` isn't used by Gemini's structured-output API (there's no
    "named tool" wrapper the way Anthropic/OpenAI have one) - it's kept as a
    parameter so every call site didn't need to change when switching
    providers."""
    client = _get_client()
    response = client.models.generate_content(
        model=runtime_config.AI_MODEL,
        contents=_to_gemini_parts(content_blocks),
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_json_schema=tool_schema,
            max_output_tokens=max_tokens,
        ),
    )
    if not response.text:
        raise ValueError(
            f"Gemini returned no content (finish_reason={getattr(response.candidates[0], 'finish_reason', None) if response.candidates else None})"
        )
    return json.loads(response.text)


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
