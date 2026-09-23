"""Verifies the Gemini request/response plumbing without a real API key or
network call: mocks google.genai.Client and checks call_structured builds the
right request shape and correctly parses the response back into a dict."""
import json
from unittest.mock import MagicMock, patch

from backend.app.extraction.ai_client import build_content_blocks, call_structured


def test_build_content_blocks_puts_images_before_text():
    blocks = build_content_blocks("hello", [b"png-bytes-1", b"png-bytes-2"])
    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    assert blocks[-1]["text"] == "hello"


def test_build_content_blocks_with_no_images():
    blocks = build_content_blocks("just text", [])
    assert blocks == [{"type": "text", "text": "just text"}]


def _fake_response(payload: dict):
    resp = MagicMock()
    resp.text = json.dumps(payload)
    return resp


def test_call_structured_returns_parsed_json():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response({"confidence": 0.95, "reasons": ["x"]})

    with patch("backend.app.extraction.ai_client.genai.Client", return_value=fake_client):
        result = call_structured("system prompt", [{"type": "text", "text": "hi"}], "tool_name", {"type": "object"})

    assert result == {"confidence": 0.95, "reasons": ["x"]}


def test_call_structured_passes_schema_and_system_prompt_through():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response({"ok": True})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    with patch("backend.app.extraction.ai_client.genai.Client", return_value=fake_client):
        call_structured("be precise", [{"type": "text", "text": "hi"}], "tool_name", schema, max_tokens=2048)

    _, kwargs = fake_client.models.generate_content.call_args
    config = kwargs["config"]
    assert config.system_instruction == "be precise"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema
    assert config.max_output_tokens == 2048


def test_call_structured_converts_image_and_text_blocks_to_parts():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response({"ok": True})
    blocks = build_content_blocks("some text", [b"fake-png-bytes"])

    with patch("backend.app.extraction.ai_client.genai.Client", return_value=fake_client):
        call_structured("sys", blocks, "tool_name", {"type": "object"})

    _, kwargs = fake_client.models.generate_content.call_args
    parts = kwargs["contents"]
    assert len(parts) == 2
    # First part should be the image (inline_data), second the text.
    assert parts[0].inline_data.data == b"fake-png-bytes"
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[1].text == "some text"


def test_call_structured_raises_on_empty_response():
    fake_client = MagicMock()
    empty_response = MagicMock()
    empty_response.text = None
    empty_response.candidates = []
    fake_client.models.generate_content.return_value = empty_response

    with patch("backend.app.extraction.ai_client.genai.Client", return_value=fake_client):
        try:
            call_structured("sys", [{"type": "text", "text": "hi"}], "tool_name", {"type": "object"})
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "no content" in str(exc)
