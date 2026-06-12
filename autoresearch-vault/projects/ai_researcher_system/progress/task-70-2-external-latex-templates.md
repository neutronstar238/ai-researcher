# Task 70.2 External LaTeX Template Compatibility

- Date: 2026-06-13 +08:00
- Task: `70.2`
- Status: completed with a documented Springer Nature local-class limitation
- Run artifact: `runs/manual-live/latex-template-compatibility-task70-external/latex-template-compatibility.json`
- Compatibility report: [[../paper/latex-template-compatibility]]

## Policy Boundary

- Process data, compatibility summaries, and evidence notes remain Markdown in `autoresearch-vault/`.
- Final paper-level delivery must compile a venue or publisher LaTeX template to PDF.
- External template packages are not vendored into this repository.
- Missing external classes are recorded as `source_unavailable`; they are not treated as successful compatibility.

## Source Review

| Template | Source | Source status | Compile status | Notes |
| --- | --- | --- | --- | --- |
| IEEEtran conference | https://ctan.org/pkg/IEEEtran | HTTP 200 fetched | compiled | Local TeX Live provided `IEEEtran.cls`; smoke PDF was generated. |
| ACM acmart SIGCONF | https://ctan.org/pkg/acmart | HTTP 200 fetched | compiled | Local TeX Live provided `acmart.cls`; abstract placement was adjusted through template metadata. |
| Springer Nature `sn-jnl` | https://www.springernature.com/gp/authors/campaigns/latex-author-support | HTTP 200 fetched | source_unavailable | Source page was reachable, but local TeX Live did not provide `sn-jnl.cls`. |

## Verification

- `poetry run pytest tests\unit\reports\test_latex_templates.py -q`: passed with 9 tests.
- `poetry run ruff check src\autoresearch\reports\latex_templates.py src\autoresearch\reports\__init__.py tests\unit\reports\test_latex_templates.py`: passed.
- `poetry run mypy src\autoresearch\reports`: passed.
- Real external matrix: `run_latex_template_compatibility(Path('runs/manual-live/latex-template-compatibility-task70-external'), templates=external_latex_templates(), fetch_sources=True, vault_root=Path('autoresearch-vault'), project_id='ai_researcher_system')`.

## Follow-Up

- Add/verify Springer Nature `sn-jnl.cls` through an allowed local TeX installation or explicitly reviewed template package before claiming Springer Nature PDF compatibility.
- Keep template source metadata cached under ignored run artifacts, not in repository source.
