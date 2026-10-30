"""Synthetic only. Every provider request is intercepted by MockTransport."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "validate_groq_synthetic", Path(__file__).resolve().parents[1] / "validate_groq_synthetic.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def current_analysis():
    case = harness.load_cases()[3]
    return harness.analyze(harness.TriageRequest(kind="report", messages=[{"role": "player", "text": case["text"]}]))


def settings(**kwargs):
    return harness.Settings(mode="test", enable_groq=True, groq_api_key="synthetic-offline-test-key",
        groq_model="openai/gpt-oss-20b", groq_input_usd_per_million=.075,
        groq_output_usd_per_million=.30, groq_max_retries=kwargs.pop("groq_max_retries", 1), **kwargs)


def run_one(handler, *, budget=Decimal("1.00")):
    async def run():
        ledger = harness.BudgetLedger(budget)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            guarded = harness.GuardedClient(client, ledger, harness.load_cases())
            generator = harness.DraftGenerator(settings(), guarded)
            result = await generator.generate(current_analysis(), [], True, False)
        return result, ledger, guarded
    return asyncio.run(run())


def test_plan_and_mock_never_read_key(monkeypatch, capsys):
    def forbidden(*args):
        raise AssertionError("Offline modes must not read a key")
    monkeypatch.setattr(harness, "read_live_key", forbidden)
    assert harness.main(["--mode", "plan", "--env-file", "/does/not/exist"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["network_requests"] == 0 and plan["secret_read"] is False
    assert Decimal(plan["worst_case_all_48_attempts_on_120b_usd"]) < Decimal(1)
    assert harness.main(["--mode", "mock", "--rounds", "1", "--env-file", "/does/not/exist"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["observations"]) == 12
    assert all(row["provider_accepted"] and row["bounded_output_valid"] for row in report["observations"])
    assert report["total_usage_cost_usd"] is None
    assert report["category_accuracy"] is None and not report["language_quality_native_reviewed"]


def test_live_requires_authorization_before_key_read(monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_live_key", lambda _: pytest.fail("Must gate before reading key"))
    assert harness.main(["--mode", "live"]) == 2
    assert json.loads(capsys.readouterr().out)["requests_reserved"] == 0


@pytest.mark.parametrize("value", ["0", "-1", "1.01", "NaN", "Infinity"])
def test_invalid_budgets_rejected(value):
    with pytest.raises(harness.ValidationStopped):
        harness.BudgetLedger(Decimal(value))


def test_each_retry_reserves_full_context_before_send():
    observed = []
    async def run():
        ledger = harness.BudgetLedger(Decimal(1))
        def handler(request):
            observed.append(len(ledger.events))
            if len(observed) == 1:
                return httpx.Response(429, json={"error": "synthetic"})
            return harness.mock_response(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            guarded = harness.GuardedClient(client, ledger, harness.load_cases())
            result = await harness.DraftGenerator(settings(), guarded).generate(current_analysis(), [], True, False)
        return result, ledger
    result, ledger = asyncio.run(run())
    assert observed == [1, 2]
    assert result.mode.startswith("groq:") and result.api_attempts == 2
    assert result.cost_usd is None  # First attempt has no billing usage.
    assert ledger.reserved == 2 * harness.token_cost("openai/gpt-oss-20b", harness.MAX_INPUT_TOKENS, 1024)
    assert ledger.events[0]["usage_known"] is False
    assert ledger.events[1]["usage_known"] is True


def test_budget_exhaustion_cannot_send_retry():
    calls = []
    def handler(request):
        calls.append(True)
        return httpx.Response(429, json={"error": "synthetic"})
    one_attempt = harness.token_cost("openai/gpt-oss-20b", harness.MAX_INPUT_TOKENS, 1024)
    result, ledger, guarded = run_one(handler, budget=one_attempt)
    assert len(calls) == 1 and len(ledger.events) == 1
    assert result.mode == "local_template"
    assert guarded.block_reason == "next_attempt_would_exceed_budget"


def test_request_hard_cap_is_independent_of_remaining_budget():
    ledger = harness.BudgetLedger(Decimal(1))
    for _ in range(harness.MAX_COMPLETION_REQUESTS):
        ledger.reserve("openai/gpt-oss-20b")
    assert ledger.reserved < Decimal(1)
    with pytest.raises(harness.ValidationStopped, match="hard_request_limit"):
        ledger.reserve("openai/gpt-oss-20b")


def test_model_probe_limit():
    ledger = harness.BudgetLedger(Decimal(1))
    for _ in range(harness.MAX_MODEL_PROBES):
        ledger.reserve(None)
    with pytest.raises(harness.ValidationStopped, match="hard_request_limit"):
        ledger.reserve(None)


@pytest.mark.parametrize("fault", ["401", "429", "refusal", "malformed", "unknown_citation", "missing_clause", "truncated"])
def test_failure_modes_use_bounded_fallback_and_redacted_ledger(fault):
    private_canary = "SYNTHETIC_PRIVATE_PROVIDER_CANARY"
    def handler(request):
        if fault in {"401", "429"}:
            return httpx.Response(int(fault), json={"error": private_canary})
        if fault == "malformed":
            return httpx.Response(200, content=private_canary)
        if fault == "refusal":
            answer = {"content": None, "refusal": private_canary}
        else:
            content = json.loads(harness.mock_response(request).json()["choices"][0]["message"]["content"])
            if fault == "unknown_citation":
                content["cited"] = [private_canary]
            elif fault == "missing_clause":
                content["clause_order"] = [0]
            answer = {"content": json.dumps(content)}
        return httpx.Response(200, json={"choices": [{"message": answer,
            "finish_reason": "length" if fault == "truncated" else "stop"}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 30}})
    result, ledger, _ = run_one(handler)
    assert result.mode == "local_template"
    assert harness.validate_draft(result.draft, [], False, harness.approved_clauses(current_analysis(), [], True))
    assert private_canary not in json.dumps(ledger.events)
    assert private_canary not in result.draft.text
    assert "synthetic-offline-test-key" not in json.dumps(ledger.events)
    if fault in {"401", "429", "malformed"}:
        assert result.cost_usd is None
    if fault == "refusal":
        assert all(event["refusal_detected"] for event in ledger.events)


def test_transport_failure_is_unknown_cost_not_free():
    def fail(request):
        raise httpx.ReadTimeout("synthetic-private-canary", request=request)
    result, ledger, _ = run_one(fail)
    assert result.mode == "local_template" and result.cost_usd is None
    assert ledger.events[0]["status"] == "transport_error_usage_unknown"
    assert ledger.reserved > 0
    assert "synthetic-private-canary" not in json.dumps(ledger.events)


def test_invalid_billed_usage_stops_future_requests():
    def handler(request):
        response = harness.mock_response(request).json()
        response["usage"]["completion_tokens"] = 1025
        return httpx.Response(200, json=response)
    _, ledger, guarded = run_one(handler)
    assert len(ledger.events) == 1
    assert guarded.block_reason == "provider_usage_exceeded_or_invalidated_bound"
    assert ledger.events[0]["usage_known"] is False


def test_secret_redaction_before_provider_payload():
    secret = "SYNTHETIC_ONLY_PASSWORD"
    raw = "Hello! How do I choose a job in the game? email@example.test password=" + secret + " +1 202 555 0100"
    sent = []
    def handler(request):
        sent.append(request.content.decode())
        return harness.mock_response(request)
    async def run():
        current = harness.analyze(harness.TriageRequest(kind="report", messages=[{"role": "player", "text": raw}]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            return await harness.DraftGenerator(settings(), client).generate(current, [], True, False)
    result = asyncio.run(run())
    assert result.mode.startswith("groq:")
    assert sent and all(secret not in value and "email@example.test" not in value and "202 555" not in value for value in sent)


def test_persistent_ledger_reserves_survive_reopen_and_are_private(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = harness.BudgetLedger(Decimal(1), path)
    ledger.reserve("openai/gpt-oss-120b")
    expected = ledger.reserved
    with pytest.raises(harness.ValidationStopped, match="holds_budget_lock"):
        harness.BudgetLedger(Decimal(1), path)
    ledger.close()
    reopened = harness.BudgetLedger(Decimal(1), path)
    assert reopened.reserved == expected and len(reopened.events) == 1
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    reopened.close()
    with pytest.raises(harness.ValidationStopped, match="invalid_do_not_reset"):
        harness.BudgetLedger(Decimal(1), path, mode="live")


def test_output_and_secret_paths_reject_git_or_permissive_files(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / ".git/HEAD").write_text("ref: refs/heads/main\n")
    with pytest.raises(harness.ValidationStopped, match="inside_git"):
        harness.private_path(checkout / "report.json")
    key_file = tmp_path / "private.env"
    key_file.write_text("GROQ_API_KEY=synthetic-only\n")
    key_file.chmod(0o644)
    if os.name != "nt":
        with pytest.raises(harness.ValidationStopped, match="permissions"):
            harness.read_live_key(key_file)
    key_file.chmod(0o600)
    assert harness.read_live_key(key_file) == "synthetic-only"
    link = tmp_path / "link.env"
    try:
        link.symlink_to(key_file)
    except OSError:
        if os.name == "nt":
            return  # Windows without Developer Mode cannot create a test symlink.
        raise
    with pytest.raises(harness.ValidationStopped, match="path_invalid"):
        harness.read_live_key(link)


def test_changed_fixture_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "unapproved.json"
    path.write_text('{"synthetic":true,"cases":[]}')
    monkeypatch.setattr(harness, "FIXTURE", path)
    with pytest.raises(harness.ValidationStopped, match="integrity_changed"):
        harness.load_cases()


@pytest.mark.parametrize("change", ["endpoint", "model", "output_cap", "tools", "private_text", "private_policy", "private_metadata"])
def test_request_guards_fail_before_network_or_budget_reservation(change):
    captured = []
    def capture(request):
        captured.append(json.loads(request.content))
        return harness.mock_response(request)
    run_one(capture)
    payload = captured[0]
    url = harness.API + "/chat/completions"
    if change == "endpoint":
        url = "https://example.test/not-authorized"
    elif change == "model":
        payload["model"] = "unpriced-model"
    elif change == "output_cap":
        payload["max_completion_tokens"] = 1025
    elif change == "tools":
        payload["tools"] = [{"type": "browser_search"}]
    else:
        data = json.loads(payload["messages"][1]["content"])
        if change == "private_text":
            data["player_statement"] = "NOT_AN_APPROVED_FIXTURE"
        elif change == "private_policy":
            data["policy"] = [{"text": "NOT_AN_APPROVED_POLICY"}]
        else:
            data["private_metadata"] = "NOT_AUTHORIZED"
        payload["messages"][1]["content"] = json.dumps(data)
    async def run():
        ledger = harness.BudgetLedger(Decimal(1))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Guard sent a request")), trust_env=False) as client:
            guarded = harness.GuardedClient(client, ledger, harness.load_cases())
            with pytest.raises(harness.ValidationStopped):
                await guarded.post(url, json=payload, headers={"Authorization": "Bearer synthetic-only"})
        assert ledger.events == []
    asyncio.run(run())


def test_cli_errors_do_not_leak_exception_content(monkeypatch, capsys):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("SYNTHETIC_PRIVATE_EXCEPTION_CANARY")
    monkeypatch.setattr(harness, "run_comparison", fail)
    assert harness.main(["--mode", "mock"]) == 2
    output = capsys.readouterr().out
    assert "SYNTHETIC_PRIVATE_EXCEPTION_CANARY" not in output
    assert json.loads(output)["details_redacted"] is True


def test_real_loopback_pipeline_with_mock_provider():
    ledger = harness.BudgetLedger(Decimal("0.05"))
    report = asyncio.run(harness.run_comparison("mock", "synthetic-offline-key", ledger,
        ["openai/gpt-oss-120b"], 1, scope="pipeline", transport=httpx.MockTransport(harness.mock_response)))
    assert report["latency_scope"].startswith("loopback_http_nlp_rag_generation_sqlite")
    assert report["completion_attempts_in_ledger"] == 6
    assert report["total_usage_cost_usd"] is None
    assert all(row["api_attempts"] == 1 and row["provider_accepted"] for row in report["observations"])


def test_oversized_synthetic_prompt_cannot_exceed_reserved_input_bound():
    captured = []
    def capture(request):
        captured.append(json.loads(request.content))
        return harness.mock_response(request)
    run_one(capture)
    payload = captured[0]
    payload["messages"][0]["content"] = "x" * harness.MAX_INPUT_TOKENS
    async def run():
        ledger = harness.BudgetLedger(Decimal("0.05"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Must not send oversized prompt"))) as client:
            guarded = harness.GuardedClient(client, ledger, harness.load_cases())
            with pytest.raises(harness.ValidationStopped, match="input_exceeds"):
                await guarded.post(harness.API + "/chat/completions", json=payload, headers={})
        assert ledger.events == []
    asyncio.run(run())


def test_percentile_is_nearest_rank_and_empty_is_unknown():
    assert harness.percentile95([]) is None
    assert harness.percentile95(list(range(1, 21))) == 19
