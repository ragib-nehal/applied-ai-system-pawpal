import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.ollama_client import OllamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(content_dict: dict, status_code: int = 200):
    """Build a mock requests.Response with message.content set to JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "model": "qwen2.5",
        "message": {"role": "assistant", "content": json.dumps(content_dict)},
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_error_response(status_code: int = 500):
    import requests

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
    return mock_resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_default_base_url_and_model():
    client = OllamaClient()
    assert client.base_url == "http://localhost:11434"
    assert client.model == "qwen2.5"


def test_custom_base_url_strips_trailing_slash():
    client = OllamaClient(base_url="http://myhost:11434/")
    assert client.base_url == "http://myhost:11434"


def test_custom_model():
    client = OllamaClient(model="llama3")
    assert client.model == "llama3"


# ---------------------------------------------------------------------------
# generate_json — happy path
# ---------------------------------------------------------------------------

def test_generate_json_returns_parsed_dict():
    client = OllamaClient()
    expected = {"schedule": [], "guidance": []}
    with patch("services.ollama_client.requests.post", return_value=_mock_response(expected)) as mock_post:
        result = client.generate_json("sys", "user")
    assert result == expected
    mock_post.assert_called_once()


def test_generate_json_sends_correct_payload():
    client = OllamaClient(model="llama3")
    with patch("services.ollama_client.requests.post", return_value=_mock_response({})) as mock_post:
        client.generate_json("system prompt", "user prompt")
    call_kwargs = mock_post.call_args
    sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    assert sent_json["model"] == "llama3"
    assert sent_json["stream"] is False
    assert sent_json["format"] == "json"
    messages = sent_json["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "system prompt"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "user prompt"


def test_generate_json_posts_to_correct_url():
    client = OllamaClient(base_url="http://myhost:11434")
    with patch("services.ollama_client.requests.post", return_value=_mock_response({})) as mock_post:
        client.generate_json("s", "u")
    url = mock_post.call_args[0][0]
    assert url == "http://myhost:11434/api/chat"


def test_generate_json_uses_timeout_180():
    client = OllamaClient()
    with patch("services.ollama_client.requests.post", return_value=_mock_response({})) as mock_post:
        client.generate_json("s", "u")
    call_kwargs = mock_post.call_args
    timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
    assert timeout == 180


# ---------------------------------------------------------------------------
# generate_json — content extraction
# ---------------------------------------------------------------------------

def test_generate_json_handles_empty_message_content():
    client = OllamaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "{}"}}
    mock_resp.raise_for_status = MagicMock()
    with patch("services.ollama_client.requests.post", return_value=mock_resp):
        result = client.generate_json("s", "u")
    assert result == {}


def test_generate_json_handles_missing_message_key():
    client = OllamaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}  # no "message" key
    mock_resp.raise_for_status = MagicMock()
    with patch("services.ollama_client.requests.post", return_value=mock_resp):
        result = client.generate_json("s", "u")
    assert result == {}


# ---------------------------------------------------------------------------
# generate_json — error handling
# ---------------------------------------------------------------------------

def test_generate_json_raises_on_http_error():
    import requests as req_module

    client = OllamaClient()
    with patch("services.ollama_client.requests.post", return_value=_mock_error_response(500)):
        with pytest.raises(req_module.HTTPError):
            client.generate_json("s", "u")


def test_generate_json_raises_on_json_decode_error():
    client = OllamaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "not valid json {"}}
    mock_resp.raise_for_status = MagicMock()
    with patch("services.ollama_client.requests.post", return_value=mock_resp):
        with pytest.raises(json.JSONDecodeError):
            client.generate_json("s", "u")