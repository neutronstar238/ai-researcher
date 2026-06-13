# Release Gate Checklist

Use this checklist before tagging a release, publishing a demo, or claiming a workflow is production-ready.

## Required Gates

- Unit and smoke tests pass with `python scripts/check.py`.
- Golden tests do not regress. If golden tests do not exist for the changed surface yet, record that gap in `Problem.md`.
- Security checks pass for the changed surface. At minimum, review permissions, sandbox boundaries, secrets handling, generated artifacts, and publication paths.
- Documentation is updated in `README.md`, `README.zh-CN.md`, `Agent.md`, `Problem.md`, and task-specific docs where relevant.
- Migrations are reversible or have a documented rollback path. This includes schema changes, Obsidian vault layout changes, and persisted JSON/JSONL formats.
- Changelog or release notes are complete for user-visible changes.
- Automated research-cycle release claims require a physical evidence gate: cycle summary, live literature/similarity evidence, first run record, reproduction rerun record, reproduction validation report, publication audit, paper-build JSON, and compiled PDF must exist and pass the relevant gate.
- Publication-level claims require file-backed method innovation evidence, not only baseline reproduction or a paper-shaped report.
- Neutral or negative method-candidate deltas must remain visible in the release evidence. Do not convert an underperforming run into an empirical-gain claim.
- Git tag is created only after the release candidate commit is verified.
- The `autoresearch-vault/` self-loop memory remains readable as Markdown and keeps provenance links for experiments, failures, skills, and strategy changes.

## 中文

在创建版本标签、发布演示或声明某个工作流可用于生产前，必须检查以下事项：

- `python scripts/check.py` 通过单元测试、冒烟测试、ruff 和 mypy。
- golden tests 不回退。如果当前变更范围还没有 golden tests，必须在 `Problem.md` 记录缺口。
- 变更范围内的安全检查通过，至少覆盖权限、沙箱边界、密钥处理、生成产物和对外发布路径。
- 已更新 `README.md`、`README.zh-CN.md`、`Agent.md`、`Problem.md` 以及相关任务文档。
- migration 可逆，或有明确回滚路径；这包括 schema、Obsidian vault 目录结构、持久化 JSON/JSONL 格式。
- 面向用户的变更已经写入 changelog 或 release notes。
- 自动科研循环的发布声明必须通过物理 evidence gate：cycle summary、真实文献/相似工作证据、第一次 run record、复现实验 rerun record、复现实验 validation report、publication audit、paper-build JSON 和编译后的 PDF 都必须存在并通过对应门禁。
- 发表级声明必须有文件支撑的方法创新证据，不能只靠 baseline reproduction 或论文格式完整的报告。
- 中性或负向的方法候选 delta 必须保留在发布证据里，不能把低于 baseline 的运行包装成经验增益声明。
- 只有在 release candidate commit 验证完成后，才能创建 git tag。
- `autoresearch-vault/` 自循环记忆仍然保持 Markdown 可读，并保留实验、失败、技能和策略变更的 provenance 链接。
