# API, concurrency and private storage

The service remains one FastAPI process with a SQLite queue. Start one Uvicorn
worker. The HTTP limiter, inference cache and creation lock are process-local;
they are not distributed rate limits. SQLite transactions protect writes across
connections, but multiple service processes can spend generation work on the
same request before one of them commits. No game-server action is performed.

## Review migration

`PATCH /api/tickets/{id}/review` now requires `expected_revision` at the HTTP
boundary. Read the ticket, send its integer `revision`, and retain local edits
until the save succeeds. Older callers that omitted it receive **428**, rather
than silently overwriting another administrator. The internal `ReviewRequest`
model still accepts an absent revision for explicit internal compatibility.

On **409**, fetch `GET /api/tickets/{id}` again. Compare the fresh draft/note with
the unsaved local version before another save; do not use an older queue cache
as the conflict source. Every successful save increments the revision and adds
one history record in the same transaction. An omitted note or draft is
preserved; an empty note explicitly clears the note. A failure writing history
rolls back the whole review.

`simulated_sent` is terminal at the API boundary: changes to its status, draft
or note return **409**. An exact no-op with the current revision returns the
unchanged ticket without another revision or history row. This preserves the
record of the confirmed simulation; it still does not represent game delivery.

Create calls retain `POST /triage` and `POST /api/tickets` and accept an
`Idempotency-Key` of 1–128 non-whitespace characters. A retry of the same body
returns the saved ticket; reusing a key with another body gives **409**. Keep
the same key for retries after a timeout or **503**. Idempotency keys and queue
history survive restarts. The backend never treats a click on simulated send
as evidence of delivery to a player.

Repeat/flood observations, the ticket and its idempotency record commit in one
short transaction, after generation has finished. A failed save rolls all three
back, so retrying cannot falsely count the failed request as a duplicate or flood.
The key is checked again inside this transaction to cover independent service
connections. Batch `persist=False` retains repeat history without saving tickets.
Provider attempts remain counted even when a subsequent storage operation fails.

## Queue queries and errors

`GET /api/tickets` filters the entire database before counting and pagination.
Alongside status, category, language, priority and search, it accepts
`needs_human=true|false` and `urgent=true|false` (`urgent` means p0 or p1).
`limit` is 1–100; `offset` is non-negative. Unsupported enum/filter values return
422 instead of an unexplained empty result.
Search uses Unicode case folding, including Cyrillic, and treats `%` and `_`
literally. This remains a scan intended for modest queues, not an indexed search
engine for an unbounded ticket archive.

| Status | Meaning | Client action |
|---|---|---|
| 401 | Missing or expired application access | Preserve local edits; request a valid application token. |
| 403 | Disallowed browser origin | Fix the configured origin; do not disable authentication. |
| 409 | Stale revision or reused idempotency key | Fetch fresh data or correct the create key/body. |
| 413 | Request exceeds the bounded body size | Reduce the request. |
| 422 | Invalid input | Show validation feedback without echoing private bodies. |
| 428 | Review has no revision | Fetch the current ticket first. |
| 429 | HTTP request limit | Respect `Retry-After`; do not silently switch to demo. |
| 503 | SQLite is temporarily unavailable | Preserve edits and retry with the same key/revision. |

`REQUEST_RATE_PER_MINUTE` defaults to 120 and is bounded to 1–10000. The limit
covers API reads and writes per direct peer, excluding health and readiness.
The service does not trust a client-supplied forwarded IP. Behind a proxy,
configure one trusted ingress and account for its shared peer bucket. Active
buckets have a hard bound. The independent `FLOOD_LIMIT_PER_HOUR` still defaults
to five: subsequent player requests remain accepted and are marked for human
review; it is not an HTTP refusal.

`SQLITE_BUSY_TIMEOUT_SECONDS` defaults to 1 and accepts 0.05–5 seconds. A locked
database yields a generic 503 and `Retry-After: 1`; SQL, paths, private text and
provider bodies are not returned. Queue storage work runs off the HTTP event
loop. `/health` means the process is alive; `/ready` also probes the queue and
returns 503 if storage is closed or fails. Neither asserts model quality or a
successful Groq integration.

## Files, logs and shutdown

The default database lives in the OS temporary directory under `grandmobile`,
outside the checkout. Set a private persistent `DATABASE_PATH` for durable use.
POSIX files receive mode 0600. Windows files receive a protected NTFS ACL for
the current account, SYSTEM and administrators; `chmod` alone is not treated
as Windows confidentiality. Database WAL/SHM companions receive the same
protection. Newly created private directories inherit this protection for
children. An ACL failure stops initialization rather than continuing insecurely.

Static serving allows built web assets and font-license text; it refuses dot
files, SQLite, arbitrary JSON/text, source maps and path escapes even if copied
inside the build directory. This is additional defense, not permission to put
private data in a frontend build.

HTTP logs contain a generated request ID, route template, method, status and
duration. They omit query strings, IDs, request/response bodies and credentials.
Use the provided `--no-access-log` startup commands so a second Uvicorn access
logger does not print search text. Security headers and `no-store` are applied
to validation, origin, size and rate errors too. Shutdown closes storage even
if provider cleanup fails; repeated storage close is harmless.

The regression suite uses only invented requests/rules. It exercises separate
SQLite connections, competing administrators, transaction rollback, retry,
restart, filtering before pagination, private NTFS/POSIX permissions and log
redaction. The symlink-escape test requires the OS privilege to create symlinks;
on Windows without that privilege only that test is skipped, while path
traversal and private-file exposure tests still run. These checks do not establish
deployment readiness, classifier accuracy, native-speaker draft quality or an
end-to-end latency target.
