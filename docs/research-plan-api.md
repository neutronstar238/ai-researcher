# AutoResearch research-plan API

The API is a local, single-user adapter over the existing evidence-first
direction loop. It does not implement a second scientific workflow.

## Start

```powershell
poetry run python -m autoresearch.api.app `
  --host 127.0.0.1 `
  --port 8765 `
  --config config.yaml `
  --env .env `
  --vault-root autoresearch-vault `
  --skills-root skills
```

Open <http://127.0.0.1:8765/>. The server rejects non-loopback bind addresses
because this local interface has no authentication. Provider credentials are
never accepted by HTTP; the direction loop reads the configured provider,
model, base URL, and key environment name from the server-side config and env
files.

## Core endpoints

| Method and path | Purpose |
|---|---|
| `POST /api/runs` | Create one question/direction run or a zero-call dry-run |
| `GET /api/runs/{id}` | Read job, verified stage status, and public artifacts |
| `POST /api/runs/{id}/resume` | Reuse the existing nine-stage checkpoints |
| `POST /api/runs/{id}/cancel` | Cancel queued work or record a safe-stop request |
| `GET /api/runs/{id}/artifacts/{path}` | Open a public plan/evidence artifact |
| `POST /api/batches` | Run or preview a PDF-derived 1–125 question batch |
| `GET /api/batches/{id}` | Read the durable batch receipt |
| `POST /api/runs/{id}/evolution` | Run the frozen evidence-to-Skill shadow service |
| `GET /api/runs/{id}/evolution` | Read candidate/validation state without promotion |

Batch questions are not trusted free-text HTTP inputs. `question_pdf` must be
an existing local PDF, and the deterministic batch service owns extraction and
question IDs. `start`, `limit`, or `include_question_ids` select the desired
subset.

## Evidence and execution boundaries

- Stage completion is reported only after the existing checkpoint loader
  revalidates the receipt and every bound artifact hash.
- Provider response escrows, raw memory, context memory, and private paths are
  never downloadable through the artifact API.
- Formal experiments and result-paper generation are not started by this API.
- Skill evolution produces an isolated candidate and held-out validation. It
  never activates or overwrites an active Skill; explicit promotion remains a
  separate governed action.
- The current direction runner is synchronous. A queued job can be canceled,
  but a running Python worker cannot be killed safely. Its status becomes
  `cancel_requested`; completed evidence/checkpoints are retained and remain
  resumable.
