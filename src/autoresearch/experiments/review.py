"""Static review checks for generated experiment code."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodeReviewFinding:
    """One blocking generated-code review finding."""

    category: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "message": self.message,
            "line": self.line,
        }


@dataclass(frozen=True)
class CodeReviewResult:
    """Generated-code review outcome."""

    approved: bool
    findings: tuple[CodeReviewFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "findings": [finding.to_dict() for finding in self.findings],
        }


DANGEROUS_CALLS = {
    "eval",
    "exec",
    "os.popen",
    "os.system",
    "shutil.rmtree",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
}
DANGEROUS_IMPORT_ROOTS = {"subprocess"}
DANGEROUS_COMMAND_MARKERS = ("rm -rf", "del /", "remove-item", "curl ", "wget ")
NETWORK_IMPORT_ROOTS = {"aiohttp", "httpx", "requests", "socket", "urllib"}
SECRET_MARKERS = (".env", "api_key", "id_rsa", "secret", "token")
PATH_TRAVERSAL_PATTERN = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


def review_generated_code(
    experiment_dir: Path | str,
    entrypoint: str = "run.py",
) -> CodeReviewResult:
    """Review generated experiment code before local execution."""

    root = Path(experiment_dir).resolve()
    entrypoint_path = (root / entrypoint).resolve()
    findings: list[CodeReviewFinding] = []

    if not entrypoint_path.is_relative_to(root):
        findings.append(
            CodeReviewFinding(
                "path_traversal",
                "entrypoint resolves outside the experiment directory",
            )
        )
        return _result(findings)

    if not entrypoint_path.is_file():
        findings.append(CodeReviewFinding("missing_entrypoint", "run.py is missing"))
        return _result(findings)

    source = entrypoint_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        findings.append(
            CodeReviewFinding("syntax_error", exc.msg, line=exc.lineno)
        )
        return _result(findings)

    findings.extend(_review_imports(tree))
    findings.extend(_review_calls(tree))
    findings.extend(_review_attributes(tree))
    findings.extend(_review_string_literals(tree))
    findings.extend(_review_metric_write(tree))
    return _result(findings)


def quarantine_unsafe_experiment(
    experiment_dir: Path | str,
    result: CodeReviewResult | None = None,
) -> Path | None:
    """Write quarantine markers for unsafe generated code."""

    root = Path(experiment_dir)
    review_result = result or review_generated_code(root)
    if review_result.approved:
        return None

    quarantine_dir = root / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    findings_path = quarantine_dir / "review-findings.json"
    findings_path.write_text(
        json.dumps(review_result.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (root / "QUARANTINED").write_text(
        "Generated experiment code failed static review.\n",
        encoding="utf-8",
    )
    return findings_path


def _review_imports(tree: ast.AST) -> list[CodeReviewFinding]:
    findings: list[CodeReviewFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", maxsplit=1)[0]
                if root in DANGEROUS_IMPORT_ROOTS:
                    findings.append(
                        _finding(
                            "dangerous_command",
                            f"imports command execution module {alias.name}",
                            node,
                        )
                    )
                if root in NETWORK_IMPORT_ROOTS:
                    findings.append(
                        _finding(
                            "unrestricted_network",
                            f"imports network module {alias.name}",
                            node,
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", maxsplit=1)[0]
            if root in DANGEROUS_IMPORT_ROOTS:
                findings.append(
                    _finding(
                        "dangerous_command",
                        f"imports from command execution module {node.module}",
                        node,
                    )
                )
            if root in NETWORK_IMPORT_ROOTS:
                findings.append(
                    _finding(
                        "unrestricted_network",
                        f"imports from network module {node.module}",
                        node,
                    )
                )
    return findings


def _review_calls(tree: ast.AST) -> list[CodeReviewFinding]:
    findings: list[CodeReviewFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        if call_name in DANGEROUS_CALLS:
            findings.append(
                _finding(
                    "dangerous_command",
                    f"calls blocked function {call_name}",
                    node,
                )
            )
        if call_name in {"os.getenv", "Path.home"} or _is_expanduser_call(node):
            findings.append(
                _finding(
                    "secret_read",
                    f"reads from environment or user home via {call_name}",
                    node,
                )
            )
        findings.extend(_review_dynamic_import(node, call_name))
    return findings


def _review_attributes(tree: ast.AST) -> list[CodeReviewFinding]:
    findings: list[CodeReviewFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attribute_name = _attribute_name(node)
            if attribute_name.startswith("os.environ"):
                findings.append(
                    _finding(
                        "secret_read",
                        "reads from process environment",
                        node,
                    )
                )
    return findings


def _review_string_literals(tree: ast.AST) -> list[CodeReviewFinding]:
    findings: list[CodeReviewFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value
        normalized = value.casefold()
        if PATH_TRAVERSAL_PATTERN.search(value):
            findings.append(
                _finding("path_traversal", f"contains traversal path {value!r}", node)
            )
        if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("/etc/"):
            findings.append(
                _finding("path_traversal", f"contains absolute system path {value!r}", node)
            )
        if any(marker in normalized for marker in SECRET_MARKERS):
            findings.append(
                _finding("secret_read", f"references secret-like path or key {value!r}", node)
            )
        if any(marker in normalized for marker in DANGEROUS_COMMAND_MARKERS):
            findings.append(
                _finding("dangerous_command", f"contains shell command marker {value!r}", node)
            )
    return findings


def _review_metric_write(tree: ast.AST) -> list[CodeReviewFinding]:
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    has_metrics_path = "metrics.json" in string_literals
    has_write_call = any(_is_write_call(node) for node in ast.walk(tree))
    if has_metrics_path and has_write_call:
        return []
    return [
        CodeReviewFinding(
            "missing_metric_write",
            "generated code must write metrics.json before execution is allowed",
        )
    ]


def _is_write_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in {
        "write",
        "write_text",
        "write_bytes",
    }:
        return True
    call_name = _call_name(node.func)
    return call_name == "json.dump"


def _is_expanduser_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "expanduser"


def _review_dynamic_import(node: ast.Call, call_name: str) -> list[CodeReviewFinding]:
    if call_name not in {"__import__", "importlib.import_module"}:
        return []
    module_name = _first_string_arg(node)
    if not module_name:
        return []
    root = module_name.split(".", maxsplit=1)[0]
    findings: list[CodeReviewFinding] = []
    if root in DANGEROUS_IMPORT_ROOTS:
        findings.append(
            _finding(
                "dangerous_command",
                f"dynamically imports command execution module {module_name}",
                node,
            )
        )
    if root in NETWORK_IMPORT_ROOTS:
        findings.append(
            _finding(
                "unrestricted_network",
                f"dynamically imports network module {module_name}",
                node,
            )
        )
    return findings


def _first_string_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _call_name(node: ast.AST) -> str:
    return ".".join(_name_parts(node))


def _attribute_name(node: ast.Attribute) -> str:
    return ".".join(_name_parts(node))


def _name_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*_name_parts(node.value), node.attr]
    return []


def _finding(category: str, message: str, node: ast.AST) -> CodeReviewFinding:
    return CodeReviewFinding(category, message, line=getattr(node, "lineno", None))


def _result(findings: list[CodeReviewFinding]) -> CodeReviewResult:
    deduped: dict[tuple[str, str, int | None], CodeReviewFinding] = {}
    for finding in findings:
        deduped[(finding.category, finding.message, finding.line)] = finding
    final_findings = tuple(deduped.values())
    return CodeReviewResult(approved=not final_findings, findings=final_findings)
