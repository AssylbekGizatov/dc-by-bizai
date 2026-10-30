#!/usr/bin/env python3
"""Bounded, opt-in Groq adapter smoke test. Never reads datasets or dotenv files.

Default --mode=plan is offline and never reads GROQ_API_KEY. --mode=mock exercises
the same adapter with a MockTransport. Live mode requires explicit authorization,
an environment key, and a durable private ledger outside every Git checkout.

Pricing/model documentation checked 2026-10-30:
https://console.groq.com/docs/models
https://console.groq.com/docs/model/openai/gpt-oss-20b
https://console.groq.com/docs/structured-outputs
https://console.groq.com/docs/api-reference

The spend bound assumes those documented on-demand rates. It is not an account-
wide billing cap: other processes/account use are outside this ledger. Do not
delete or replace the ledger to rerun within the same authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx

from app.config import Settings
from app.generation import DraftGenerator, _composed_only_of, approved_clauses, validate_draft
from app.nlp import analyze, redact_for_external
from app.schemas import TriageRequest
from with_env import read_env

PRICING_REVIEWED_ON = "2026-10-30"
RATES = {
    "openai/gpt-oss-20b": (Decimal("0.075"), Decimal("0.30")),
    "openai/gpt-oss-120b": (Decimal("0.15"), Decimal("0.60")),
}
MAX_BUDGET_USD = Decimal("1.00")
MAX_COMPLETION_REQUESTS = 48
MAX_MODEL_PROBES = 2
MAX_INPUT_TOKENS = 131_072
MAX_COMPLETION_TOKENS = 1024
FIXTURE = ROOT / "backend/fixtures/synthetic_groq_validation.json"
FIXTURE_SHA256 = "9e9eb2bb94b7c35852ab04e02920fbfe9b668624ffdecea3ad375c055f1201b3"
LANGUAGES = ("ru", "kk", "uz", "en", "es", "pt")
API = "https://api.groq.com/openai/v1"


class ValidationStopped(ValueError):
    """Only constant safe reason codes belong in this exception, never payloads."""


def load_cases() -> list[dict]:
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValidationStopped("synthetic_fixture_integrity_changed")
    data = json.loads(raw)
    if data.get("synthetic") is not True:
        raise ValidationStopped("synthetic_fixture_marker_missing")
    cases = data["cases"]
    if tuple(c["language"] for c in cases) != LANGUAGES:
        raise ValidationStopped("synthetic_languages_changed")
    return cases


def private_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.parent.is_dir():
        raise ValidationStopped("private_output_path_invalid")
    resolved = path.resolve()
    # Some managed sandboxes mount empty read-only .git placeholders at writable
    # roots. A real checkout has .git/HEAD, or a .git file for a linked worktree.
    if any((parent / ".git").is_file() or (parent / ".git/HEAD").is_file() for parent in resolved.parents):
        raise ValidationStopped("private_output_inside_git_checkout")
    if resolved.exists() and resolved.stat().st_mode & 0o077:
        raise ValidationStopped("private_output_permissions_must_be_0600")
    return resolved


def write_private_json(path: Path, data: dict, *, exclusive: bool = False) -> None:
    path = private_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def token_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    inp, out = RATES[model]
    return (inp * input_tokens + out * output_tokens) / Decimal(1_000_000)


def read_live_key(env_file: Path | None) -> str:
    """Called only after live authorization gates; never executes dotenv content."""
    if env_file is not None:
        path = private_path(env_file)
        if not path.is_file():
            raise ValidationStopped("private_env_file_missing")
        key = read_env(path).get("GROQ_API_KEY")
    else:
        key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ValidationStopped("groq_key_missing_from_private_env_or_environment")
    return key


class BudgetLedger:
    """Reserve the FULL model context before every attempt, including retries.

    Reservations are never refunded, even for timeout, HTTP failure, or invalid
    output. Actual usage is separate; unknown cost is never reported as zero.
    The file is locked for the whole run and fsynced before each network send.
    """

    def __init__(self, budget: Decimal, path: Path | None = None, *, mode: str = "mock"):
        if not budget.is_finite() or not Decimal(0) < budget <= MAX_BUDGET_USD:
            raise ValidationStopped("budget_must_be_positive_and_at_most_one_usd")
        self.budget, self.path, self.lock, self.mode = budget, None, None, mode
        self.events: list[dict] = []
        if path is not None:
            self.path = private_path(path)
            lock_path = private_path(Path(str(self.path) + ".lock"))
            self.lock = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(self.lock)
                self.lock = None
                raise ValidationStopped("another_validation_run_holds_budget_lock") from None
            if self.path.exists():
                try:
                    saved = json.loads(self.path.read_text())
                    if (saved["version"] != 1 or saved["pricing_reviewed_on"] != PRICING_REVIEWED_ON
                            or saved["mode"] != mode):
                        raise ValueError
                    if Decimal(saved["budget_usd"]) != self.budget:
                        raise ValueError
                    self.events = saved["events"]
                    if not isinstance(self.events, list):
                        raise ValueError
                    for event in self.events:
                        if event["kind"] == "completion":
                            expected = token_cost(event["model"], MAX_INPUT_TOKENS, MAX_COMPLETION_TOKENS)
                            if Decimal(event["reserved_usd"]) != expected:
                                raise ValueError
                        elif event["kind"] != "model_probe" or Decimal(event["reserved_usd"]) != 0:
                            raise ValueError
                    if self.reserved > self.budget:
                        raise ValueError
                except (ValueError, TypeError, KeyError):
                    self.close()
                    raise ValidationStopped("existing_budget_ledger_invalid_do_not_reset") from None
            else:
                self.save()

    @property
    def reserved(self) -> Decimal:
        return sum((Decimal(event["reserved_usd"]) for event in self.events), Decimal(0))

    def save(self) -> None:
        if self.path:
            write_private_json(self.path, {
                "version": 1, "mode": self.mode, "pricing_reviewed_on": PRICING_REVIEWED_ON,
                "budget_usd": str(self.budget), "events": self.events,
            })

    def reserve(self, model: str | None) -> dict:
        kind = "completion" if model else "model_probe"
        count = sum(event["kind"] == kind for event in self.events)
        limit = MAX_COMPLETION_REQUESTS if model else MAX_MODEL_PROBES
        if count >= limit:
            raise ValidationStopped("hard_request_limit_reached")
        if model is not None and model not in RATES:
            raise ValidationStopped("unreviewed_model_or_price")
        amount = token_cost(model, MAX_INPUT_TOKENS, MAX_COMPLETION_TOKENS) if model else Decimal(0)
        if self.reserved + amount > self.budget:
            raise ValidationStopped("next_attempt_would_exceed_budget")
        event = {
            "sequence": len(self.events) + 1, "kind": kind, "model": model,
            "reserved_usd": str(amount), "status": "reserved_before_send",
            "usage_known": False, "input_tokens": None, "output_tokens": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.events.append(event)
        self.save()
        return event

    def close(self) -> None:
        if self.lock is not None:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            os.close(self.lock)
            self.lock = None


class GuardedClient:
    """Only fixed model-list / synthetic completion endpoints can be sent."""

    def __init__(self, client: httpx.AsyncClient, ledger: BudgetLedger, cases: list[dict]):
        self.client, self.ledger = client, ledger
        self.allowed_statements = {redact_for_external(analyze(TriageRequest(
            kind="report", messages=[{"role": "player", "text": case["text"]}]
        )).text) for case in cases}
        self.block_reason: str | None = None

    async def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        if self.block_reason:
            raise ValidationStopped(self.block_reason)
        if url != API + "/chat/completions" or json.get("model") not in RATES:
            raise ValidationStopped("unapproved_provider_endpoint_or_model")
        limit = json.get("max_completion_tokens")
        if type(limit) is not int or not 1 <= limit <= MAX_COMPLETION_TOKENS:
            raise ValidationStopped("completion_token_cap_invalid")
        if (json.get("tools") or json.get("functions") or json.get("stream")
                or json.get("n", 1) != 1 or json.get("service_tier", "on_demand") != "on_demand"):
            raise ValidationStopped("extra_provider_features_not_authorized")
        if set(json) - {"model", "temperature", "max_completion_tokens", "response_format", "messages",
                        "reasoning_effort", "include_reasoning", "service_tier", "seed", "n", "stream"}:
            raise ValidationStopped("unreviewed_provider_request_field")
        messages = json.get("messages", [])
        if len(messages) != 2 or [m.get("role") for m in messages] != ["system", "user"]:
            raise ValidationStopped("unexpected_provider_messages")
        try:
            data = __import__("json").loads(messages[1]["content"])
        except (ValueError, TypeError, KeyError):
            raise ValidationStopped("unexpected_synthetic_request_format") from None
        if (data.get("player_statement") not in self.allowed_statements
                or data.get("language") not in LANGUAGES
                or data.get("policy") != [] or data.get("approved_citations") != []):
            raise ValidationStopped("non_fixture_text_or_policy_rejected")
        if set(data) != {"player_statement", "language", "category", "needs_human", "evidence_count_only",
                         "policy", "approved_clauses", "approved_citations"}:
            raise ValidationStopped("unreviewed_synthetic_request_field")
        try:
            event = self.ledger.reserve(json["model"])
        except ValidationStopped as exc:
            self.block_reason = str(exc)
            raise
        return await self._send("POST", url, event, json=json, headers=headers)

    async def model_probe(self, key: str) -> set[str]:
        event = self.ledger.reserve(None)
        response = await self._send("GET", API + "/models", event,
                                    headers={"Authorization": "Bearer " + key})
        if response.status_code != 200:
            raise ValidationStopped("model_probe_http_failure")
        try:
            body = response.json()
            return {item["id"] for item in body["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)}
        except (ValueError, TypeError, KeyError):
            raise ValidationStopped("model_probe_invalid_response") from None

    async def _send(self, method: str, url: str, event: dict, **kwargs) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self.client.request(method, url, **kwargs)
            event["http_status"] = response.status_code
            event["status"] = "response_received"
            if event["kind"] == "completion":
                try:
                    body = response.json()
                    usage = body.get("usage") if isinstance(body, dict) else None
                    if isinstance(usage, dict):
                        inp, out = usage.get("prompt_tokens"), usage.get("completion_tokens")
                        if (type(inp) is int and type(out) is int
                                and 0 <= inp <= MAX_INPUT_TOKENS and 0 <= out <= MAX_COMPLETION_TOKENS):
                            event.update(usage_known=True, input_tokens=inp, output_tokens=out)
                        else:
                            self.block_reason = "provider_usage_exceeded_or_invalidated_bound"
                    choices = body.get("choices") if isinstance(body, dict) else None
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                        message = choices[0].get("message")
                        event["refusal_detected"] = isinstance(message, dict) and bool(message.get("refusal"))
                except (ValueError, TypeError, KeyError):
                    event["status"] = "malformed_response"
            return response
        except asyncio.CancelledError:
            event["status"] = "cancelled_usage_unknown"
            raise
        except httpx.HTTPError:
            event["status"] = "transport_error_usage_unknown"
            raise
        finally:
            event["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self.ledger.save()


def mock_response(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json={"data": [{"id": model} for model in RATES]})
    payload = json.loads(request.content)
    data = json.loads(payload["messages"][1]["content"])
    answer = {"clause_order": [0] + [c["id"] for c in reversed(data["approved_clauses"][1:])], "cited": []}
    return httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 30},
    })


def percentile95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


async def run_comparison(mode: str, key: str, ledger: BudgetLedger, models: list[str],
                         rounds: int, *, trust_environment_proxy: bool = False,
                         transport: httpx.AsyncBaseTransport | None = None) -> dict:
    cases = load_cases()
    observations = []
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    client_args = {"timeout": 4, "follow_redirects": False, "trust_env": trust_environment_proxy}
    if transport is not None:
        client_args["transport"] = transport
    async with httpx.AsyncClient(**client_args) as client:
        guarded = GuardedClient(client, ledger, cases)
        available = await guarded.model_probe(key)
        if any(model not in available for model in models):
            raise ValidationStopped("requested_model_not_available_to_account")
        for model in models:
            inp, out = RATES[model]
            settings = Settings(mode="test", database_path=":memory:", rules_path=None, taxonomy_path=None,
                api_token=None, local_encoder_path=None, frontend_dist=None, enable_groq=True,
                groq_api_key=key, groq_model=model, groq_max_retries=1, groq_timeout_seconds=4,
                groq_input_usd_per_million=float(inp), groq_output_usd_per_million=float(out),
                allow_private_data_to_groq=False)
            generator = DraftGenerator(settings, guarded)
            for repetition in range(rounds):
                for case in cases:
                    analysis = analyze(TriageRequest(kind="report", messages=[{"role": "player", "text": case["text"]}]))
                    if analysis.language != case["language"] or analysis.sensitive or analysis.injection:
                        raise ValidationStopped("synthetic_local_analysis_changed")
                    started = time.perf_counter()
                    result = await generator.generate(analysis, [], True, False)
                    elapsed = (time.perf_counter() - started) * 1000
                    clauses = approved_clauses(analysis, [], True)
                    safe = (validate_draft(result.draft, [], False, clauses)
                            and set(_composed_only_of(result.draft.text, clauses) or []) == set(clauses))
                    observations.append({
                        "case_id": case["id"], "language": case["language"], "model": model,
                        "repetition": repetition + 1, "bounded_output_valid": safe,
                        "provider_accepted": result.mode == "groq:" + model,
                        "api_attempts": result.api_attempts, "latency_ms": round(elapsed, 3),
                        "fallback": result.mode == "local_template",
                    })
                    if guarded.block_reason:
                        raise ValidationStopped(guarded.block_reason)
                    # The generator catches ValueError for safe fallback. A refused
                    # reservation must additionally stop the entire comparison.
                    if not result.api_attempts or ledger.reserved >= ledger.budget:
                        raise ValidationStopped("validation_budget_or_pre_send_guard_stopped")
    completions = [event for event in ledger.events if event["kind"] == "completion"]
    known_cost = sum((token_cost(event["model"], event["input_tokens"], event["output_tokens"])
                      for event in completions if event["usage_known"]), Decimal(0))
    all_usage_known = all(event["usage_known"] for event in completions)
    summary = {}
    for model in models:
        rows = [row for row in observations if row["model"] == model]
        summary[model] = {
            "sample_count": len(rows), "provider_accepted_count": sum(row["provider_accepted"] for row in rows),
            "bounded_output_valid_count": sum(row["bounded_output_valid"] for row in rows),
            "fallback_count": sum(row["fallback"] for row in rows),
            "observed_p95_ms_nearest_rank": percentile95([row["latency_ms"] for row in rows]),
        }
    return {
        "mode": mode, "synthetic_only": True, "no_rules_or_dataset_uploaded": True,
        "pricing_reviewed_on": PRICING_REVIEWED_ON, "models": summary,
        "completion_attempts_in_ledger": len(completions), "reserved_upper_bound_usd": str(ledger.reserved),
        "known_usage_cost_usd": str(known_cost) if mode == "live" else None,
        "total_usage_cost_usd": str(known_cost) if mode == "live" and all_usage_known else None,
        "cost_method": "Reported usage at documented uncached on-demand rates; conservative estimate, not an invoice. No cache discount assumed.",
        "usage_complete": all_usage_known, "category_accuracy": None, "priority_macro_f1": None,
        "language_quality_native_reviewed": False, "production_quality_validated": False,
        "latency_scope": "direct_generation_adapter_only; excludes HTTP server, retrieval, encoder startup",
        "warning": "Small synthetic smoke test, not a gold-set accuracy benchmark or a production p95 guarantee. Mock tokens/timing are not provider measurements.",
        "observations": observations,
    }


def plan() -> dict:
    largest = max(token_cost(model, MAX_INPUT_TOKENS, MAX_COMPLETION_TOKENS) for model in RATES)
    return {
        "mode": "plan", "network_requests": 0, "secret_read": False,
        "models": list(RATES), "languages": list(LANGUAGES), "default_cases_per_model": 12,
        "max_completion_requests_including_retries": MAX_COMPLETION_REQUESTS,
        "max_model_probes": MAX_MODEL_PROBES, "max_input_tokens_reserved_per_attempt": MAX_INPUT_TOKENS,
        "max_completion_tokens_allowed": MAX_COMPLETION_TOKENS,
        "worst_case_all_48_attempts_on_120b_usd": str(largest * MAX_COMPLETION_REQUESTS),
        "hard_budget_usd": str(MAX_BUDGET_USD), "pricing_reviewed_on": PRICING_REVIEWED_ON,
        "requires_live_authorization_and_private_ledger": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "mock", "live"), default="plan")
    parser.add_argument("--model", action="append", choices=tuple(RATES))
    parser.add_argument("--rounds", type=int, choices=(1, 2), default=2)
    parser.add_argument("--budget-usd", default="1.00")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--env-file", type=Path,
                        help="Optional private 0600 dotenv file outside Git; read only in explicitly authorized live mode")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--acknowledge-paid-synthetic-data", action="store_true")
    parser.add_argument("--pricing-reviewed-on", help="Must match the documented date; recheck public Groq rates first")
    parser.add_argument("--trust-environment-proxy", action="store_true",
                        help="Use only the environment's existing approved proxy; requires httpx SOCKS support if configured")
    args = parser.parse_args(argv)
    ledger = None
    try:
        load_cases()
        if args.mode == "plan":
            report = plan()
        else:
            if args.mode == "live":
                if not args.acknowledge_paid_synthetic_data or not args.ledger:
                    raise ValidationStopped("live_requires_explicit_authorization_and_private_ledger")
                if args.pricing_reviewed_on != PRICING_REVIEWED_ON:
                    raise ValidationStopped("verify_current_public_model_prices_before_live_run")
                key = read_live_key(args.env_file)
            else:
                key = "synthetic-offline-test-key"
            ledger = BudgetLedger(Decimal(args.budget_usd), args.ledger, mode=args.mode)
            report = asyncio.run(run_comparison(args.mode, key, ledger,
                list(dict.fromkeys(args.model or RATES)), args.rounds,
                trust_environment_proxy=args.trust_environment_proxy if args.mode == "live" else False,
                transport=httpx.MockTransport(mock_response) if args.mode == "mock" else None))
        if args.output:
            write_private_json(args.output, report, exclusive=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("mode") == "plan" or all(
            row["bounded_output_valid"] and row["provider_accepted"] for row in report["observations"]) else 1
    except Exception as exc:
        # Never print exception messages, provider response bodies, request headers,
        # prompts, generated drafts, proxy URLs, or secret environment values.
        reason = str(exc) if isinstance(exc, ValidationStopped) else "validation_failed_redacted"
        print(json.dumps({"status": "blocked", "reason": reason, "mode": args.mode,
                          "error_type": type(exc).__name__, "details_redacted": True,
                          "requests_reserved": len(ledger.events) if ledger else 0,
                          "reserved_upper_bound_usd": str(ledger.reserved) if ledger else "0"}))
        return 2
    finally:
        if ledger:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
