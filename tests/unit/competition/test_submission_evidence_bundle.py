"""Task 270.4: one missing proof must keep the submission bundle blocked."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_final_research_report import _lineage  # type: ignore[import-not-found]

from autoresearch.competition import submission_evidence_bundle as evidence_bundle
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    OfficialDevelopmentSearchPackage,
)
from autoresearch.competition.publication_signature import (
    ed25519_public_key_fingerprint,
    publication_signature_message,
)
from autoresearch.competition.submission_evidence_bundle import (
    HumanPublicationAuthorization,
    IndependentReexecutionManifest,
    IndependentReexecutionReceipt,
    SubmissionEvidenceBundle,
    SubmissionEvidenceError,
    audit_submission_evidence_bundle,
    human_publication_authorization_request_hash,
    run_submission_quality_gates,
)
from autoresearch.knowledge.raw_memory import RawMemorySourceKind, RawMemoryStore
from autoresearch.schemas import file_hash

ROOT = Path(__file__).resolve().parents[3]
_COMMIT = "a" * 40


def _checks(bundle: SubmissionEvidenceBundle) -> dict[str, bool]:
    return {item.name: item.passed for item in bundle.checks}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ("git", *args),
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _clean_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    (repo / ".gitignore").write_text(
        (
            ".pytest_cache/\n"
            "config.local.yaml\n"
            ".env\n"
            "config.yaml\n"
            "autoresearch-vault/_private/\n"
        ),
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=AutoResearch Tests",
        "-c",
        "user.email=autoresearch@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "base",
    )
    return repo


def _write_model_config(repo: Path) -> Path:
    config = repo / "config.yaml"
    config.write_text(
        """\
deployment:
  llm:
    provider: qwen-dashscope
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model_name: qwen3.7-max
    api_key_env: TEST_QWEN_API_KEY
""",
        encoding="utf-8",
    )
    return config


def _mock_green_quality_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = {
        "pytest": "1 passed in 0.01s\n",
        "ruff": "All checks passed!\n",
        "mypy": "Success: no issues found\n",
    }
    commands = evidence_bundle._canonical_quality_commands()

    def fake_run(
        command: tuple[str, ...] | list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        normalized = tuple(command)
        if normalized[:2] == ("git", "rev-parse"):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=_COMMIT + "\n",
                stderr="",
            )
        if normalized[:2] == ("git", "status"):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
        if normalized[:2] == ("git", "ls-files"):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
        for name, expected in commands.items():
            if normalized == expected:
                assert kwargs.get("cwd") is not None
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=outputs[name],
                    stderr="",
                )
        raise AssertionError(f"unexpected subprocess command: {normalized}")

    monkeypatch.setattr(evidence_bundle.subprocess, "run", fake_run)


def _write_reexecution_evidence(
    *, lineage: Path, package: OfficialDevelopmentSearchPackage
) -> IndependentReexecutionReceipt:
    output_directory = lineage / "independent-reexecution-output"
    output_directory.mkdir()
    entries: list[dict[str, object]] = []
    for result in package.cell_results:
        path = output_directory / f"{result.attempt_id}.json"
        path.write_text(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        entries.append(
            {
                "attempt_id": result.attempt_id,
                "relative_path": path.relative_to(output_directory).as_posix(),
                "sha256": file_hash(path),
                "byte_count": path.stat().st_size,
            }
        )
    manifest_path = output_directory / "reexecution-manifest.json"
    manifest_payload: dict[str, object] = {
        "schema_version": "independent-reexecution-manifest-v1",
        "lineage_id": lineage.name,
        "package_hash": package.package_hash,
        "source_commit": _COMMIT,
        "cell_artifacts": entries,
    }
    manifest_payload["manifest_hash"] = canonical_model_hash(manifest_payload)
    manifest_payload["output_path"] = manifest_path.as_posix()
    manifest = IndependentReexecutionManifest.model_validate(manifest_payload)
    manifest_path.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = lineage / "independent-reexecution-receipt.json"
    receipt_payload: dict[str, object] = {
        "schema_version": "independent-reexecution-receipt-v2",
        "lineage_id": lineage.name,
        "package_hash": package.package_hash,
        "source_commit": _COMMIT,
        "clean_output_directory": output_directory.relative_to(lineage).as_posix(),
        "artifact_manifest_relative_path": manifest_path.relative_to(
            output_directory
        ).as_posix(),
        "artifact_manifest_sha256": file_hash(manifest_path),
        "artifact_manifest_byte_count": manifest_path.stat().st_size,
        "artifact_manifest_hash": manifest.manifest_hash,
        "reexecuted_cell_count": len(entries),
        "expected_cell_count": len(entries),
        "all_cells_reexecuted": True,
        "aggregate_metrics_match": True,
        "gate_verdict_matches": True,
        "network_disabled": True,
        "passed": True,
        "created_at": "2026-08-09T08:00:00Z",
    }
    receipt_payload["receipt_hash"] = canonical_model_hash(receipt_payload)
    receipt_payload["output_path"] = receipt_path.as_posix()
    return IndependentReexecutionReceipt.model_validate(receipt_payload)


def _replace_reexecution_receipt(
    receipt: IndependentReexecutionReceipt, **updates: object
) -> IndependentReexecutionReceipt:
    payload = receipt.model_dump(mode="json")
    payload.update(updates)
    payload["receipt_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"receipt_hash", "output_path"}
        }
    )
    return IndependentReexecutionReceipt.model_validate(payload)


def _human_authorization_payload(lineage_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "human-publication-authorization-v2",
        "lineage_id": lineage_id,
        "decision": "authorize",
        "authorized_by": "提交负责人",
        "authorization_statement": (
            "我已审阅并授权将上述哈希绑定的材料用于本次提交；"
            "该授权仅是发表与提交决定，不构成科学证据。"
        ),
        "notes": "已核对最终中文报告、复现材料与全部冻结门禁。",
        "plan_artifact_hash": "1" * 64,
        "plan_decision_file_sha256": "2" * 64,
        "signed_package_hash": "3" * 64,
        "outcome_hash": "4" * 64,
        "final_report_hash": "5" * 64,
        "final_report_build_receipt_hash": "6" * 64,
        "innovation_audit_hash": "7" * 64,
        "reexecution_receipt_hash": "8" * 64,
        "quality_gate_receipt_hash": "9" * 64,
        "source_commit": _COMMIT,
        "authorized_at": "2026-08-09T08:00:00Z",
        "authored_by_model": False,
        "is_scientific_evidence": False,
        "evidence_refs": (),
        "changes_scientific_verdict": False,
    }
    payload["authorization_request_hash"] = (
        human_publication_authorization_request_hash(payload)
    )
    payload["signature_base64"] = "detached-signature-placeholder"
    payload["signer_public_key_pem"] = "external-public-key-placeholder"
    payload["signer_public_key_sha256"] = "c" * 64
    payload["authorization_hash"] = canonical_model_hash(payload)
    payload["output_path"] = "human-publication-authorization.json"
    return payload


def _sign_authorization_payload(
    payload: dict[str, object], private_key: Ed25519PrivateKey
) -> tuple[dict[str, object], str]:
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    signed = dict(payload)
    signed["signature_base64"] = base64.b64encode(
        private_key.sign(
            publication_signature_message(str(signed["authorization_request_hash"]))
        )
    ).decode("ascii")
    signed["signer_public_key_pem"] = public_pem
    signed["signer_public_key_sha256"] = ed25519_public_key_fingerprint(public_pem)
    signed["authorization_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in signed.items()
            if key not in {"authorization_hash", "output_path"}
        }
    )
    return signed, str(signed["signer_public_key_sha256"])


@pytest.mark.parametrize(
    "relative_path",
    (
        "src/new_module.py",
        "skills/domain/SKILL.md",
        "config.local.yaml",
        "docs/submission.md",
    ),
)
def test_worktree_gate_rejects_untracked_submission_inputs(
    tmp_path: Path,
    relative_path: str,
) -> None:
    repo = _clean_repository(tmp_path)
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("untracked\n", encoding="utf-8")

    assert evidence_bundle._tracked_worktree_clean(repo) is False


@pytest.mark.parametrize(
    "relative_path",
    ("runs/lineage/result.json", ".pytest_cache/v/cache/nodeids"),
)
def test_worktree_gate_allows_only_lineage_outputs_and_caches(
    tmp_path: Path,
    relative_path: str,
) -> None:
    repo = _clean_repository(tmp_path)
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("runtime output\n", encoding="utf-8")

    assert evidence_bundle._tracked_worktree_clean(repo) is True


def test_worktree_gate_still_rejects_unstaged_and_staged_changes(
    tmp_path: Path,
) -> None:
    repo = _clean_repository(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("changed\n", encoding="utf-8")

    assert evidence_bundle._tracked_worktree_clean(repo) is False

    _git(repo, "add", "tracked.txt")
    assert evidence_bundle._tracked_worktree_clean(repo) is False


def test_worktree_gate_allows_only_hash_bound_canonical_config_and_local_env(
    tmp_path: Path,
) -> None:
    repo = _clean_repository(tmp_path)
    config = _write_model_config(repo)
    (repo / ".env").write_text("TEST_QWEN_API_KEY=local-only\n", encoding="utf-8")
    config_hash = file_hash(config)

    assert evidence_bundle._tracked_worktree_clean(repo) is False
    assert (
        evidence_bundle._tracked_worktree_clean(
            repo, expected_config_sha256=config_hash
        )
        is True
    )

    config.write_text(config.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert (
        evidence_bundle._tracked_worktree_clean(
            repo, expected_config_sha256=config_hash
        )
        is False
    )


def test_worktree_gate_allows_verified_sovereign_memory_but_rejects_extra_files(
    tmp_path: Path,
) -> None:
    repo = _clean_repository(tmp_path)
    store = RawMemoryStore(repo / "autoresearch-vault")
    store.capture_text(
        "仅用于验证私有原始记忆不会污染源码洁净门。",
        project_id="quality-test",
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="质量门测试",
        source_ref="test-user-input",
        original_name="memory.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
    )

    assert evidence_bundle._tracked_worktree_clean(repo) is True

    injected = repo / "autoresearch-vault" / "_private" / "injected.py"
    injected.write_text("raise RuntimeError('must not be reachable')\n", encoding="utf-8")
    assert evidence_bundle._tracked_worktree_clean(repo) is False


def test_submission_artifact_inventory_rejects_secret_env_and_raw_memory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    secret = repo / ".env"
    raw_blob = (
        repo
        / "autoresearch-vault"
        / "_private"
        / "raw-memory"
        / "blobs"
        / "sha256"
        / "aa"
        / ("a" * 64 + ".blob")
    )
    secret.parent.mkdir(parents=True)
    raw_blob.parent.mkdir(parents=True)
    secret.write_text("SECRET=never-package\n", encoding="utf-8")
    raw_blob.write_bytes(b"private")

    with pytest.raises(SubmissionEvidenceError, match=r"\.env"):
        evidence_bundle._require_submission_artifact_is_public(repo=repo, path=secret)
    with pytest.raises(SubmissionEvidenceError, match="raw memory"):
        evidence_bundle._require_submission_artifact_is_public(
            repo=repo, path=raw_blob
        )


def test_worktree_gate_rejects_tracked_private_runtime_even_when_unchanged(
    tmp_path: Path,
) -> None:
    repo = _clean_repository(tmp_path)
    (repo / ".env").write_text("TEST_QWEN_API_KEY=tracked\n", encoding="utf-8")
    _git(repo, "add", "--force", ".env")
    _git(
        repo,
        "-c",
        "user.name=AutoResearch Tests",
        "-c",
        "user.email=autoresearch@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "forbidden tracked private state",
    )

    assert evidence_bundle._tracked_worktree_clean(repo) is False


@pytest.mark.parametrize(
    "status_output",
    (b"?? runs/../src/injected.py\0", b"?? __pycache__\0", b"?? C:/escape.py\0"),
)
def test_worktree_gate_rejects_malformed_or_escaping_status_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_output: bytes,
) -> None:
    def fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args="git",
            returncode=0,
            stdout=status_output,
            stderr=b"",
        )

    monkeypatch.setattr(evidence_bundle.subprocess, "run", fake_run)

    assert evidence_bundle._tracked_worktree_clean(tmp_path) is False


def test_quality_gate_rejects_three_green_noop_commands(tmp_path: Path) -> None:
    noops = {
        name: (sys.executable, "-c", "raise SystemExit(0)")
        for name in ("pytest", "ruff", "mypy")
    }

    with pytest.raises(SubmissionEvidenceError, match="frozen production contract"):
        run_submission_quality_gates(
            repository_root=tmp_path,
            output_dir=tmp_path / "quality",
            commands=noops,
        )


def test_quality_receipt_binds_full_config_bytes_without_collecting_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_model_config(tmp_path)
    (tmp_path / ".env").write_text(
        "TEST_QWEN_API_KEY=must-never-enter-receipt\n", encoding="utf-8"
    )
    _mock_green_quality_subprocess(monkeypatch)
    receipt = run_submission_quality_gates(
        repository_root=tmp_path,
        output_dir=tmp_path / "quality",
        config_path=config,
        clock=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
    )
    serialized = json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False)

    assert receipt.configuration_sha256 == file_hash(config)
    assert "must-never-enter-receipt" not in serialized
    assert "TEST_QWEN_API_KEY=must" not in serialized

    config.write_text(config.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(SubmissionEvidenceError, match="configuration bytes"):
        evidence_bundle._verify_quality_runtime_configuration(
            receipt=receipt, repository_root=tmp_path
        )


def test_quality_gate_rejects_secret_literal_in_yaml_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_model_config(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8") + "# sk-0123456789abcdef0123456789\n",
        encoding="utf-8",
    )
    _mock_green_quality_subprocess(monkeypatch)

    with pytest.raises(SubmissionEvidenceError, match="credential"):
        run_submission_quality_gates(
            repository_root=tmp_path,
            output_dir=tmp_path / "quality",
            config_path=config,
        )


@pytest.mark.parametrize("mutation", ("missing", "tampered"))
def test_reused_quality_receipt_requires_every_hashed_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    lineage = _lineage(tmp_path)
    destination = lineage / "submission-evidence"
    config = _write_model_config(tmp_path)
    _mock_green_quality_subprocess(monkeypatch)
    receipt = run_submission_quality_gates(
        repository_root=tmp_path,
        output_dir=destination,
        config_path=config,
        clock=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
    )
    assert receipt.schema_version == "submission-quality-gate-receipt-v3"
    assert receipt.configuration_sha256 == file_hash(config)
    assert receipt.local_secret_env_excluded is True
    assert receipt.sovereign_raw_memory_excluded is True
    pytest_log = destination / "quality-logs" / "pytest.log"
    if mutation == "missing":
        pytest_log.unlink()
    else:
        pytest_log.write_text("forged green log\n", encoding="utf-8")

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=tmp_path,
        run_quality_gates=False,
    )

    quality_check = next(
        item for item in bundle.checks if item.name == "broad_quality_gates"
    )
    assert quality_check.passed is False
    assert any("quality log" in finding for finding in quality_check.findings)


def test_existing_authorization_freezes_quality_receipt_instead_of_rerunning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lineage = _lineage(tmp_path)
    (lineage / "human-publication-authorization.json").write_text(
        "{}\n", encoding="utf-8"
    )

    def forbidden_rerun(**_kwargs: object) -> None:
        pytest.fail("an existing authorization must freeze the quality receipt")

    monkeypatch.setattr(
        evidence_bundle, "run_submission_quality_gates", forbidden_rerun
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=True,
    )

    assert _checks(bundle)["broad_quality_gates"] is False
    assert _checks(bundle)["human_publication_authorization"] is False


def test_submission_paths_reject_project_and_quality_receipt_escape(
    tmp_path: Path,
) -> None:
    lineage = tmp_path / "lineage"
    lineage.mkdir()
    outside = tmp_path / "outside" / "submission-quality-gate-receipt.json"

    with pytest.raises(SubmissionEvidenceError, match="越出谱系目录"):
        evidence_bundle._plan_decision_path(lineage, "../../outside")
    with pytest.raises(SubmissionEvidenceError, match="越出谱系目录"):
        evidence_bundle._contained_quality_receipt_path(lineage, outside)
    with pytest.raises(SubmissionEvidenceError, match="canonical receipt filename"):
        evidence_bundle._contained_quality_receipt_path(
            lineage, lineage / "submission-evidence" / "forged.json"
        )


def test_reexecution_rejects_stale_commit_before_trusting_receipt(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (lineage / "official-development-search-package.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = _write_reexecution_evidence(lineage=lineage, package=package)

    with pytest.raises(SubmissionEvidenceError, match="source commit differ"):
        evidence_bundle._verify_reexecution_evidence(
            root=lineage,
            package=package,
            receipt=receipt,
            current_source_commit="b" * 40,
            quality_source_commit="b" * 40,
        )


@pytest.mark.parametrize(
    ("clean_output_directory", "error"),
    (("../outside", "越出谱系目录"), ("missing", "output directory is missing")),
)
def test_reexecution_clean_output_directory_is_contained_and_present(
    tmp_path: Path,
    clean_output_directory: str,
    error: str,
) -> None:
    lineage = _lineage(tmp_path)
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (lineage / "official-development-search-package.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = _replace_reexecution_receipt(
        _write_reexecution_evidence(lineage=lineage, package=package),
        clean_output_directory=clean_output_directory,
    )

    with pytest.raises(SubmissionEvidenceError, match=error):
        evidence_bundle._verify_reexecution_evidence(
            root=lineage,
            package=package,
            receipt=receipt,
            current_source_commit=_COMMIT,
            quality_source_commit=_COMMIT,
        )


def test_reexecution_rejects_missing_raw_cell_even_with_green_self_report(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (lineage / "official-development-search-package.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = _write_reexecution_evidence(lineage=lineage, package=package)
    manifest_path = (
        lineage
        / receipt.clean_output_directory
        / receipt.artifact_manifest_relative_path
    )
    manifest = IndependentReexecutionManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    missing = lineage / receipt.clean_output_directory / manifest.cell_artifacts[0].relative_path
    missing.unlink()

    with pytest.raises(SubmissionEvidenceError, match="cell result is missing"):
        evidence_bundle._verify_reexecution_evidence(
            root=lineage,
            package=package,
            receipt=receipt,
            current_source_commit=_COMMIT,
            quality_source_commit=_COMMIT,
        )


def test_reexecution_verifies_manifest_and_every_raw_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lineage = _lineage(tmp_path)
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (lineage / "official-development-search-package.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = _write_reexecution_evidence(lineage=lineage, package=package)
    monkeypatch.setattr(evidence_bundle, "_replay_findings", lambda _package: ())

    verified = evidence_bundle._verify_reexecution_evidence(
        root=lineage,
        package=package,
        receipt=receipt,
        current_source_commit=_COMMIT,
        quality_source_commit=_COMMIT,
    )

    assert len(verified) == len(package.cell_results) + 1
    assert all(path.is_file() for path in verified)


def test_bundle_is_written_but_never_ready_with_missing_required_proofs(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    checks = _checks(bundle)
    assert bundle.submission_ready is False
    assert bundle.publication_ready is False
    assert checks["publication_readiness"] is False
    assert checks["human_publication_authorization"] is False
    assert checks["required_audits_present"] is False
    assert checks["broad_quality_gates"] is False
    assert checks["innovation_evidence_audited"] is False
    assert checks["independent_scientific_reexecution"] is False
    assert checks["plan_to_code_alignment"] is True
    assert bundle.human_approval_is_scientific_evidence is False
    assert Path(bundle.output_path).is_file()
    markdown = Path(bundle.output_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "禁止宣称可提交" in markdown
    assert "不生成研究假设、结果解释或创新性主张" in markdown


def test_submission_audit_refuses_a_valid_legacy_plan_artifact(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    artifact_path = lineage / "system-authored-research-plan.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "system-authored-research-plan-v1"
    payload.pop("scientific_lineage_binding")
    payload.pop("scientific_lineage_attestation")
    payload["artifact_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "output_path"}
        }
    )
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    checks = _checks(bundle)
    assert checks["plan_model_authorship_provenance"] is False
    assert checks["plan_to_code_alignment"] is False
    assert bundle.submission_ready is False
    with pytest.raises(SubmissionEvidenceError, match="Artifact v2"):
        evidence_bundle.prepare_human_publication_authorization_request(
            lineage_dir=lineage,
            authorized_by="提交负责人",
            notes="仅用于验证旧式计划不能进入外部签名请求。",
            repository_root=ROOT,
        )


def test_configured_and_recorded_model_identity_mismatch_blocks(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    config = tmp_path / "mismatch.yaml"
    config.write_text(
        """\
deployment:
  llm:
    provider: another-provider
    base_url: https://example.invalid/v1
    model_name: another-model
    api_key_env: TEST_KEY
""",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=config,
        repository_root=ROOT,
        run_quality_gates=False,
    )

    assert _checks(bundle)["configured_model_identity_matches"] is False
    assert bundle.submission_ready is False


def test_red_broad_quality_command_blocks_even_when_receipt_exists(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    commands = {
        "pytest": (sys.executable, "-c", "print('1 passed')"),
        "ruff": (sys.executable, "-c", "raise SystemExit(1)"),
        "mypy": (sys.executable, "-c", "print('Success')"),
    }
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=True,
        quality_commands=commands,
    )

    assert _checks(bundle)["broad_quality_gates"] is False
    assert bundle.submission_ready is False


def test_hash_valid_package_with_missing_observed_metric_is_still_blocked(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    package_path = lineage / "official-development-search-package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["overall_median_log_effect"] = None
    payload["package_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"package_hash", "output_path"}
        }
    )
    package_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    package_check = next(
        item for item in bundle.checks if item.name == "signed_package_semantics"
    )
    assert package_check.passed is False
    assert any("缺少总体" in finding for finding in package_check.findings)
    assert bundle.submission_ready is False


def test_schema_forbids_submission_ready_while_publication_is_false(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )
    payload = bundle.model_dump(mode="json")
    payload["submission_ready"] = True
    payload["bundle_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"bundle_hash", "output_path"}
        }
    )

    with pytest.raises(SubmissionEvidenceError, match="submission-ready"):
        SubmissionEvidenceBundle.model_validate(payload)


def test_schema_forbids_publication_ready_when_secret_gate_is_red(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )
    payload = bundle.model_dump(mode="json")
    for check in payload["checks"]:
        if check["name"] == "publication_readiness":
            check["passed"] = True
            check["findings"] = []
        elif check["name"] == "secrets_absent":
            check["passed"] = False
            check["findings"] = ["检测到凭据值。"]
    payload["publication_ready"] = True
    payload["submission_ready"] = False
    payload["blocking_findings"] = [
        finding for check in payload["checks"] for finding in check["findings"]
    ]
    payload["bundle_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"bundle_hash", "output_path"}
        }
    )

    with pytest.raises(SubmissionEvidenceError, match="publication flag"):
        SubmissionEvidenceBundle.model_validate(payload)


def test_human_publication_authorization_is_hash_bound_and_never_evidence() -> None:
    payload = _human_authorization_payload("lineage-under-test")

    authorization = HumanPublicationAuthorization.model_validate(payload)

    assert authorization.decision == "authorize"
    assert authorization.is_scientific_evidence is False
    assert authorization.evidence_refs == ()

    tampered = dict(payload)
    tampered["final_report_hash"] = "b" * 64
    with pytest.raises(SubmissionEvidenceError, match="request hash mismatch"):
        HumanPublicationAuthorization.model_validate(tampered)


def test_legacy_unsigned_authorization_schema_fails_closed() -> None:
    legacy = _human_authorization_payload("lineage-under-test")
    legacy["schema_version"] = "human-publication-authorization-v1"
    for field_name in (
        "authorization_request_hash",
        "signature_base64",
        "signer_public_key_pem",
        "signer_public_key_sha256",
    ):
        legacy.pop(field_name)

    with pytest.raises(ValueError):
        HumanPublicationAuthorization.model_validate(legacy)


def test_authorization_without_external_trust_anchor_stays_red(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    authorization_path = lineage / "human-publication-authorization.json"
    authorization_path.write_text(
        json.dumps(
            _human_authorization_payload(lineage.name),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    authorization_check = next(
        item
        for item in bundle.checks
        if item.name == "human_publication_authorization"
    )
    assert authorization_check.passed is False
    assert any("外部可信" in finding for finding in authorization_check.findings)


def test_self_minted_authorization_key_cannot_replace_external_trust(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    attacker_payload, _ = _sign_authorization_payload(
        _human_authorization_payload(lineage.name), Ed25519PrivateKey.generate()
    )
    trusted_private = Ed25519PrivateKey.generate()
    trusted_pem = trusted_private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    authorization_path = lineage / "human-publication-authorization.json"
    authorization_path.write_text(
        json.dumps(attacker_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
        trusted_publication_key_sha256=ed25519_public_key_fingerprint(trusted_pem),
    )

    authorization_check = next(
        item
        for item in bundle.checks
        if item.name == "human_publication_authorization"
    )
    assert authorization_check.passed is False
    assert any("外部签名无效" in finding for finding in authorization_check.findings)
