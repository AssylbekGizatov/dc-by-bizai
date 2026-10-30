from __future__ import annotations

import hmac
import json
import logging
import math
import sqlite3
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .schemas import AdminCreate, Category, Language, Priority, ReviewRequest, Status, Ticket, TriageRequest, TriageResponse
from .service import CopilotService
from .storage import ConflictError

logger = logging.getLogger("copilot.http")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def create_app(settings: Settings | None = None, service: CopilotService | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.copilot = service or CopilotService(cfg)
        try:
            yield
        finally:
            await application.state.copilot.close()

    app = FastAPI(title="Grand Mobile Support Copilot", version="0.1.0", lifespan=lifespan,
                  description="Local NLP → local hybrid RAG → optional Groq drafting → deterministic safety → human review.")
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Authorization", "Idempotency-Key"])
    windows: dict[str, deque] = {}

    @app.middleware("http")
    async def security_and_limits(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in cfg.cors_origins and request.method in {"POST", "PATCH", "DELETE"}:
            # Same-origin browser deployments do not need to enumerate their own host.
            if origin != f"{request.url.scheme}://{request.url.netloc}":
                return JSONResponse(status_code=403, content={"detail": "Origin is not allowed"})
        if request.method in {"POST", "PATCH"}:
            raw_length = request.headers.get("content-length", "0")
            if len(raw_length) > 12 or not raw_length.isdigit() or int(raw_length) > cfg.max_request_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
            # Bound chunked bodies while reading, not after accumulating unbounded bytes.
            chunks, received = [], 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > cfg.max_request_bytes:
                    return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
                chunks.append(chunk)
            # Starlette's cached request replays this bounded body to downstream validation.
            request._body = b"".join(chunks)
        is_api = request.url.path == "/triage" or request.url.path.startswith("/api/")
        if is_api and request.url.path != "/api/health" and request.method != "OPTIONS":
            peer = request.client.host if request.client else "unknown"
            # Never log or store bearer tokens. IP buckets are process-local and ephemeral.
            now = time.monotonic()
            # Bound active as well as expired entries. Forwarded headers are not trusted.
            if len(windows) >= 10_000:
                for key in list(windows):
                    if not windows[key] or windows[key][-1] <= now - 60:
                        del windows[key]
                if peer not in windows and len(windows) >= 10_000:
                    return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={"detail": "Request rate exceeded"})
            bucket = windows.setdefault(peer, deque())
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= cfg.request_rate_per_minute:
                retry_after = max(1, math.ceil(60 - (now - bucket[0])))
                return JSONResponse(status_code=429, headers={"Retry-After": str(retry_after)}, content={"detail": "Request rate exceeded"})
            bucket.append(now)
        return await call_next(request)

    @app.middleware("http")
    async def response_security_and_logging(request: Request, call_next):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as exc:
            # Exception strings, body values and provider responses may contain private data.
            logger.error(json.dumps({"event": "request_failed", "request_id": request_id, "error_type": type(exc).__name__}))
            response = JSONResponse(status_code=500, content={"detail": "Internal service error; retry or contact the administrator"})
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        logger.info(json.dumps({"event": "http_request", "request_id": request_id,
            "method": request.method, "route": getattr(route, "path", "unmatched"), "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2)}, ensure_ascii=True))
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        return JSONResponse(status_code=422, content={"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

    @app.exception_handler(ConflictError)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def storage_unavailable(_request, exc):
        logger.warning(json.dumps({"event": "storage_unavailable", "error_type": type(exc).__name__}))
        return JSONResponse(status_code=503, headers={"Retry-After": "1"},
                            content={"detail": "Storage is temporarily unavailable; retry with the same idempotency key or revision"})

    def get_service(request: Request) -> CopilotService:
        return request.app.state.copilot

    def authorize(authorization: str | None = Header(default=None)):
        if cfg.api_token:
            supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
            if not hmac.compare_digest(supplied.encode(), cfg.api_token.encode()):
                raise HTTPException(status_code=401, detail="Valid API bearer token required", headers={"WWW-Authenticate": "Bearer"})

    protected = [Depends(authorize)]

    @app.get("/health")
    @app.get("/api/health")
    async def health(svc: CopilotService = Depends(get_service)):
        return svc.health()

    @app.get("/ready")
    async def ready(svc: CopilotService = Depends(get_service)):
        await run_in_threadpool(svc.store.check_ready)
        status = svc.health()
        return {"status": "ready", "mode": status["mode"], "capability": "local_model_assisted_baseline" if status["local_encoder_loaded"] else "local_baseline",
                "real_rules_loaded": status["real_rules_loaded"], "local_encoder_loaded": status["local_encoder_loaded"],
                "generation_mode": status["generation_mode"], "model_quality_validated": False}

    @app.post("/triage", response_model=TriageResponse, dependencies=protected)
    async def triage(payload: TriageRequest, svc: CopilotService = Depends(get_service),
                     idempotency_key: str | None = Header(default=None, min_length=1, max_length=128, pattern=r"^\S+$")):
        return (await svc.process(payload, idempotency_key=idempotency_key)).result

    @app.post("/api/tickets", response_model=Ticket, status_code=201, dependencies=protected)
    async def create_ticket(payload: AdminCreate, svc: CopilotService = Depends(get_service),
                            idempotency_key: str | None = Header(default=None, min_length=1, max_length=128, pattern=r"^\S+$")):
        request = TriageRequest(kind=payload.kind, messages=[{"role": "player", "text": payload.text, "attachments": payload.attachments_count}],
            reporter_hash=payload.player_id, server=payload.server, server_lang=payload.server_lang)
        return await svc.process(request, idempotency_key=idempotency_key)

    @app.get("/api/tickets", dependencies=protected)
    async def list_tickets(status: Status | None = None, category: Category | None = None, language: Language | None = None,
            priority: Priority | None = None, search: str | None = Query(default=None, max_length=200),
            needs_human: bool | None = None, urgent: bool | None = None,
            limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), svc: CopilotService = Depends(get_service)):
        return await run_in_threadpool(svc.store.list, status=status, category=category, language=language, priority=priority,
            search=search, needs_human=needs_human, urgent=urgent, limit=limit, offset=offset)

    @app.get("/api/tickets/{ticket_id}", response_model=Ticket, dependencies=protected)
    async def get_ticket(ticket_id: str, svc: CopilotService = Depends(get_service)):
        ticket = await run_in_threadpool(svc.store.get, ticket_id)
        if ticket is None:
            raise HTTPException(404, "Ticket not found")
        return ticket

    @app.patch("/api/tickets/{ticket_id}/review", response_model=Ticket, dependencies=protected)
    async def review_ticket(ticket_id: str, payload: ReviewRequest, svc: CopilotService = Depends(get_service)):
        # Human edits are preserved as feedback, never automatically treated as correct labels.
        if payload.expected_revision is None:
            raise HTTPException(428, "expected_revision is required; load the current ticket before saving")
        ticket = await run_in_threadpool(svc.store.review, ticket_id, payload)
        if ticket is None:
            raise HTTPException(404, "Ticket not found")
        return ticket

    @app.get("/api/tickets/{ticket_id}/feedback", dependencies=protected)
    async def feedback(ticket_id: str, svc: CopilotService = Depends(get_service)):
        if await run_in_threadpool(svc.store.get, ticket_id) is None:
            raise HTTPException(404, "Ticket not found")
        return {"items": await run_in_threadpool(svc.store.feedback, ticket_id)}

    @app.get("/api/rules", dependencies=protected)
    async def rules(search: str | None = Query(default=None, max_length=200), svc: CopilotService = Depends(get_service)):
        selected = svc.index.rules
        if search:
            term = search.casefold()
            selected = [r for r in selected if term in (r.title + " " + r.text).casefold()]
        return {"items": selected, "total": len(selected), "synthetic": svc.index.synthetic, "version": svc.index.version}

    @app.get("/api/rules/{rule_id}", dependencies=protected)
    async def get_rule(rule_id: str, svc: CopilotService = Depends(get_service)):
        if rule_id not in svc.index.by_id:
            raise HTTPException(404, "Rule not found")
        return svc.index.by_id[rule_id]

    @app.get("/api/metrics", dependencies=protected)
    async def metrics(svc: CopilotService = Depends(get_service)):
        return {"counters": dict(svc.metrics), "latency_ms": {"p50": float(np.percentile(svc.latencies, 50)) if svc.latencies else None,
                "p95": float(np.percentile(svc.latencies, 95)) if svc.latencies else None, "sample_count": len(svc.latencies)},
                "cost_note": "Only accepted provider usage is counted; configure current prices. Local API cost is zero, compute cost excluded.",
                "accuracy": None, "accuracy_note": "No adjudicated category/priority labels or calibrated model evaluation available."}

    if cfg.frontend_dist:
        root = Path(cfg.frontend_dist).resolve()

        @app.get("/{file_path:path}", include_in_schema=False)
        async def frontend(file_path: str):
            if file_path.startswith(("api/", "triage", "health", "ready")):
                raise HTTPException(404, "Not found")
            candidate = (root / file_path).resolve()
            if candidate != root and root not in candidate.parents:
                raise HTTPException(404, "Not found")
            if any(part.startswith(".") for part in Path(file_path).parts):
                raise HTTPException(404, "Not found")
            if candidate.is_file():
                public_extensions = {".html", ".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".woff", ".woff2", ".ttf"}
                is_license = candidate.suffix == ".txt" and candidate.parent == root / "licenses"
                if candidate.suffix.lower() not in public_extensions and not is_license:
                    raise HTTPException(404, "Not found")
                return FileResponse(candidate)
            if candidate.suffix:
                raise HTTPException(404, "Not found")
            return FileResponse(root / "index.html")

    return app


app = create_app()
