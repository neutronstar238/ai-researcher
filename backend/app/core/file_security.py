"""文件安全（spec §19.4）：大小上限 + Magic Bytes 校验。

原始文件名只作显示（Object Key 服务端生成），上传完成时服务端校验：
- 大小 ≤ ``max_upload_bytes``（默认 500 MiB）。
- 声明 MIME 有固定签名时，文件头必须匹配（PDF/PNG/JPEG/ZIP 等）。
无固定签名的类型（text/*、application/json、application/octet-stream）跳过校验。
完整 quarantine + 恶意扫描（ClamAV）需外部扫描器，见 docs/security.md 遗留项。
"""

from __future__ import annotations

# MIME → 允许的文件头签名；None 表示该类型无固定 magic，跳过校验。
MAGIC_SIGNATURES: dict[str, list[bytes] | None] = {
    "application/pdf": [b"%PDF"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "application/zip": [b"PK\x03\x04"],
    "application/gzip": [b"\x1f\x8b"],
}


def magic_bytes_matches(mime_type: str | None, head: bytes) -> bool:
    signatures = MAGIC_SIGNATURES.get(mime_type or "")
    if signatures is None:
        return True  # 无签名可校验
    return any(head.startswith(sig) for sig in signatures)
