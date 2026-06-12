"""OpenAI-compatible LLM smoke test client with output quality checks."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from autoresearch.config import ConfigParser, SystemConfig


class LLMClientError(RuntimeError):
    """Raised when a live LLM smoke request cannot complete."""


class LLMOutputQuality(BaseModel):
    """Local quality checks for the smoke-test model output."""

    score: float = Field(ge=0.0, le=1.0)
    checks: dict[str, bool]
    issues: list[str] = Field(default_factory=list)
    parsed_output: dict[str, Any] | None = None


class LLMSmokeResult(BaseModel):
    """Source-backed result from a live provider call."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    response_text: str
    usage: dict[str, Any] = Field(default_factory=dict)
    quality: LLMOutputQuality


def run_llm_smoke_test(
    *,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int = 600,
) -> LLMSmokeResult:
    """Call the configured OpenAI-compatible model and validate its output."""

    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    config_file = Path(config_path)
    config = (
        ConfigParser().parse_file(config_file, model_type=SystemConfig)
        if config_file.exists()
        else SystemConfig()
    )
    if not isinstance(config, SystemConfig):
        msg = f"Expected SystemConfig from {config_file}"
        raise LLMClientError(msg)

    llm = config.deployment.llm
    api_key = os.getenv(llm.api_key_env)
    if not api_key:
        msg = f"Missing API key environment variable {llm.api_key_env}; run deploy-setup first"
        raise LLMClientError(msg)

    endpoint = _chat_completions_endpoint(llm.base_url)
    response = _post_chat_completion(
        endpoint=endpoint,
        api_key=api_key,
        model_name=llm.model_name,
        timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
        max_tokens=max_tokens,
    )
    content = _extract_message_content(response)
    quality = evaluate_llm_output_quality(content, secret_values=[api_key])
    return LLMSmokeResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=endpoint,
        response_text=content,
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        quality=quality,
    )


def evaluate_llm_output_quality(
    response_text: str,
    *,
    secret_values: list[str] | None = None,
) -> LLMOutputQuality:
    """Score model smoke output for structure, evidence discipline, and secret safety."""

    checks: dict[str, bool] = {
        "non_empty": bool(response_text.strip()),
        "valid_json": False,
        "status_ok": False,
        "summary_present": False,
        "evidence_policy_present": False,
        "risks_present": False,
        "next_steps_present": False,
        "no_secret_leak": _has_no_secret_leak(response_text, secret_values or []),
        "no_fake_urls": not bool(re.search(r"https?://", response_text, flags=re.IGNORECASE)),
    }
    issues: list[str] = []
    parsed: dict[str, Any] | None = None
    try:
        decoded = json.loads(_strip_json_fences(response_text))
    except json.JSONDecodeError as exc:
        issues.append(f"Response is not valid JSON: {exc.msg}")
    else:
        if isinstance(decoded, dict):
            parsed = decoded
            checks["valid_json"] = True
            checks["status_ok"] = decoded.get("status") == "ok"
            checks["summary_present"] = _short_text(decoded.get("summary"))
            checks["evidence_policy_present"] = _mentions_evidence_policy(
                decoded.get("evidence_policy")
            )
            checks["risks_present"] = _string_list_has_items(decoded.get("risks"), minimum=2)
            checks["next_steps_present"] = _string_list_has_items(
                decoded.get("next_steps"),
                minimum=2,
            )
        else:
            issues.append("Response JSON top-level value is not an object")

    for check, passed in checks.items():
        if not passed:
            issues.append(f"Quality check failed: {check}")

    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 3)
    return LLMOutputQuality(score=score, checks=checks, issues=issues, parsed_output=parsed)


def _post_chat_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    timeout_seconds: int,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the AI-Researcher deployment smoke-test model. "
                    "Return only JSON. Do not include markdown fences. Do not invent URLs, "
                    "paper titles, benchmark scores, or external results."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a concise deployment readiness note for AI-Researcher. "
                    "Use this exact JSON object shape: "
                    '{"status":"ok","summary":"...","evidence_policy":"...",'
                    '"risks":["...","..."],"next_steps":["...","..."]}. '
                    "The summary must say that unverified research outcomes remain pending "
                    "verification. The evidence_policy must mention source-backed evidence "
                    "or independent fact-checking."
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMClientError(f"LLM API HTTP {exc.code}: {_redact_api_key(body)}") from exc
    except urllib.error.URLError as exc:
        raise LLMClientError(f"LLM API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMClientError("LLM API request timed out") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMClientError(f"LLM API response was not JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise LLMClientError("LLM API response JSON top-level value is not an object")
    return decoded


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMClientError("LLM API response did not include choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMClientError("LLM API first choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMClientError("LLM API first choice did not include a message object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMClientError("LLM API message content is empty")
    return content.strip()


def _chat_completions_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _has_no_secret_leak(text: str, secret_values: list[str]) -> bool:
    if re.search(r"sk-[A-Za-z0-9_-]{12,}", text):
        return False
    return all(secret not in text for secret in secret_values if secret)


def _short_text(value: Any) -> bool:
    return isinstance(value, str) and 20 <= len(value.strip()) <= 800


def _mentions_evidence_policy(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lower = value.lower()
    return any(
        phrase in lower
        for phrase in (
            "evidence",
            "source",
            "verified",
            "verification",
            "fact-check",
            "fact checking",
            "factcheck",
            "pending",
            "unknown",
        )
    )


def _string_list_has_items(value: Any, *, minimum: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _redact_api_key(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", text)
