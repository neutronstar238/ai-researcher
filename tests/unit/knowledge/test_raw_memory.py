from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.knowledge.raw_memory import (
    DreamingMemoryContent,
    MemoryClaimAssessment,
    MemoryClaimVerdict,
    RawMemoryIntegrityError,
    RawMemoryPolicyError,
    RawMemorySourceKind,
    RawMemoryStore,
)

CAPTURED_AT = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def _capture(store: RawMemoryStore, payload: str = "原始文章全文"):
    return store.capture_text(
        payload,
        project_id="ai_researcher_system",
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="用户提供的记忆架构文章",
        source_ref="conversation:memory-article",
        original_name="memory-article.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=CAPTURED_AT,
    )


def test_raw_capture_is_private_content_addressed_and_does_not_store_source_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside" / "article.txt"
    source.parent.mkdir()
    source.write_text("逐字保留的原始材料", encoding="utf-8")
    store = RawMemoryStore(tmp_path / "autoresearch-vault")

    capture = store.capture_file(
        source,
        project_id="ai_researcher_system",
        source_kind=RawMemorySourceKind.USER_ATTACHMENT,
        source_label="用户附件",
        source_ref="attachment:article.txt",
        media_type="text/plain",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=CAPTURED_AT,
    )

    assert capture.blob_path.read_bytes() == source.read_bytes()
    assert capture.record_path.is_relative_to(
        (tmp_path / "autoresearch-vault" / "_private" / "raw-memory").resolve()
    )
    assert capture.record.envelope.visibility == "private-local"
    assert capture.record.envelope.write_policy == "append-only"
    assert capture.record.envelope.schema_version == 2
    assert capture.blob_path.suffix == ".blob"
    assert str(source.resolve()) not in capture.record_path.read_text(encoding="utf-8")
    store.verify_capture(capture)


def test_exact_retry_is_idempotent_but_distinct_capture_keeps_distinct_record(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    first = _capture(store)
    retry = _capture(store)
    later = store.capture_text(
        "原始文章全文",
        project_id="ai_researcher_system",
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="第二个来源",
        source_ref="conversation:memory-article-copy",
        original_name="memory-article.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=datetime(2026, 8, 9, 8, 1, tzinfo=timezone.utc),
    )

    assert retry.record_path == first.record_path
    assert retry.blob_path == first.blob_path
    assert later.record_path != first.record_path
    assert later.blob_path == first.blob_path


@pytest.mark.parametrize(
    ("authorized", "reviewed"),
    [(False, True), (True, False), (False, False)],
)
def test_capture_requires_authorization_and_sensitive_review(
    tmp_path: Path, authorized: bool, reviewed: bool
) -> None:
    store = RawMemoryStore(tmp_path / "vault")

    with pytest.raises(RawMemoryPolicyError):
        store.capture_text(
            "safe payload",
            project_id="project",
            source_kind=RawMemorySourceKind.USER_TEXT,
            source_label="source",
            source_ref="conversation:item",
            original_name="item.txt",
            source_authorized=authorized,
            sensitive_content_reviewed=reviewed,
            captured_at=CAPTURED_AT,
        )


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        (".env", "SAFE=value"),
        ("private-key.pem", "not even a real key"),
        ("note.txt", "Authorization: Bearer abcdefghijklmnop"),
        ("note.txt", "contact researcher@example.org"),
        ("note.txt", "contact 研究者@例子.公司"),
        ("note.txt", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"),
        ("note.txt", "api_key=DUMMYSECRET12345678"),
        (
            "note.txt",
            "-----BEGIN PRIVATE KEY-----\nmaterial\n-----END RSA PRIVATE KEY-----",
        ),
    ],
)
def test_capture_refuses_secret_like_files_credentials_and_direct_identifiers(
    tmp_path: Path, name: str, payload: str
) -> None:
    store = RawMemoryStore(tmp_path / "vault")

    with pytest.raises(RawMemoryPolicyError):
        store.capture_text(
            payload,
            project_id="project",
            source_kind=RawMemorySourceKind.USER_TEXT,
            source_label="source",
            source_ref="conversation:item",
            original_name=name,
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=CAPTURED_AT,
        )


def test_raw_capture_allows_bearer_noun_phrase(tmp_path: Path) -> None:
    store = RawMemoryStore(tmp_path / "vault")

    capture = store.capture_text(
        "The bearer certificate remained valid.",
        project_id="project",
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="source",
        source_ref="conversation:item",
        original_name="item.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=CAPTURED_AT,
    )

    store.verify_capture(capture)


def test_tampered_payload_and_record_fail_closed(tmp_path: Path) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)
    capture.blob_path.write_bytes(b"tampered")

    with pytest.raises(RawMemoryIntegrityError, match="payload"):
        store.verify_capture(capture)

    capture.blob_path.write_text("原始文章全文", encoding="utf-8")
    capture.record_path.write_text(
        capture.record_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(RawMemoryIntegrityError, match="record"):
        store.load_record(
            capture.record_path.relative_to(store.vault_root),
            project_id="ai_researcher_system",
        )


def test_correction_appends_superseding_record_without_mutating_original(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    original = _capture(store, "原始版本")
    original_bytes = original.record_path.read_bytes()

    correction = store.capture_text(
        "更正版本",
        project_id="ai_researcher_system",
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="用户更正",
        source_ref="conversation:memory-article-correction",
        original_name="memory-article-correction.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=datetime(2026, 8, 9, 8, 2, tzinfo=timezone.utc),
        supersedes_record_id=original.record.record_id,
    )

    assert correction.record.envelope.supersedes_record_id == original.record.record_id
    assert original.record_path.read_bytes() == original_bytes
    assert correction.record_path != original.record_path


def test_dreaming_projection_is_rebuildable_and_hash_bound_to_raw_memory(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)
    raw_before = capture.record_path.read_bytes()
    content = DreamingMemoryContent(
        project_id="ai_researcher_system",
        title="大模型原生记忆与 Agent 原始记忆主权",
        generated_at=CAPTURED_AT,
        generator_identity="autoresearch-system",
        source_bindings=[capture.binding(store.vault_root)],
        summary="模型级记忆与应用级可迁移记忆承担不同责任。",
        claim_assessments=[
            MemoryClaimAssessment(
                claim="模型级记忆成为架构一等维度",
                verdict=MemoryClaimVerdict.SUPPORTED,
                rationale="原论文以表示、更新和持久性三个维度统一模型记忆。",
                evidence_refs=[
                    "raw:"
                    f"{capture.record.record_id}#sha256:"
                    f"{capture.record.envelope.payload_sha256}"
                ],
            )
        ],
        design_decisions=[
            "原始输入在本地私有区只追加保存。",
            "Dreaming 只生成可重建的派生视图。",
        ],
    )

    written = store.write_dreaming_projection(content)

    assert written.json_path.is_file()
    assert written.markdown_path.is_file()
    assert written.commit_path is not None and written.commit_path.is_file()
    markdown = written.markdown_path.read_text(encoding="utf-8")
    assert "这是可重建的 Dreaming 派生视图" in markdown
    assert "候选设计建议（未授权）" in markdown
    assert capture.record.record_hash in markdown
    assert capture.record_path.read_bytes() == raw_before
    store.verify_dreaming_projection(written)


def test_dreaming_rejects_tampered_source_binding(tmp_path: Path) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)
    binding = capture.binding(store.vault_root).model_copy(update={"payload_sha256": "0" * 64})
    content = DreamingMemoryContent(
        project_id="ai_researcher_system",
        title="派生视图",
        generated_at=CAPTURED_AT,
        generator_identity="autoresearch-system",
        source_bindings=[binding],
        summary="摘要",
        claim_assessments=[
            MemoryClaimAssessment(
                claim="论断",
                verdict=MemoryClaimVerdict.UNVERIFIED,
                rationale="没有足够证据。",
                evidence_refs=["raw:source"],
            )
        ],
        design_decisions=["保留原始记录。"],
    )

    with pytest.raises(RawMemoryIntegrityError, match="binding"):
        store.write_dreaming_projection(content)


def test_supported_claim_refuses_bare_url_without_exact_raw_binding(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)

    with pytest.raises(ValueError, match="exact bound raw-record"):
        DreamingMemoryContent(
            project_id="ai_researcher_system",
            title="不受原始记录约束的派生视图",
            generated_at=CAPTURED_AT,
            generator_identity="autoresearch-system",
            source_bindings=[capture.binding(store.vault_root)],
            summary="摘要",
            claim_assessments=[
                MemoryClaimAssessment(
                    claim="未经原始记录绑定的支持性断言",
                    verdict=MemoryClaimVerdict.SUPPORTED,
                    rationale="裸网址不能证明该断言来自已保存的原始字节。",
                    evidence_refs=["https://arxiv.org/abs/2607.25380"],
                )
            ],
            design_decisions=["保留原始记录。"],
        )


def test_dreaming_supersession_requires_a_verified_existing_projection(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)
    binding = capture.binding(store.vault_root)
    exact_ref = f"raw:{binding.record_id}#sha256:{binding.payload_sha256}"
    content = DreamingMemoryContent(
        project_id="ai_researcher_system",
        title="缺失前驱的派生视图",
        generated_at=CAPTURED_AT,
        generator_identity="autoresearch-system",
        source_bindings=[binding],
        summary="摘要",
        claim_assessments=[
            MemoryClaimAssessment(
                claim="论断",
                verdict=MemoryClaimVerdict.SUPPORTED,
                rationale="理由",
                evidence_refs=[exact_ref],
            )
        ],
        design_decisions=["保留原始记录。"],
        supersedes_projection_id=f"dream_{'0' * 64}",
    )

    with pytest.raises(RawMemoryIntegrityError, match="cannot load superseded"):
        store.write_dreaming_projection(content)


def test_dreaming_supersession_appends_a_verified_projection_chain(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)
    binding = capture.binding(store.vault_root)
    exact_ref = f"raw:{binding.record_id}#sha256:{binding.payload_sha256}"
    base = DreamingMemoryContent(
        project_id="ai_researcher_system",
        title="第一版派生视图",
        generated_at=CAPTURED_AT,
        generator_identity="autoresearch-system",
        source_bindings=[binding],
        summary="第一版摘要",
        claim_assessments=[
            MemoryClaimAssessment(
                claim="论断",
                verdict=MemoryClaimVerdict.SUPPORTED,
                rationale="理由",
                evidence_refs=[exact_ref],
            )
        ],
        design_decisions=["保留原始记录。"],
    )
    first = store.write_dreaming_projection(base)
    first_json = first.json_path.read_bytes()
    second = store.write_dreaming_projection(
        base.model_copy(
            update={
                "title": "第二版派生视图",
                "summary": "第二版摘要",
                "generated_at": datetime(2026, 8, 9, 8, 3, tzinfo=timezone.utc),
                "supersedes_projection_id": first.projection.projection_id,
            }
        )
    )

    assert second.projection.content.supersedes_projection_id == first.projection.projection_id
    assert first.json_path.read_bytes() == first_json
    store.load_dreaming_projection(
        second.projection.projection_id,
        project_id="ai_researcher_system",
    )


def test_concurrent_identical_capture_never_observes_partial_file(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")

    with ThreadPoolExecutor(max_workers=4) as pool:
        captures = list(pool.map(lambda _: _capture(store), range(8)))

    assert len({item.record.record_id for item in captures}) == 1
    assert len({item.record_path for item in captures}) == 1
    for capture in captures:
        store.verify_capture(capture)


def test_raw_record_lookup_is_project_isolated(tmp_path: Path) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    capture = _capture(store)

    with pytest.raises(RawMemoryIntegrityError, match="found 0"):
        store.find_record(capture.record.record_id, project_id="another_project")

    with pytest.raises(RawMemoryPolicyError, match="another project"):
        store.load_record(
            capture.record_path.relative_to(store.vault_root),
            project_id="another_project",
        )
