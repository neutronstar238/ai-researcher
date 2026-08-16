"""Secret 扫描（spec §19.7/§23.3）：在仓库内 grep 常见密钥模式。

排除 .env / node_modules / .venv / dist / 快照等。命中即退出码 1，供 CI 使用。
用法：cd backend && .\.venv\Scripts\python.exe scripts/scan_secrets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 常见密钥模式（命中需人工复核；.env.example 允许空占位）
PATTERNS = [
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/LLM API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key"),
    (r"password\s*=\s*[\"'][^\"']{8,}[\"']", "hardcoded password"),
    (r"secret\s*=\s*[\"'][^\"']{8,}[\"']", "hardcoded secret"),
]

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock", ".woff", ".woff2"}
EXCLUDE_FILES = {".env", ".env.example", "package-lock.json"}


def scan() -> list[str]:
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        parts = set(rel.parts)
        if parts & EXCLUDE_DIRS:
            continue
        if path.name in EXCLUDE_FILES or path.suffix in EXCLUDE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in PATTERNS:
            if re.search(pattern, text):
                hits.append(f"{rel}: {label}")
                break
    return hits


def main() -> int:
    hits = scan()
    if hits:
        print("发现潜在密钥：")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("未发现硬编码密钥")
    return 0


if __name__ == "__main__":
    sys.exit(main())
