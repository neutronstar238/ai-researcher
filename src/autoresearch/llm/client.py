"""OpenAI-compatible LLM smoke test client with output quality checks."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.schemas import file_hash

REVIEW_SUBJECT_MAX_CHARS = 36_000
REVIEW_EVIDENCE_MAX_CHARS = 3_000
PROFILE_CONTEXT_TERMS = (
    "agent_profiles",
    "stage_runtime_contexts",
    "stage_agent_contexts",
    "agent profile",
    "profile context",
    "mcp_runtime_contract",
    "mcp runtime contract",
    "runtime contract",
    "skill",
    "skills",
    "mcp",
    "allowlist",
    "allowlists",
)
PROFILE_PROOF_TERMS = (
    "prove",
    "proves",
    "proof",
    "support",
    "supports",
    "supported",
    "validate",
    "validates",
    "validated",
    "verify",
    "verifies",
    "verified",
    "confirm",
    "confirms",
    "confirmed",
    "demonstrate",
    "demonstrates",
    "establish",
    "establishes",
    "evidence for",
)
PROFILE_SCIENTIFIC_CLAIM_TERMS = (
    "scientific result",
    "scientific results",
    "result",
    "results",
    "novelty",
    "benchmark",
    "metric",
    "metrics",
    "accuracy",
    "f1",
    "citation",
    "citations",
    "publication readiness",
    "publishable",
    "tool invocation",
    "tool was invoked",
    "tool use",
)
PROFILE_CONTEXT_NEGATION_TERMS = (
    "not evidence",
    "not proof",
    "cannot prove",
    "does not prove",
    "doesn't prove",
    "process metadata",
    "responsibility boundary",
    "responsibility boundaries",
    "available tool context",
)


class LLMClientError(RuntimeError):
    """Raised when a live LLM smoke request cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        response_text: str | None = None,
        response_usage: dict[str, Any] | None = None,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.response_text = response_text
        self.response_usage = response_usage or {}
        self.finish_reason = finish_reason


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
    attempts: int = Field(default=1, ge=1)


class LLMEvidenceArtifact(BaseModel):
    """Local evidence artifact supplied to an LLM reviewer."""

    evidence_id: str
    path: str
    sha256: str
    excerpt: str


class LLMReviewQuality(BaseModel):
    """Local checks for an LLM-as-reviewer response."""

    score: float = Field(ge=0.0, le=1.0)
    checks: dict[str, bool]
    issues: list[str] = Field(default_factory=list)
    parsed_output: dict[str, Any] | None = None


class LLMReviewResult(BaseModel):
    """Source-constrained LLM review result with local evidence provenance."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    subject_path: str
    subject_sha256: str
    evidence: list[LLMEvidenceArtifact]
    response_text: str
    usage: dict[str, Any] = Field(default_factory=dict)
    quality: LLMReviewQuality
    attempts: int = Field(default=1, ge=1)


class LLMJsonCompletionResult(BaseModel):
    """Raw JSON completion result from the configured provider."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    response_text: str
    parsed_json: dict[str, Any]
    transport_normalization: Literal[
        "none",
        "discarded_trailing_closing_delimiters",
        "discarded_leading_self_revision",
    ] = "none"
    normalization_suffix: str | None = Field(
        default=None,
        min_length=1,
        max_length=200_000,
    )
    usage: dict[str, Any] = Field(default_factory=dict)
    temperature: float = Field(ge=0.0)
    # Task 267.3.1: explicit reasoning output.  This records HOW a candidate was
    # authored.  It is process evidence only and must never satisfy an evidence
    # gate, a metric claim, or a publication claim.
    reasoning_text: str | None = Field(default=None, max_length=200_000)
    reasoning_is_evidence: Literal[False] = False
    reasoning_transport: Literal[
        "absent",
        "dashscope_enable_thinking",
        "anthropic_thinking_block",
    ] = "absent"

    @model_validator(mode="after")
    def _validate_transport_normalization(self) -> LLMJsonCompletionResult:
        normalized = self.transport_normalization != "none"
        if normalized != (self.normalization_suffix is not None):
            raise ValueError("JSON transport normalization suffix presence mismatch")
        if self.normalization_suffix is not None:
            if self.transport_normalization == "discarded_trailing_closing_delimiters":
                delimiters = self.normalization_suffix.strip()
                if (
                    len(self.normalization_suffix) > 4
                    or not delimiters
                    or any(marker not in "]}" for marker in delimiters)
                ):
                    raise ValueError(
                        "JSON transport normalization suffix is not a closing delimiter"
                    )
            elif self.transport_normalization == "discarded_leading_self_revision":
                if not self.response_text.startswith(self.normalization_suffix):
                    raise ValueError("JSON self-revision prefix differs from raw response")
                selected = self.response_text[len(self.normalization_suffix) :].strip()
                try:
                    parsed = json.loads(selected)
                except json.JSONDecodeError as exc:
                    raise ValueError("selected JSON self-revision is invalid") from exc
                if parsed != self.parsed_json:
                    raise ValueError("selected JSON self-revision payload changed")
        return self


def run_llm_smoke_test(
    *,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
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
        messages=_smoke_messages(),
    )
    content = _extract_message_content(response)
    quality = evaluate_llm_output_quality(content, secret_values=[api_key])
    attempts = 1
    if _has_failed_output_critical_checks(quality):
        attempts += 1
        response = _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=_smoke_repair_messages(
                previous_response=content,
                issues=quality.issues,
            ),
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
        attempts=attempts,
    )


def run_llm_evidence_review(
    *,
    subject_path: Path | str,
    evidence_paths: list[Path | str],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
) -> LLMReviewResult:
    """Ask the configured model to review output using only local evidence artifacts."""

    if not evidence_paths:
        msg = "at least one local evidence file is required for LLM review"
        raise LLMClientError(msg)

    config, api_key = _load_llm_config_and_api_key(config_path=config_path, env_path=env_path)
    llm = config.deployment.llm
    endpoint = _chat_completions_endpoint(llm.base_url)
    subject_file = Path(subject_path)
    subject_text = _read_limited_text(
        subject_file,
        label="subject",
        max_chars=REVIEW_SUBJECT_MAX_CHARS,
    )
    evidence = [
        _read_evidence_artifact(index=index, path=Path(path))
        for index, path in enumerate(evidence_paths, start=1)
    ]
    response = _post_chat_completion(
        endpoint=endpoint,
        api_key=api_key,
        model_name=llm.model_name,
        timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
        max_tokens=max_tokens,
        messages=_review_messages(
            subject_path=subject_file,
            subject_text=subject_text,
            evidence=evidence,
        ),
    )
    content = _extract_message_content(response)
    quality = evaluate_llm_review_quality(
        content,
        evidence_ids=[artifact.evidence_id for artifact in evidence],
        secret_values=[api_key],
    )
    attempts = 1
    if _has_failed_review_critical_checks(quality):
        attempts += 1
        response = _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=_review_repair_messages(
                previous_response=content,
                issues=quality.issues,
                evidence=evidence,
            ),
        )
        content = _extract_message_content(response)
        quality = evaluate_llm_review_quality(
            content,
            evidence_ids=[artifact.evidence_id for artifact in evidence],
            secret_values=[api_key],
        )
    return LLMReviewResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=endpoint,
        subject_path=subject_file.as_posix(),
        subject_sha256=file_hash(subject_file),
        evidence=evidence,
        response_text=content,
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        quality=quality,
        attempts=attempts,
    )


def run_llm_json_completion(
    *,
    messages: list[dict[str, str]],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    reasoning_effort: str | None = None,
    thinking_mode: Literal["enabled", "disabled"] | None = None,
    thinking_budget: int | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "autoresearch_output",
) -> LLMJsonCompletionResult:
    """Call the configured OpenAI-compatible model and require one JSON object."""

    config, api_key = _load_llm_config_and_api_key(config_path=config_path, env_path=env_path)
    llm = config.deployment.llm
    if reasoning_effort == "none" and llm.provider.lower().startswith("ollama"):
        endpoint = _ollama_native_chat_endpoint(llm.base_url)
        response = _post_ollama_native_json_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=messages,
            temperature=temperature,
            response_schema=response_schema,
        )
    else:
        endpoint = _chat_completions_endpoint(llm.base_url)
        response = _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=messages,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            thinking_mode=thinking_mode,
            thinking_budget=thinking_budget,
            provider=llm.provider,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
        )
    content = _extract_message_content(response)
    try:
        parsed, transport_normalization, normalization_suffix = (
            _parse_json_completion_content(content)
        )
    except json.JSONDecodeError as exc:
        raise LLMClientError(
            f"LLM JSON completion was not valid JSON: {exc.msg}",
            response_text=content,
            response_usage=(
                response.get("usage", {})
                if isinstance(response.get("usage"), dict)
                else {}
            ),
            finish_reason=_response_finish_reason(response),
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMClientError(
            "LLM JSON completion top-level value is not an object",
            response_text=content,
            response_usage=(
                response.get("usage", {})
                if isinstance(response.get("usage"), dict)
                else {}
            ),
            finish_reason=_response_finish_reason(response),
        )
    return LLMJsonCompletionResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=endpoint,
        response_text=content,
        parsed_json=parsed,
        transport_normalization=transport_normalization,
        normalization_suffix=normalization_suffix,
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        temperature=temperature,
        reasoning_text=_extract_reasoning_content(response),
        reasoning_transport=(
            reasoning_transport_for_provider(llm.provider)
            if thinking_mode is not None
            else "absent"
        ),
    )


def _extract_reasoning_content(response: dict[str, Any]) -> str | None:
    """Return provider reasoning text when present, as explicit recorded output."""

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning[:200_000]
    return None


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
    critical_checks = (
        "valid_json",
        "status_ok",
        "summary_present",
        "evidence_policy_present",
        "risks_present",
        "next_steps_present",
        "no_secret_leak",
        "no_fake_urls",
    )
    if any(not checks[check] for check in critical_checks):
        score = min(score, 0.5)
    return LLMOutputQuality(score=score, checks=checks, issues=issues, parsed_output=parsed)


def evaluate_llm_review_quality(
    response_text: str,
    *,
    evidence_ids: list[str],
    secret_values: list[str] | None = None,
) -> LLMReviewQuality:
    """Score an LLM reviewer response for local evidence discipline."""

    known_ids = set(evidence_ids)
    checks: dict[str, bool] = {
        "non_empty": bool(response_text.strip()),
        "valid_json": False,
        "verdict_present": False,
        "summary_present": False,
        "findings_present": False,
        "finding_refs_present": False,
        "finding_refs_known": False,
        "unsupported_claims_present": False,
        "next_steps_present": False,
        "profile_context_not_used_as_scientific_evidence": False,
        "no_secret_leak": _has_no_secret_leak(response_text, secret_values or []),
        "no_fake_urls": not bool(re.search(r"https?://", response_text, flags=re.IGNORECASE)),
    }
    issues: list[str] = []
    parsed: dict[str, Any] | None = None
    try:
        decoded = json.loads(_strip_json_fences(response_text))
    except json.JSONDecodeError as exc:
        issues.append(f"Review response is not valid JSON: {exc.msg}")
    else:
        if isinstance(decoded, dict):
            parsed = decoded
            checks["valid_json"] = True
            checks["verdict_present"] = decoded.get("verdict") in {
                "pass",
                "needs_revision",
                "fail",
            }
            checks["summary_present"] = _short_text(decoded.get("summary"))
            findings = decoded.get("findings")
            checks["findings_present"] = isinstance(findings, list) and bool(findings)
            refs_by_finding = _finding_evidence_refs(findings)
            checks["finding_refs_present"] = bool(refs_by_finding) and all(refs_by_finding)
            checks["finding_refs_known"] = bool(refs_by_finding) and all(
                ref in known_ids for refs in refs_by_finding for ref in refs
            )
            checks["unsupported_claims_present"] = isinstance(
                decoded.get("unsupported_claims"),
                list,
            )
            checks["next_steps_present"] = _string_list_has_items(
                decoded.get("next_steps"),
                minimum=1,
            )
            checks["profile_context_not_used_as_scientific_evidence"] = (
                not _review_misuses_profile_context(findings)
            )
        else:
            issues.append("Review response JSON top-level value is not an object")

    for check, passed in checks.items():
        if not passed:
            issues.append(f"Review quality check failed: {check}")

    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 3)
    critical_checks = (
        "valid_json",
        "verdict_present",
        "summary_present",
        "findings_present",
        "finding_refs_present",
        "finding_refs_known",
        "unsupported_claims_present",
        "next_steps_present",
        "profile_context_not_used_as_scientific_evidence",
        "no_secret_leak",
        "no_fake_urls",
    )
    if any(not checks[check] for check in critical_checks):
        score = min(score, 0.5)
    return LLMReviewQuality(score=score, checks=checks, issues=issues, parsed_output=parsed)


def _has_failed_output_critical_checks(quality: LLMOutputQuality) -> bool:
    critical_checks = (
        "valid_json",
        "status_ok",
        "summary_present",
        "evidence_policy_present",
        "risks_present",
        "next_steps_present",
        "no_secret_leak",
        "no_fake_urls",
    )
    return any(not quality.checks.get(check, False) for check in critical_checks)


def _has_failed_review_critical_checks(quality: LLMReviewQuality) -> bool:
    critical_checks = (
        "valid_json",
        "verdict_present",
        "summary_present",
        "findings_present",
        "finding_refs_present",
        "finding_refs_known",
        "unsupported_claims_present",
        "next_steps_present",
        "profile_context_not_used_as_scientific_evidence",
        "no_secret_leak",
        "no_fake_urls",
    )
    return any(not quality.checks.get(check, False) for check in critical_checks)


_DEFAULT_THINKING_BUDGET = 4_000


def reasoning_transport_for_provider(
    provider: str,
) -> Literal["dashscope_enable_thinking", "anthropic_thinking_block"]:
    """Return the reasoning-parameter dialect a provider actually accepts.

    Task 267.3.1.  Kept provider-neutral: engine code passes a normalized
    `thinking_mode` and this function maps it onto the vendor's real field names.
    """

    normalized = provider.casefold()
    if "dashscope" in normalized or "qwen" in normalized or "ollama" in normalized:
        return "dashscope_enable_thinking"
    if "anthropic" in normalized or "claude" in normalized:
        return "anthropic_thinking_block"
    # Unknown providers use the OpenAI-compatible DashScope-style field, which is
    # the dialect this deployment has actually verified live.
    return "dashscope_enable_thinking"


def _reasoning_parameters(
    *,
    provider: str,
    thinking_mode: Literal["enabled", "disabled"],
    thinking_budget: int | None,
) -> dict[str, Any]:
    """Build the provider-correct reasoning payload fields.

    Always bounds the reasoning budget when reasoning is enabled: unbounded
    reasoning on `qwen3-max` produced 81,933 completion tokens for a trivial
    prompt and an intermittently empty `content`.
    """

    transport = reasoning_transport_for_provider(provider)
    if transport == "anthropic_thinking_block":
        return {"thinking": {"type": thinking_mode}}
    if thinking_mode != "enabled":
        return {"enable_thinking": False}
    return {
        "enable_thinking": True,
        "thinking_budget": thinking_budget or _DEFAULT_THINKING_BUDGET,
    }


def _post_chat_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    timeout_seconds: int,
    max_tokens: int | None,
    messages: list[dict[str, str]] | None = None,
    temperature: float = 0.0,
    reasoning_effort: str | None = None,
    thinking_mode: Literal["enabled", "disabled"] | None = None,
    thinking_budget: int | None = None,
    provider: str = "",
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "autoresearch_output",
) -> dict[str, Any]:
    payload = {
        "model": model_name,
        "messages": messages or _smoke_messages(),
        "temperature": temperature,
        "response_format": (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            }
            if response_schema is not None
            else {"type": "json_object"}
        ),
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    if thinking_mode is not None:
        # Task 267.3.1: dispatch the provider-correct reasoning parameter.
        # The Anthropic-shaped `{"thinking": {"type": ...}}` field is silently
        # ignored by DashScope, which returns HTTP 200 with empty
        # `reasoning_content`, so the reasoning chain was never engaged.
        payload.update(
            _reasoning_parameters(
                provider=provider,
                thinking_mode=thinking_mode,
                thinking_budget=thinking_budget,
            )
        )
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


def _ollama_native_chat_endpoint(base_url: str) -> str:
    """Translate an Ollama OpenAI-compatible base URL to its native chat endpoint."""

    parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, f"{path}/api/chat", "", "")
    )


def _post_ollama_native_json_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    timeout_seconds: int,
    max_tokens: int | None,
    messages: list[dict[str, str]],
    temperature: float,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Use Ollama's native ``think=false`` path and normalize its response.

    Ollama's OpenAI-compatible endpoint currently accepts ``reasoning_effort``
    but does not disable thinking for Qwen 3.5. Short structured calls can
    therefore spend the complete output budget on hidden reasoning and return
    an empty message. The native endpoint has an explicit ``think`` switch.
    The public client selects this adapter only for an Ollama provider and an
    explicit ``reasoning_effort="none"`` request.
    """

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": response_schema or "json",
        "options": options,
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
        raise LLMClientError(
            f"Ollama native API HTTP {exc.code}: {_redact_api_key(body)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise LLMClientError(f"Ollama native API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMClientError("Ollama native API request timed out") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMClientError(
            f"Ollama native API response was not JSON: {exc.msg}"
        ) from exc
    if not isinstance(decoded, dict):
        raise LLMClientError("Ollama native API response top-level value is not an object")
    message = decoded.get("message")
    if not isinstance(message, dict):
        raise LLMClientError("Ollama native API response did not include a message")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMClientError("Ollama native API message content is not text")
    return {
        "choices": [
            {
                "finish_reason": decoded.get("done_reason"),
                "message": {"role": message.get("role", "assistant"), "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": int(decoded.get("prompt_eval_count") or 0),
            "completion_tokens": int(decoded.get("eval_count") or 0),
            "total_tokens": int(decoded.get("prompt_eval_count") or 0)
            + int(decoded.get("eval_count") or 0),
        },
    }


def _smoke_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the AI-Researcher deployment smoke-test model. "
                "Return only one valid JSON object. Do not include markdown fences. "
                "Do not invent URLs, paper titles, benchmark scores, or external results. "
                "Do not encode JSON arrays as strings."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a concise deployment readiness note for AI-Researcher. "
                "Use this exact JSON object shape: "
                '{"status":"ok","summary":"...","evidence_policy":"...",'
                '"risks":["...","..."],"next_steps":["...","..."]}. '
                "`risks` and `next_steps` must be real JSON arrays, not quoted strings. "
                "The summary must say that unverified research outcomes remain pending "
                "verification. The evidence_policy must mention source-backed evidence "
                "or independent fact-checking."
            ),
        },
    ]


def _smoke_repair_messages(
    *,
    previous_response: str,
    issues: list[str],
) -> list[dict[str, str]]:
    issue_text = "; ".join(issues[:8])
    return [
        {
            "role": "system",
            "content": (
                "You are repairing a failed AI-Researcher deployment smoke-test response. "
                "Return only one syntactically valid JSON object. Do not include markdown "
                "fences, comments, URLs, or quoted JSON arrays."
            ),
        },
        {
            "role": "user",
            "content": (
                "The previous response failed deterministic local quality checks. "
                f"Failed checks and parser errors: {issue_text}. "
                "Return a corrected object with exactly these keys and value types: "
                '{"status":"ok","summary":"...","evidence_policy":"...",'
                '"risks":["...","..."],"next_steps":["...","..."]}. '
                "Both `risks` and `next_steps` must be arrays of strings. "
                "The summary must say that unverified research outcomes remain pending "
                "verification. The evidence_policy must mention source-backed evidence "
                "or independent fact-checking.\n\n"
                f"Previous invalid response:\n{previous_response[:2000]}"
            ),
        },
    ]


def _load_llm_config_and_api_key(
    *,
    config_path: Path | str,
    env_path: Path | str,
) -> tuple[SystemConfig, str]:
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
    return config, api_key


def _read_evidence_artifact(*, index: int, path: Path) -> LLMEvidenceArtifact:
    excerpt = _read_limited_text(
        path,
        label=f"evidence_{index}",
        max_chars=REVIEW_EVIDENCE_MAX_CHARS,
    )
    return LLMEvidenceArtifact(
        evidence_id=f"evidence_{index}",
        path=path.as_posix(),
        sha256=file_hash(path),
        excerpt=excerpt,
    )


def _read_limited_text(path: Path, *, label: str, max_chars: int) -> str:
    if not path.exists():
        msg = f"{label} file is missing: {path.as_posix()}"
        raise LLMClientError(msg)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{label} file must be UTF-8 text: {path.as_posix()}"
        raise LLMClientError(msg) from exc
    return text[:max_chars]


def _review_messages(
    *,
    subject_path: Path,
    subject_text: str,
    evidence: list[LLMEvidenceArtifact],
) -> list[dict[str, str]]:
    evidence_block = "\n\n".join(
        (
            f"[{artifact.evidence_id}] path={artifact.path} sha256={artifact.sha256}\n"
            f"{artifact.excerpt}"
        )
        for artifact in evidence
    )
    allowed_ids = ", ".join(artifact.evidence_id for artifact in evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are the AI-Researcher quality reviewer. Return only JSON. "
                "Judge the subject only against the provided local evidence artifacts. "
                "Every finding must cite one or more provided evidence IDs exactly. "
                "Use only the outer evidence IDs supplied by this prompt as citations. "
                "Agent profile context, including agent_profiles, stage_runtime_contexts, "
                "stage_agent_contexts, skills, MCP allowlists, and mcp_runtime_contracts, "
                "is process metadata only. "
                "It may support findings about responsibility boundaries or available tool "
                "context, but it is not evidence for scientific results, novelty, benchmark "
                "metrics, citation validity, or publication readiness. A profile does not "
                "prove a tool was invoked. "
                "Do not invent URLs, papers, metrics, benchmark results, or files. "
                "Do not encode JSON arrays as strings."
            ),
        },
        {
            "role": "user",
            "content": (
                "Review the subject output for evidence support, unsupported claims, "
                "missing caveats, and next actions. Use this exact JSON object shape: "
                '{"verdict":"pass|needs_revision|fail","summary":"...",'
                '"findings":[{"severity":"info|warning|blocking","claim":"...",'
                '"evidence_refs":["evidence_1"]}],"unsupported_claims":["..."],'
                '"next_steps":["..."]}. `findings`, `evidence_refs`, `unsupported_claims`, '
                "and `next_steps` must be real JSON arrays, not quoted strings. "
                "Every finding must have at least one evidence_refs "
                "entry from the provided local evidence IDs. If you cannot cite a provided "
                "evidence ID for a claim, put that claim in unsupported_claims instead of "
                "findings. Allowed evidence_refs values are exactly: "
                f"{allowed_ids}. Do not use file names, paths, source_run_id values, "
                "or nested id/evidence_ref values from inside evidence files as "
                "evidence_refs. If the subject report cites internal metric evidence "
                "edge IDs, treat those subject citations as valid when the IDs appear "
                "inside a provided evidence-map artifact; this rule does not change "
                "the outer evidence_refs IDs required in your JSON. Use verdict `pass` "
                "when unsupported_claims is empty and all findings are informational. "
                "Use `needs_revision` only when there is at least one unsupported claim, "
                "missing caveat, warning finding, blocking finding, or concrete revision "
                "action. next_steps must contain at least one non-empty string; if the "
                "verdict is pass, use a maintenance step such as keeping the evidence "
                "bundle attached.\n\n"
                f"SUBJECT path={subject_path.as_posix()}\n{subject_text}\n\n"
                f"LOCAL EVIDENCE\n{evidence_block}"
            ),
        },
    ]


def _review_repair_messages(
    *,
    previous_response: str,
    issues: list[str],
    evidence: list[LLMEvidenceArtifact],
) -> list[dict[str, str]]:
    issue_text = "; ".join(issues[:10])
    allowed_ids = ", ".join(artifact.evidence_id for artifact in evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are repairing a failed AI-Researcher local-evidence review response. "
                "Return only one syntactically valid JSON object. Do not include markdown "
                "fences, comments, URLs, quoted JSON arrays, or new uncited claims. "
                "Agent profile context is process metadata only; it cannot prove scientific "
                "results, publication readiness, or tool invocation."
            ),
        },
        {
            "role": "user",
            "content": (
                "The previous review response failed deterministic local quality checks. "
                f"Failed checks and parser errors: {issue_text}. "
                "Return a corrected object with exactly these keys and value types: "
                '{"verdict":"pass|needs_revision|fail","summary":"...",'
                '"findings":[{"severity":"info|warning|blocking","claim":"...",'
                '"evidence_refs":["evidence_1"]}],"unsupported_claims":["..."],'
                '"next_steps":["..."]}. '
                "All array fields must be real JSON arrays, not quoted strings. "
                f"Allowed evidence_refs values are exactly: {allowed_ids}. "
                "Do not cite file paths, URLs, paper titles, source_run_id values, or "
                "nested evidence ids. Do not add findings that were not in the previous "
                "response. If a previous finding lacks an allowed evidence ref, move its "
                "claim into unsupported_claims instead of guessing a ref. next_steps must "
                "contain at least one non-empty string. Use verdict `pass` when "
                "unsupported_claims is empty and all findings are informational; use "
                "`needs_revision` only for a concrete revision item.\n\n"
                f"Previous invalid response:\n{previous_response[:3000]}"
            ),
        },
    ]


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
        raise LLMClientError(
            "LLM API message content is empty; if you manually set --max-tokens, "
            "remove it or raise the provider-specific value",
            response_text=content if isinstance(content, str) else None,
            response_usage=(
                response.get("usage", {})
                if isinstance(response.get("usage"), dict)
                else {}
            ),
            finish_reason=_response_finish_reason(response),
        )
    return content.strip()


def _response_finish_reason(response: dict[str, Any]) -> str | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    finish_reason = first.get("finish_reason")
    return finish_reason if isinstance(finish_reason, str) else None


def _finding_evidence_refs(findings: Any) -> list[list[str]]:
    if not isinstance(findings, list):
        return []
    refs_by_finding: list[list[str]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            refs_by_finding.append([])
            continue
        refs = finding.get("evidence_refs")
        if not isinstance(refs, list):
            refs_by_finding.append([])
            continue
        refs_by_finding.append([ref for ref in refs if isinstance(ref, str) and ref.strip()])
    return refs_by_finding


def _review_misuses_profile_context(findings: Any) -> bool:
    if not isinstance(findings, list):
        return False
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        claim = finding.get("claim")
        if isinstance(claim, str) and _misuses_profile_context_as_evidence(claim):
            return True
    return False


def _misuses_profile_context_as_evidence(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in PROFILE_CONTEXT_NEGATION_TERMS):
        return False
    return (
        any(term in lower for term in PROFILE_CONTEXT_TERMS)
        and any(term in lower for term in PROFILE_PROOF_TERMS)
        and any(term in lower for term in PROFILE_SCIENTIFIC_CLAIM_TERMS)
    )


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


def _parse_json_completion_content(
    text: str,
) -> tuple[
    object,
    Literal[
        "none",
        "discarded_trailing_closing_delimiters",
        "discarded_leading_self_revision",
    ],
    str | None,
]:
    """Parse JSON with narrow, auditable provider transport normalizations."""

    stripped = _strip_json_fences(text)
    try:
        return json.loads(stripped), "none", None
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data":
            raise
    decoder = json.JSONDecoder()
    parsed, end = decoder.raw_decode(stripped)
    suffix = stripped[end:]
    delimiters = suffix.strip()
    if 1 <= len(suffix) <= 4 and delimiters and set(delimiters) <= {"]", "}"}:
        return parsed, "discarded_trailing_closing_delimiters", suffix
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Extra data", stripped, end)
    final_candidate: tuple[dict[str, Any], int] | None = None
    for position in range(end, len(stripped)):
        if stripped[position] != "{":
            continue
        try:
            candidate, candidate_end = decoder.raw_decode(stripped, position)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, dict)
            and not stripped[candidate_end:].strip()
            and set(candidate) == set(parsed)
        ):
            final_candidate = (candidate, position)
    if final_candidate is None:
        raise json.JSONDecodeError("Extra data", stripped, end)
    candidate, position = final_candidate
    stripped_offset = text.find(stripped)
    if stripped_offset < 0:
        raise json.JSONDecodeError("Extra data", stripped, end)
    discarded_prefix = text[: stripped_offset + position]
    if not 1 <= len(discarded_prefix) <= 200_000:
        raise json.JSONDecodeError("Extra data", stripped, end)
    return candidate, "discarded_leading_self_revision", discarded_prefix


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
