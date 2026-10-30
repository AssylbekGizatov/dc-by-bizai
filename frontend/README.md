# Support Copilot — admin UI

Russian-first React + TypeScript workspace with bundled Lucide icons and no external fonts or frontend model credentials.

## Run and verify

Node >= 22.12 is required. From this directory:

```sh
npm ci
npm run dev       # http://127.0.0.1:5173, proxies /api to localhost:8000
npm run build     # typecheck + production output in dist/
npm test          # 20 API, rendering, and safety-flow tests
```

For both services, run `npm run dev` or `make dev` from the repository root after its setup. Production uses the FastAPI same-origin static host; the browser only calls `/api/*`. The dev proxy preserves the browser Host for the API's same-origin policy. Never enable unrestricted Vite `allowedHosts`.

## Included behavior

- Server-side text/ID, status, language, category, and priority filters; 100-record pagination; explicitly page-scoped counters.
- Ticket details, original/normalized text, unverified extracted claims, model confidence clearly distinguished from measured accuracy.
- RAG source browser with canonical unique rule ID, section, full text, and explicit synthetic-rule markings.
- Editable draft, optimistic revision checks, preserved human feedback, escalation reason, and confirmed **simulated** send. There is no game-send integration.
- Synthetic examples only; zero real tickets or dataset-derived examples in the frontend.
- Request cancellation for navigation, unsaved-change guards, protected repeated creation, retained idempotency key on retry, loading/empty/error states.
- Native modal focus trapping, Escape/cancel, labelled controls, keyboard text tabs, reduced-motion handling, narrow-screen layout.
- Optional admin API token stays in tab memory; never localStorage. Provider keys never belong in the browser.

## Verified locally

Production build, TypeScript, and 20 tests pass. CUA browser QA against the actual Python API verified synthetic creation, parsed details, canonical citation view, editing/saving, required-note escalation, cancel/reopen, and explicit-confirmation simulated send. API-offline errors and desktop layout were also inspected. Unit tests use synthetic fixtures only and do not replace the application's API.
