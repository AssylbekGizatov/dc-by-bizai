# Verification and measurement boundaries

Verification date: 2026-10-31. Windows, Python 3.12, Node 24, actual Edge/Chromium and loopback Uvicorn. This document contains synthetic measurements only; organizer-data reports and screenshots containing private rules stay outside Git.

Final integrated local result: **256 Python tests passed, 2 Windows privilege skips; 33 frontend tests passed; TypeScript/Vite build and release hygiene passed. All 6 browser E2E scenarios passed in 38.6 s.** Independent review results in `FINAL_REVIEW.md` are subsets, not additional unique tests.

## Reproduce

Follow the root README to install Python/frontend/root test dependencies. `npm test` runs Python tests, frontend tests, type checks/build and release hygiene. `npm run test:e2e` runs an actual API and SQLite with temporary credentials. Set `E2E_BROWSER_CHANNEL=msedge` to use an installed Edge; otherwise install Playwright Chromium.

The E2E suite covers create/double-click, analyzer copy-only edits, saved queue edits/notes, two-admin 409 with fresh retrieval and recovery, history, canceled escalation, confirmed simulated send, reload/auth, Back/Forward, network loss, real 401/429, mobile focus/reduced-motion/overflow and axe checks. The provider-error scenario uses a real HTTP API with an injected mock provider 503. It is not a live Groq outage test. Screenshots are opt-in via `E2E_SCREENSHOTS`; CI uploads none.

`backend/tests/test_uvicorn_rate_limit.py` starts the documented Uvicorn command and verifies that rotating forwarded headers does not bypass auth or quotas, even when an inherited `FORWARDED_ALLOW_IPS=*` exists. The direct deployment disables proxy headers explicitly. A future proxy deployment needs a separate trusted-proxy policy.

## Synthetic full HTTP latency

`scripts/benchmark_http.py` sends unique synthetic ru/kk/uz tickets to a warm authenticated server, including NLP, retrieval, generation, serialization and SQLite. On 60 requests, concurrency 4: 60 HTTP 201, p50 78.07 ms, p95 105.53 ms, max 112.55 ms. This run used local templates and no dense encoder: external API cost $0, infrastructure cost unmeasured. Cold start and production traffic were not measured.

## Groq: live versus mock versus templates

The separate synthetic harness completed 12 real successful provider calls: ru/kk/uz/en/es/pt, once per model, no fallback. Full loopback HTTP → NLP → retrieval → Groq → SQLite was timed. No organizer tickets or rules were transmitted; no dense encoder or cold start was included.

| Model | Cases | p50 | Observed p95 (nearest rank) | Mean usage cost |
|---|---:|---:|---:|---:|
| openai/gpt-oss-20b | 6 | 476.40 ms | 936.69 ms | $0.0000569 |
| openai/gpt-oss-120b | 6 | 627.84 ms | 783.26 ms | $0.0001318 |

Total reported-usage estimate: **$0.0011322**. Pricing checked against [Groq models](https://console.groq.com/docs/models): 20b $0.075/$0.30 and 120b $0.15/$0.60 per million input/output tokens. These are usage estimates, not an invoice. Six cases per model do not establish a stable p95, language quality, model ranking or a production SLO. The default remains 20b pending reviewed quality evidence.

[Structured outputs](https://console.groq.com/docs/structured-outputs) select a bounded plan of approved clauses; the application composes the response. This is constrained drafting, not unrestricted prose generation. The harness conservatively bounds input at 16,384 tokens using serialized UTF-8 bytes plus framing allowance, reserves spend before sending, and never conflates mock usage with billed provider usage. Provider timeouts, refusal, invalid usage/JSON, unsafe text and retry limits also have mock tests.

## Retrieval comparison

`scripts/benchmark_retrieval_synthetic.py` uses 18 authored synthetic regression cases: 15 retrieval targets and 3 abstentions. It compares algorithms, not old-versus-new repository quality; the original project already used hybrid retrieval.

| Method | Target hit@3 | Correct abstention | Retrieval-only p95 |
|---|---:|---:|---:|
| BM25 | 5/15 | 3/3 | 4.11 ms |
| BM25 + character TF-IDF | 15/15 | 3/3 | 6.03 ms |
| Hybrid + local multilingual-E5-small | 15/15 | 3/3 | 134.14 ms |

The pinned real E5 weights were loaded in a separate CPU environment with two model threads. Loading/import under competing workstation load took 133.2 s; it is excluded from retrieval timings. On this small engineered set E5 added no measured benefit, so dense retrieval and a reranker are not enabled by default. This is not semantic-relevance accuracy on real traffic.

## Container verification

The initial Docker Desktop engine failure cleared on recheck. The final code image `grandmobile-copilot:verified-20261031` built successfully; image ID `sha256:06512321ee894aa9cdcdbdba0ce161780f6cd0335da00878a2b0cbdb868dc1e9`. A separate loopback-only container on port 18086, using only synthetic data and a fresh disposable volume, passed frontend/readiness/healthcheck, auth 401, creation 201, idempotent replay, revision conflict, escalation, terminal simulation, request limits and forwarded-header rate limiting. A real restart preserved the draft, administrator note, history and idempotency record.

Runtime UID was 10001, the root filesystem was read-only, all capabilities were dropped and no-new-privileges was enabled. SQLite files were owned by the app user with owner-only modes. The built application filesystem and image environment contained no detected credential patterns, real datasets/rules, model weights or pre-existing runtime database; only reviewed synthetic fixtures were included. This scoped inspection is evidence, not a universal guarantee against every possible secret encoding. Verification removes only its own disposable container, volume and token; the tested image remains local.

Three targeted original Linux filesystem/symlink security tests also passed (zero skips, 3.31 s) inside the container using temporary test dependencies in tmpfs; the image was unchanged. This covers the Windows privilege-skipped cases, not an entire Linux test-suite run.

Shutdown was checked separately: the log recorded `Application shutdown complete` and `Finished server process`; stopping took 1.094 s with no OOM. Uvicorn re-raises SIGTERM after cleanup, yielding the expected 143 exit code. An initial verification-script assertion requiring only exit 0 was corrected after this evidence; application code did not change.

## Remaining limits

- No independent human category/priority labels: accuracy, macro-F1, false escalation rate, citation relevance and native-language draft quality remain unmeasured. See the annotation protocol; auto-labels are not gold.
- Local Windows skips two symlink-creation tests because the account lacks that privilege. Three targeted Linux filesystem/symlink tests passed separately; Windows confidentiality is tested through NTFS ACL rather than POSIX mode bits.
- GitHub Actions runs for the published improvements failed before acquiring a runner, with no test steps. The exact external cause could not be read. Local Docker build/run is confirmed as above; a successful hosted Linux CI run is still not confirmed.
- A small synthetic response-time sample does not prove the 5-second production p95 target. There is no real game-server connection; sending remains a recorded simulation.

Do not infer production readiness from these checks. Private corpus aggregates, full logs, before/after screenshots and annotation material are delivered separately outside the repository.
