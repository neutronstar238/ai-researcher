"""OpenAI 兼容 LLM Provider（spec §10.6/§26.3，provider-agnostic）。

任何 OpenAI 兼容端点（OpenAI / DeepSeek / 阿里云百炼 DashScope compatible-mode /
Ollama / vLLM 等）都可用：从配置读取 ``base_url``/``api_key``/``model``，不写死某一家。
未配置或调用失败时抛 ``ProviderNotConfiguredError`` / 结构化错误，绝不伪造成功（§23.4）。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.api.errors import ProviderNotConfiguredError
from app.core.config import get_settings
from app.integrations.llm.base import LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = (settings.llm_base_url or "").rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model or "gpt-4o-mini"
        if not self.base_url or not self.api_key:
            raise ProviderNotConfiguredError(
                "LLM 未完整配置（需 LLM_BASE_URL + LLM_API_KEY）"
            )

    async def complete(self, prompt: str, *, json_schema: dict | None = None) -> LLMResponse:
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if json_schema is not None:
            # OpenAI 兼容端点对结构化输出支持不一：统一用 json_object + 在 prompt 里注入 schema。
            body["response_format"] = {"type": "json_object"}
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "You must respond with a single valid JSON object matching this JSON Schema:\n"
                        f"{json.dumps(json_schema, ensure_ascii=False)}"
                    ),
                },
            )

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=body, headers=headers)
        if response.status_code >= 400:
            raise ProviderNotConfiguredError(
                f"LLM 调用失败 HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage")

        structured: dict | None = None
        if json_schema is not None:
            structured = self._parse_json(content)
        return LLMResponse(content=content, structured=structured, usage=usage)

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        text = content.strip()
        # 去掉可能的 ```json ... ``` 围栏
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
