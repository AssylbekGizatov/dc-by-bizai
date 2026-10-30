# Backend: supported behavior and limits

## Run

From the repository root (root Makefile installs dependencies):

```sh
make setup-backend
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
make test-backend
```

The default is an **offline local baseline**. It starts with clearly synthetic rules, an empty queue, no model downloads, no API calls, and no secrets. `GET /api/health` reports exact capabilities. Synthetic policies cannot enable production mode. The UI and provider adapter never send a real game message or execute a sanction, unban, refund, or teleport.

## Pipeline

1. Pydantic validates a bounded request. Only `role=player` text is analyzed; admin outcomes and reported-player rebuttals cannot become labels.
2. Local Unicode/cp1251-glyph normalization, lexical language detection (ru/kk/uz/en/es/pt, else und), regex facts and conservative intent/risk rules. Original player text is retained separately.
3. Optional **local multilingual E5** performs zero-shot category-prototype fallback for unresolved lexical intents. This is not a trained classifier and its confidence is not calibrated. Safety escalation is independent of category classification.
4. Local `rank-bm25` + scikit-learn character TF-IDF retrieval; if local weights are configured, dense E5 + reciprocal-rank fusion. Compound `section:ref` IDs avoid repeated bare rule-number collisions. Scope/intent gates reject contextually incompatible rules; weak retrieval abstains. This is conservative heuristic relevance, not a proven entailment system.
5. Local reviewed-language clauses produce a safe draft. **Optional Groq returns a compact, strict-schema clause-order plan only**, with no authority to add policy claims or actions. Trusted code renders the approved language clauses locally; the model never supplies arbitrary player-facing prose. Any additional prose, missing required clause, invalid JSON/citation, timeout, or provider failure falls back locally. A model-generated draft always requires a human. This deliberately sacrifices free-form drafting to meet the no-promises/no-unseen-images requirement; no unrestricted-generative quality claim is made.
6. Human review persists the edited draft and revision history as feedback. Feedback is not automatically promoted to training truth.

## API

- `POST /triage`: exact brief request/response schema; see `/docs` or `/openapi.json`.
- `POST /api/tickets`: `{text,kind?,player_id?,server?,attachments_count?,server_lang?}`. `Idempotency-Key` makes uncertain retries safe; reuse with different content returns 409.
- `GET /api/tickets`: status/category/language/priority/search + limit/offset filters.
- `GET /api/tickets/{id}`: result, original/normalized text, citations, evidence count, diagnostics, editable draft, revision.
- `PATCH /api/tickets/{id}/review`: draft/status/note + `expected_revision`; stale saves return 409. Status `simulated_sent` is **only a local simulation**.
- `GET /api/tickets/{id}/feedback`, `/api/rules`, `/api/rules/{compound_id}`, `/api/metrics`.
- `/health`, `/api/health`, `/ready`: non-sensitive capability/readiness metadata.

Protected routes require `Authorization: Bearer $API_TOKEN` whenever configured. Production requires a token of at least 24 characters and a non-synthetic private rule corpus. Demo must bind only to loopback. There is no multi-user identity/authorization system; the token represents one trusted admin. TLS, an identity-aware proxy, production load testing, and retention operations remain deployment responsibilities.

## Configuration

| Variable | Default / behavior |
|---|---|
| `APP_MODE` | `demo`; `production` requires auth + real rules |
| `DATABASE_PATH` | `/tmp/grandmobile/copilot.sqlite3`; put private persisted data outside Git/static roots |
| `RULES_PATH` | Private rules JSON; absent uses `fixtures/synthetic_rules.json` |
| `TAXONOMY_PATH` | Optional private taxonomy; validates supported codes, retains mandatory-human categories |
| `LOCAL_ENCODER_PATH` | Existing local SentenceTransformer directory only; absent is lexical mode |
| `LOCAL_MODEL_THREADS` | `2`; allowed 1–16 |
| `ENABLE_GROQ` | `false`; enable explicitly |
| `GROQ_API_KEY` | Environment only; never a browser setting or committed value |
| `GROQ_MODEL` | `openai/gpt-oss-20b`; this verified adapter also supports `openai/gpt-oss-120b` |
| `GROQ_TIMEOUT_SECONDS` | `4`; total generation budget across retries |
| `GROQ_MAX_RETRIES` | `1`; bounded 0–2 |
| `GROQ_INPUT_USD_PER_MILLION` / `GROQ_OUTPUT_USD_PER_MILLION` | Unset: provider cost remains unknown. Set current verified rates to calculate reported usage cost. |
| `ALLOW_PRIVATE_DATA_TO_GROQ` | `false`; private corpus is blocked from external processing by default. Do not enable for organizer data without explicit permission. |
| `API_TOKEN` | Optional in loopback demo, mandatory production |
| `CORS_ORIGINS` | localhost/127.0.0.1:5173 |
| `REQUEST_RATE_PER_MINUTE` | `120`, per process/client IP for mutations |
| `FRONTEND_DIST` | Optional built UI directory. Only that directory is served; traversal and symlink escapes rejected. |

Model dependencies are optional (`requirements-models.txt`). The loader enforces offline mode, disables Hub telemetry, uses safetensors and `trust_remote_code=False`, and never downloads weights. Use the root model-download tooling explicitly and retain the official model license. Health reports whether the encoder actually loaded.

The provider uses Groq **strict JSON Schema** (`strict: true`, every property required, `additionalProperties: false`) with `reasoning_effort=low`, `include_reasoning=false`, and a fixed 600-token completion cap. The compact `{clause_order, cited}` response is still validated locally: all approved indices must occur exactly once, the greeting must remain first, and citations must exactly match the whitelist. Schema compliance does not establish policy relevance or language quality. Other model IDs require an explicit reviewed adapter change; a stale/unsupported configured ID fails before networking. Rejected outputs can still incur provider charges: known usage is accumulated across retries; unknown usage/cost stays unknown. Local API cost is zero, but compute is not free and is not measured. Neither the $0.002 budget nor production p95 is established by mocked tests. Use separately recorded live-validation evidence when available; account/model availability is not inferred from documentation.

## Private batch inference and evaluation

```sh
RULES_PATH=/private/handout/rules.json TAXONOMY_PATH=/private/handout/taxonomy.json \
  make predict IN=/private/tickets.jsonl OUT=/private/pred.jsonl
# .jsonl.gz is also supported
RULES_PATH=/private/handout/rules.json \
  make evaluate IN=/private/tickets_valid.jsonl OUT=/private/metrics.json
```

Both commands force external generation **off**, even if the parent environment enables Groq. The input allowlist drops admin messages, `verdict`, `punishment`, `violation`, `status`, category/priority labels and the heuristic `lang` label. Unsupported `server_lang=lat` is ignored; language is inferred from text. Images are counts only.

Predictions and queue/feedback files contain private derived data: never commit/upload them. Output uses owner-only temporary files and atomic replacement; a malformed line returns nonzero without replacing a previous output. SQLite and WAL/SHM files are owner-only. Dedup stores reporter/text hashes, is scoped to the same reporter and ±one-hour event window, never merges anonymous users, and has bounded state. A duplicate is a queue signal, never a punishment.

Evaluation reports contract coverage, citation existence, escalation rate, distributions, runtime, and external API cost. It intentionally leaves classification accuracy, F1, semantic citation quality and draft quality null: the supplied validation records have no category/priority gold labels, and user/text overlap means they are not an independent holdout. Native-speaker review, adjudicated labels, calibration and broad contextual citation review are still required.

## OSS choices

- [FastAPI](https://fastapi.tiangolo.com/) / [Pydantic](https://docs.pydantic.dev/): bounded typed HTTP contract.
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) / [scikit-learn](https://scikit-learn.org/stable/): lightweight working local lexical retrieval instead of copying a large RAG repository.
- [Sentence Transformers](https://sbert.net/) / [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small): optional local semantic embeddings, no hosted extraction.
- [HTTPX](https://www.python-httpx.org/): explicit provider timeout/mockable HTTP transport.
- Groq official [structured output docs](https://console.groq.com/docs/structured-outputs) and [configured model](https://console.groq.com/docs/model/openai/gpt-oss-20b), [reasoning API](https://console.groq.com/docs/reasoning), and [deprecation history](https://console.groq.com/docs/deprecations), checked 2026-10-30. Llama 3.3 70B was retired for free/developer usage on 2026-08-16; enterprise exceptions do not make it a safe default. Unit tests remain mocked and never use a real key.

Tests use only synthetic content and MockTransport; no organizer rows/rule text, API secrets, pretrained weights, or private databases belong in the repository.
