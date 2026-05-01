from __future__ import annotations

import json
from typing import Any

import requests


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/chat",
            timeout=180,
            json={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
            },
        )
        response.raise_for_status()
        body = response.json()
        content = body.get("message", {}).get("content", "{}")
        return json.loads(content)