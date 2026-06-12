# Third-Party Notices

Last reviewed: 2026-06-12

This file records upstream projects that AI-Researcher explicitly references for
design comparison, operator experience, naming context, or implementation
patterns. Unless a row says otherwise, the AI-Researcher source tree does not
copy, vendor, adapt, or redistribute code, datasets, model weights, images, or
other assets from these projects.

## Reference Projects

| Project | Upstream | Reviewed license status | Current use in AI-Researcher | Incorporated here? | Required handling |
|---|---|---|---|---|---|
| HKUDS AI-Researcher | https://github.com/HKUDS/AI-Researcher | No repository license file was found during this review. | Conceptual comparison for end-to-end autonomous research pipelines and Scientist-Bench-style evaluation pressure. | No | Do not copy or adapt repository code, assets, prompts, benchmark data, or generated examples unless the upstream license is clarified or written permission is obtained. Cite the paper/project when discussing conceptual comparisons. |
| karpathy/autoresearch | https://github.com/karpathy/autoresearch | MIT. | Naming-conflict context and a public example of automated research on a constrained compute setup. | No | If code or assets are ever copied or adapted, preserve upstream copyright and the MIT license text. |
| Thysrael/Horizon | https://github.com/Thysrael/Horizon | MIT. | Inspiration for scheduled AI-curated digests, source ingestion, scoring, and bilingual delivery patterns. | No | If code or assets are ever copied or adapted, preserve upstream copyright and the MIT license text. |
| UltraClr/agent-arxiv-daily | https://github.com/UltraClr/agent-arxiv-daily | Apache-2.0. | Reference for daily arXiv/GitHub Actions paper update patterns. | No | If code or assets are ever copied or adapted, preserve the Apache-2.0 license text, notices, and modification notices. |
| Microsoft SkillOpt | https://github.com/microsoft/SkillOpt | MIT. | Design inspiration for bounded Markdown skill optimization, validation gates, rejected edits, and deployable skill artifacts. | No | If code or assets are ever copied or adapted, preserve upstream copyright and the MIT license text. |
| OpenClaw | https://github.com/openclaw/openclaw | MIT. | Operator-experience inspiration for a self-hosted assistant configured once and kept running as an always-on service. | No | If code or assets are ever copied or adapted, preserve upstream copyright, the MIT license text, and any upstream third-party notices that apply. |

## Runtime Dependencies

Python package dependencies are declared in `pyproject.toml` and installed from
their upstream packages at deployment time. They are not vendored in this source
tree. Before publishing a source distribution, binary distribution, Docker image,
or reproducibility package that includes third-party code, generated artifacts,
datasets, or model outputs, maintainers must run the license metadata checks and
include any required upstream license texts, notices, attribution statements, and
modification notices.

## Contribution Rule

Pull requests must update this file and `NOTICE` whenever they add a new
third-party reference that influences design, copy or adapt upstream code,
vendor dependencies, include external assets, bundle datasets, or redistribute
generated artifacts that carry license or attribution requirements.
