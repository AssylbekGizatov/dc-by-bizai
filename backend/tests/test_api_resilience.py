"""Real ASGI routes, SQLite contention and safe error/reporting behavior."""
from __future__ import annotations

import json
import logging
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, logger

PAYLOAD = {"text": "Синтетический пример: застрял в текстурах", "kind": "report"}


@pytest.fixture
def client():
    with TestClient(create_app(Settings(mode="test", database_path=":memory:", enable_groq=False))) as value:
        yield value


def test_review_requires_revision_and_rejects_boolean_revision(client):
    ticket = client.post("/api/tickets", json=PAYLOAD).json()
    path = f"/api/tickets/{ticket['id']}/review"
    assert client.patch(path, json={"status": "reviewed"}).status_code == 428
    assert client.patch(path, json={"status": "reviewed", "expected_revision": True}).status_code == 422
    assert client.get(f"/api/tickets/{ticket['id']}").json()["revision"] == 1
    assert client.get(f"/api/tickets/{ticket['id']}/feedback").json()["items"] == []


def test_security_headers_on_early_rejections(client):
    for response in (
        client.post("/api/tickets", json=PAYLOAD, headers={"Origin": "https://hostile.invalid"}),
        client.post("/api/tickets", content=b"x" * 131073),
        client.post("/api/tickets", json={"text": ""}),
    ):
        assert response.status_code in {403, 413, 422}
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert len(response.headers["X-Request-ID"]) == 32


def test_http_read_rate_limit_is_independent_of_player_flood():
    cfg = Settings(mode="test", database_path=":memory:", request_rate_per_minute=2, enable_groq=False)
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/tickets").status_code == 200
        assert c.get("/api/tickets").status_code == 200
        rejected = c.get("/api/tickets")
        assert rejected.status_code == 429 and int(rejected.headers["Retry-After"]) > 0
        assert rejected.headers["Cache-Control"] == "no-store"
        assert c.get("/health").status_code == c.get("/ready").status_code == 200
        assert c.app.state.copilot.store.list()["total"] == 0


def test_readiness_fails_if_storage_is_closed(client):
    client.app.state.copilot.store.close()
    ready = client.get("/ready")
    assert ready.status_code == 503 and ready.headers["Retry-After"] == "1"
    assert client.get("/health").status_code == 200


def test_busy_database_returns_retryable_error_without_partial_review(tmp_path):
    path = str(tmp_path / "private.sqlite")
    cfg = Settings(mode="test", database_path=path, sqlite_busy_timeout_seconds=.05, enable_groq=False)
    with TestClient(create_app(cfg)) as c:
        ticket = c.post("/api/tickets", json=PAYLOAD).json()
        review_url = f"/api/tickets/{ticket['id']}/review"
        change = {"draft_reply": "Synthetic saved edit", "reviewer_note": "Preserved note", "expected_revision": 1}
        locker = sqlite3.connect(path, isolation_level=None)
        try:
            locker.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            response = c.patch(review_url, json=change)
            assert response.status_code == 503 and response.headers["Retry-After"] == "1"
            assert time.perf_counter() - started < 2
            assert path not in response.text
        finally:
            locker.execute("ROLLBACK")
            locker.close()
        assert c.get(f"/api/tickets/{ticket['id']}").json()["revision"] == 1
        retry = c.patch(review_url, json=change)
        assert retry.status_code == 200 and retry.json()["reviewer_note"] == "Preserved note"
        assert len(c.get(f"/api/tickets/{ticket['id']}/feedback").json()["items"]) == 1


def test_logs_do_not_contain_bearer_body_query_or_ticket_id(caplog, monkeypatch):
    sentinel = "SYNTHETIC_PRIVATE_SENTINEL"
    cfg = Settings(mode="test", database_path=":memory:", api_token=sentinel, enable_groq=False)
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level(logging.INFO, logger="copilot.http"), TestClient(create_app(cfg)) as c:
        headers = {"Authorization": "Bearer " + sentinel}
        created = c.post("/api/tickets", headers=headers, json={"text": sentinel}).json()
        c.get("/api/tickets", headers=headers, params={"search": sentinel})
        c.get(f"/api/tickets/{created['id']}", headers=headers)
        c.get("/api/tickets/" + sentinel, headers=headers)
    entries = [record.message for record in caplog.records if record.name == "copilot.http"]
    assert entries and sentinel not in " ".join(entries) and created["id"] not in " ".join(entries)
    for entry in entries:
        record = json.loads(entry)
        assert record["event"] == "http_request" and record["duration_ms"] >= 0
        assert "?" not in record["route"]


def test_unexpected_error_is_sanitized_in_response_and_logs(client, caplog, monkeypatch):
    sentinel = "SYNTHETIC_PRIVATE_ERROR_DETAILS"
    def broken_list(**kwargs):
        raise RuntimeError(sentinel)
    monkeypatch.setattr(client.app.state.copilot.store, "list", broken_list)
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level(logging.INFO, logger="copilot.http"):
        response = client.get("/api/tickets")
    assert response.status_code == 500 and sentinel not in response.text
    entries = [record.message for record in caplog.records if record.name == "copilot.http"]
    assert sentinel not in " ".join(entries)
    assert any(json.loads(entry)["event"] == "request_failed" for entry in entries)


@pytest.mark.parametrize("params", [{"status": "unknown"}, {"priority": "critical"}, {"language": "xxx"}, {"urgent": "perhaps"}, {"offset": -1}])
def test_invalid_queue_filters_are_validation_errors(client, params):
    assert client.get("/api/tickets", params=params).status_code == 422


@pytest.mark.parametrize("values", [
    {"request_rate_per_minute": 0}, {"request_rate_per_minute": 10001}, {"sqlite_busy_timeout_seconds": 0},
    {"groq_input_usd_per_million": float("nan")}, {"groq_output_usd_per_million": -1},
    {"cors_origins": ("*",)}, {"cors_origins": ("https://example.test/path",)},
])
def test_unsafe_configuration_fails_at_startup(values):
    with pytest.raises(ValueError):
        Settings(mode="test", database_path=":memory:", **values)


def test_static_server_refuses_private_files_even_inside_dist(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Synthetic UI</h1>")
    (tmp_path / "app.js").write_text("/* synthetic */")
    for name in (".env", "queue.sqlite3", "private.json", "credentials.txt", "app.js.map"):
        (tmp_path / name).write_text("SYNTHETIC_PRIVATE_SENTINEL")
    cfg = Settings(mode="test", database_path=":memory:", frontend_dist=str(tmp_path), enable_groq=False)
    with TestClient(create_app(cfg)) as c:
        assert c.get("/").status_code == c.get("/app.js").status_code == 200
        for name in (".env", "queue.sqlite3", "private.json", "credentials.txt", "app.js.map", "missing.js"):
            response = c.get("/" + name)
            assert response.status_code == 404 and "SYNTHETIC_PRIVATE_SENTINEL" not in response.text


def test_settings_repr_redacts_both_secrets():
    value = Settings(api_token="synthetic-admin-secret", groq_api_key="synthetic-provider-secret")
    assert "synthetic-admin-secret" not in repr(value)
    assert "synthetic-provider-secret" not in repr(value)


@pytest.mark.parametrize("failure_table", ["tickets", "idempotency"])
def test_failed_create_rolls_back_repeat_state_and_retry_is_not_duplicate(client, failure_table):
    store = client.app.state.copilot.store
    # Fail both before ticket insertion and after it, while inserting the key.
    store.connection.execute(f"CREATE TRIGGER fail_create BEFORE INSERT ON {failure_table} BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END")
    payload = PAYLOAD | {"player_id": "synthetic-atomic-player"}
    headers = {"Idempotency-Key": "synthetic-atomic-create"}
    failed = client.post("/api/tickets", json=payload, headers=headers)
    assert failed.status_code == 503
    for table in ("tickets", "dedup", "idempotency"):
        assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert client.app.state.copilot.metrics["tickets_processed"] == 0
    store.connection.execute("DROP TRIGGER fail_create")
    retried = client.post("/api/tickets", json=payload, headers=headers)
    assert retried.status_code == 201
    assert retried.json()["result"]["is_spam_or_duplicate"] is False
    assert not any(reason.startswith("Флуд") for reason in retried.json()["result"]["reasons"])
    replay = client.post("/api/tickets", json=payload, headers=headers)
    assert replay.json()["id"] == retried.json()["id"]
    for table in ("tickets", "dedup", "idempotency"):
        assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_mock_provider_attempt_still_counted_when_storage_fails(client, monkeypatch):
    from dataclasses import replace
    svc = client.app.state.copilot
    original = svc.generator.generate
    async def synthetic_provider_result(*args, **kwargs):
        local = await original(*args, **kwargs)
        # Explicitly mocked accounting; this makes no provider/network call.
        return replace(local, mode="groq:synthetic-mock", api_attempts=1, input_tokens=10, output_tokens=5, cost_usd=.00001)
    monkeypatch.setattr(svc.generator, "generate", synthetic_provider_result)
    svc.store.connection.execute("CREATE TRIGGER fail_create BEFORE INSERT ON tickets BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    payload = PAYLOAD | {"player_id": "synthetic-provider-accounting"}
    headers = {"Idempotency-Key": "synthetic-provider-accounting"}
    assert client.post("/api/tickets", json=payload, headers=headers).status_code == 503
    assert svc.metrics["groq_api_attempts"] == svc.metrics["groq_calls_accepted"] == 1
    assert svc.metrics["tickets_processed"] == 0
    svc.store.connection.execute("DROP TRIGGER fail_create")
    assert client.post("/api/tickets", json=payload, headers=headers).status_code == 201
    assert svc.metrics["groq_api_attempts"] == svc.metrics["groq_calls_accepted"] == 1
    assert svc.metrics["tickets_processed"] == 1


@pytest.mark.parametrize("mutation", [
    {"status": "pending"}, {"status": "reviewed"}, {"status": "escalated"},
    {"draft_reply": "Rewritten after simulation"}, {"reviewer_note": "Rewritten note"},
])
def test_simulated_sent_ticket_is_immutable_at_api_boundary(client, mutation):
    created = client.post("/api/tickets", json=PAYLOAD).json()
    path = f"/api/tickets/{created['id']}"
    sent = client.patch(path + "/review", json={"status": "simulated_sent", "reviewer_note": "Final synthetic note", "expected_revision": 1})
    assert sent.status_code == 200 and sent.json()["revision"] == 2
    changed = client.patch(path + "/review", json=mutation | {"expected_revision": 2})
    assert changed.status_code == 409
    assert client.get(path).json() == sent.json()
    assert len(client.get(path + "/feedback").json()["items"]) == 1
    noop = client.patch(path + "/review", json={"status": "simulated_sent", "draft_reply": sent.json()["draft_reply"],
        "reviewer_note": "Final synthetic note", "expected_revision": 2})
    assert noop.status_code == 200 and noop.json()["revision"] == 2
    assert len(client.get(path + "/feedback").json()["items"]) == 1
