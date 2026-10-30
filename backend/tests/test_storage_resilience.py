"""Transactional storage checks with independent connections and synthetic tickets."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import asyncio
import sqlite3
import threading

import pytest

from app.schemas import ReviewRequest, Ticket
from app.schemas import TriageRequest
from app.config import Settings
from app.service import CopilotService
from app.storage import ConflictError, TicketStore


def ticket(identifier="synthetic-a", *, priority="p2", needs_human=True):
    return Ticket.model_validate({
        "id": identifier, "text": "Synthetic private request", "normalized_text": "Synthetic private request",
        "kind": "report", "created_at": "2026-01-01T00:00:00+00:00", "status": "pending",
        "player_id": None, "server": None, "attachments_count": 0,
        "result": {"lang": "en", "category": "report.help", "priority": priority,
            "is_spam_or_duplicate": False, "extracted": {"nickname": None, "rule_refs": [], "has_evidence": False, "server": None},
            "draft_reply": {"lang": "en", "text": "Synthetic draft", "cited": []},
            "needs_human": needs_human, "confidence": .5, "reasons": []},
        "citations": [], "reviewer_note": "Initial private note", "draft_reply": "Synthetic draft",
        "diagnostics": {"language_method": "synthetic", "classifier_method": "synthetic", "retrieval_method": "synthetic",
            "generation_mode": "local_template", "normalizations": [], "warnings": [], "timings_ms": {},
            "tokens": {}, "estimated_cost_usd": 0.0},
    })


def test_independent_connections_commit_one_idempotent_ticket(tmp_path):
    path = str(tmp_path / "queue.sqlite")
    stores = [TicketStore(path), TicketStore(path)]
    barrier = threading.Barrier(2)
    def create(index):
        barrier.wait()
        return stores[index].add(ticket(f"synthetic-{index}"), "same-key", "same-body").id
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(create, range(2)))
        assert ids[0] == ids[1]
        assert stores[0].list()["total"] == 1
        with pytest.raises(ConflictError):
            stores[1].add(ticket("other"), "same-key", "different-body")
        assert stores[0].list()["total"] == 1
    finally:
        for store in stores:
            store.close()


def test_two_administrators_preserve_winning_draft_note_and_one_history_row(tmp_path):
    path = str(tmp_path / "queue.sqlite")
    first, second = TicketStore(path), TicketStore(path)
    first.add(ticket())
    barrier = threading.Barrier(2)
    def review(pair):
        index, store = pair
        barrier.wait()
        try:
            return store.review("synthetic-a", ReviewRequest(expected_revision=1, draft_reply=f"Admin {index}", reviewer_note=f"Note {index}"))
        except ConflictError:
            return None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(review, enumerate((first, second))))
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        saved = first.get("synthetic-a")
        assert saved.revision == 2 and saved.draft_reply == winners[0].draft_reply
        assert saved.reviewer_note == winners[0].reviewer_note
        assert len(first.feedback("synthetic-a")) == 1
        # A later status-only update does not erase the note or draft.
        changed = second.review(saved.id, ReviewRequest(expected_revision=2, status="escalated"))
        assert changed.reviewer_note == saved.reviewer_note and changed.draft_reply == saved.draft_reply
    finally:
        first.close()
        second.close()


def test_failed_feedback_insert_rolls_back_entire_review(tmp_path):
    store = TicketStore(str(tmp_path / "queue.sqlite"))
    try:
        store.add(ticket())
        store.connection.execute("CREATE TRIGGER fail_feedback BEFORE INSERT ON feedback BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            store.review("synthetic-a", ReviewRequest(expected_revision=1, draft_reply="Uncommitted edit", reviewer_note="Uncommitted note"))
        saved = store.get("synthetic-a")
        assert saved.revision == 1 and saved.draft_reply == "Synthetic draft"
        assert saved.reviewer_note == "Initial private note" and store.feedback(saved.id) == []
    finally:
        store.close()


def test_filters_apply_before_pagination_and_total(tmp_path):
    store = TicketStore(str(tmp_path / "queue.sqlite"))
    try:
        for i in range(70):
            store.add(ticket(f"synthetic-{i:03}", priority="p1" if i % 2 else "p3", needs_human=i % 3 == 0))
        first = store.list(urgent=True, needs_human=True, limit=5)
        second = store.list(urgent=True, needs_human=True, limit=5, offset=5)
        assert first["total"] == second["total"] == 12
        assert len(first["items"]) == len(second["items"]) == 5
        assert {item["id"] for item in first["items"]}.isdisjoint({item["id"] for item in second["items"]})
        assert all(item["result"]["priority"] == "p1" and item["result"]["needs_human"] for item in first["items"] + second["items"])
    finally:
        store.close()


def test_restart_keeps_edits_and_idempotency(tmp_path):
    path = str(tmp_path / "queue.sqlite")
    store = TicketStore(path)
    store.add(ticket(), "synthetic-key", "synthetic-body")
    store.review("synthetic-a", ReviewRequest(expected_revision=1, reviewer_note="Persist after restart"))
    store.close()
    store.close()  # shutdown cleanup is idempotent
    reopened = TicketStore(path)
    try:
        reopened.check_ready()
        assert reopened.existing("synthetic-key", "synthetic-body").reviewer_note == "Persist after restart"
        assert len(reopened.feedback("synthetic-a")) == 1
    finally:
        reopened.close()
    with pytest.raises(sqlite3.ProgrammingError):
        reopened.check_ready()


def test_cross_service_create_race_commits_only_one_repeat_observation(tmp_path, monkeypatch):
    cfg = Settings(mode="test", database_path=str(tmp_path / "shared.sqlite"), enable_groq=False)
    services = [CopilotService(cfg), CopilotService(cfg)]
    barrier = threading.Barrier(2)
    request = TriageRequest(kind="report", reporter_hash="synthetic-race-player", messages=[{"role": "player", "text": "Я застрял в текстурах"}])
    for svc in services:
        original = svc.generator.generate
        async def synchronized_generation(*args, _original=original, **kwargs):
            barrier.wait(timeout=10)
            return await _original(*args, **kwargs)
        monkeypatch.setattr(svc.generator, "generate", synchronized_generation)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda svc: asyncio.run(svc.process(request, idempotency_key="synthetic-shared-key")), services))
        assert results[0].id == results[1].id
        assert not any(result.result.is_spam_or_duplicate for result in results)
        for table in ("tickets", "dedup", "idempotency"):
            assert services[0].store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    finally:
        for svc in services:
            asyncio.run(svc.close())


def test_batch_without_ticket_persistence_keeps_repeat_and_flood_history():
    svc = CopilotService(Settings(mode="test", database_path=":memory:", enable_groq=False, flood_limit_per_hour=2))
    async def scenario():
        try:
            base = TriageRequest(kind="report", reporter_hash="synthetic-batch-player", messages=[{"role": "player", "text": "Я застрял в текстурах"}])
            first = await svc.process(base, persist=False)
            repeated = await svc.process(base, persist=False)
            third = await svc.process(base.model_copy(update={"messages": TriageRequest(kind="report", messages=[{"role": "player", "text": "Где найти работу?"}]).messages}), persist=False)
            assert first.result.is_spam_or_duplicate is False
            assert repeated.result.is_spam_or_duplicate is True
            assert any(reason.startswith("Флуд: 3-е") for reason in third.result.reasons)
            assert svc.store.list()["total"] == 0
            assert svc.store.connection.execute("SELECT COUNT(*) FROM dedup").fetchone()[0] == 3
        finally:
            await svc.close()
    asyncio.run(scenario())


def test_search_casefolds_cyrillic_and_keeps_wildcards_literal():
    store = TicketStore(":memory:")
    try:
        item = ticket()
        item.text = "Не работает функция ФОНАРИКА, кнопка_1 и 50% заряда"
        store.add(item)
        assert store.list(search="ФУНКЦИЯ фонарика")["total"] == 1
        assert store.list(search="КНОПКА_1")["total"] == 1
        assert store.list(search="50%")["total"] == 1
        assert store.list(search="кнопка_9")["total"] == 0
        assert store.list(search="50_")["total"] == 0
    finally:
        store.close()
