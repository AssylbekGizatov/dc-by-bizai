"""Private local SQLite queue, deduplication state, and append-only review feedback."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from .private_files import restrict_private_directory, restrict_private_file
from .schemas import ReviewRequest, Ticket


class RepeatCheck(NamedTuple):
    duplicate: bool
    position: int


class ConflictError(Exception):
    pass


class TicketStore:
    def __init__(self, path: str, *, busy_timeout_seconds: float = 1.0):
        if path != ":memory:":
            parent = Path(path).parent
            created_parent = not parent.exists()
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if created_parent:
                restrict_private_directory(parent)
            # Create/chmod before SQLite creates WAL companions; they inherit 0600.
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(descriptor)
            restrict_private_file(path)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=busy_timeout_seconds, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("casefold", 1, lambda value: value.casefold() if value is not None else None, deterministic=True)
        self.lock = threading.RLock()
        self._closed = False
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
                category TEXT NOT NULL, language TEXT NOT NULL, priority TEXT NOT NULL,
                body TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tickets_filter ON tickets(status, priority, category);
            CREATE TABLE IF NOT EXISTS idempotency (
                request_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                ticket_id TEXT NOT NULL REFERENCES tickets(id)
            );
            CREATE TABLE IF NOT EXISTS dedup (
                id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_key TEXT NOT NULL,
                problem_hash TEXT NOT NULL, token_hashes TEXT NOT NULL, observed_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dedup_lookup ON dedup(reporter_key, observed_at);
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                created_at TEXT NOT NULL, previous_draft TEXT NOT NULL, edited_draft TEXT NOT NULL,
                status TEXT NOT NULL, reviewer_note TEXT NOT NULL, revision INTEGER NOT NULL
            );
        """)
        if path != ":memory:":
            restrict_private_file(path)
            for suffix in ("-wal", "-shm"):
                companion = Path(path + suffix)
                if companion.exists():
                    restrict_private_file(companion)

    def close(self) -> None:
        with self.lock:
            if not self._closed:
                self.connection.close()
                self._closed = True

    def check_ready(self) -> None:
        """A closed or unavailable store must not be advertised as ready."""
        with self.lock:
            self.connection.execute("SELECT revision FROM tickets LIMIT 1").fetchone()

    def existing(self, key: str, request_hash: str) -> Ticket | None:
        with self.lock:
            row = self.connection.execute("SELECT * FROM idempotency WHERE request_key=?", (key,)).fetchone()
            if row is None:
                return None
            if row["request_hash"] != request_hash:
                raise ConflictError("Idempotency key is already associated with a different request")
            return self.get(row["ticket_id"])

    @contextmanager
    def write_transaction(self):
        """Join a short synchronous transaction, or own its commit/rollback.

        Creation groups its repeat observation and ticket insert here after
        generation finishes. Never hold this context across an await.
        """
        with self.lock:
            owns_transaction = not self.connection.in_transaction
            if owns_transaction:
                self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                if owns_transaction:
                    self.connection.execute("COMMIT")
            except BaseException:
                if owns_transaction and self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def add(self, ticket: Ticket, key: str | None = None, request_hash: str | None = None) -> Ticket:
        with self.write_transaction():
            # Another process may have committed while generation was running.
            # Check under the write transaction before inserting a second ticket.
            if key:
                existing = self.existing(key, request_hash or "")
                if existing is not None:
                    return existing
            self.connection.execute("INSERT INTO tickets(id,created_at,status,category,language,priority,body,revision) VALUES (?,?,?,?,?,?,?,?)",
                (ticket.id, ticket.created_at, ticket.status, ticket.result.category.value, ticket.result.lang,
                 ticket.result.priority, ticket.model_dump_json(), ticket.revision))
            if key:
                self.connection.execute("INSERT INTO idempotency(request_key,request_hash,ticket_id) VALUES(?,?,?)", (key, request_hash, ticket.id))
        return ticket

    def get(self, ticket_id: str) -> Ticket | None:
        with self.lock:
            row = self.connection.execute("SELECT body FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return Ticket.model_validate_json(row["body"]) if row else None

    def list(self, *, status: str | None = None, category: str | None = None, language: str | None = None,
             priority: str | None = None, search: str | None = None, needs_human: bool | None = None,
             urgent: bool | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        clauses, args = [], []
        for col, value in (("status", status), ("category", category), ("language", language), ("priority", priority)):
            if value:
                clauses.append(f"{col}=?")
                args.append(value)
        if needs_human is not None:
            clauses.append("json_extract(body, '$.result.needs_human')=?")
            args.append(int(needs_human))
        if urgent is not None:
            clauses.append("priority IN ('p0','p1')" if urgent else "priority NOT IN ('p0','p1')")
        if search:
            # JSON body search supports short MVP queues; parameterized to avoid SQL injection.
            clauses.append("casefold(body) LIKE ? ESCAPE '\\'")
            escaped = search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{escaped}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            total = self.connection.execute("SELECT COUNT(*) FROM tickets" + where, args).fetchone()[0]
            rows = self.connection.execute("SELECT body FROM tickets" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        return {"items": [json.loads(row["body"]) for row in rows], "total": total}

    def review(self, ticket_id: str, change: ReviewRequest) -> Ticket | None:
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                old = self.get(ticket_id)
                if old is None:
                    self.connection.execute("ROLLBACK")
                    return None
                if change.expected_revision is not None and old.revision != change.expected_revision:
                    raise ConflictError("The ticket has changed; reload before saving")
                if old.status == "simulated_sent":
                    unchanged = all(value is None or value == getattr(old, name) for name, value in (
                        ("draft_reply", change.draft_reply), ("reviewer_note", change.reviewer_note), ("status", change.status)))
                    if not unchanged:
                        raise ConflictError("A simulated-sent ticket is closed and cannot be changed")
                    self.connection.execute("COMMIT")
                    return old
                new = old.model_copy(deep=True)
                if change.draft_reply is not None:
                    new.draft_reply = change.draft_reply
                if change.reviewer_note is not None:
                    new.reviewer_note = change.reviewer_note
                if change.status is not None:
                    new.status = change.status
                new.revision += 1
                self.connection.execute("UPDATE tickets SET status=?,body=?,revision=? WHERE id=?",
                                        (new.status, new.model_dump_json(), new.revision, new.id))
                self.connection.execute("INSERT INTO feedback(ticket_id,created_at,previous_draft,edited_draft,status,reviewer_note,revision) VALUES(?,?,?,?,?,?,?)",
                    (new.id, datetime.now(timezone.utc).isoformat(), old.draft_reply, new.draft_reply, new.status, new.reviewer_note, new.revision))
                self.connection.execute("COMMIT")
                return new
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def duplicate(self, reporter: str | None, text: str, observed_at: float | None = None) -> bool:
        return self.check_repeat(reporter, text, observed_at).duplicate

    def check_repeat(self, reporter: str | None, text: str, observed_at: float | None = None) -> "RepeatCheck":
        """«1 игрок, 1 проблема за час» и счётчик обращений игрока за последний час.

        position — номер этого обращения среди обращений игрока за час до него включительно.
        """
        if not reporter:
            return RepeatCheck(False, 0)  # Never merge anonymous players merely because their messages match.
        stamp = observed_at if observed_at is not None else time.time()
        reporter_key = hashlib.sha256(reporter.encode()).hexdigest()
        normalized = " ".join(text.casefold().split())
        problem_hash = hashlib.sha256(normalized.encode()).hexdigest()
        tokens = {hashlib.sha256(w.encode()).hexdigest()[:16] for w in normalized.split()}
        with self.write_transaction():
            rows = self.connection.execute("SELECT problem_hash,token_hashes FROM dedup WHERE reporter_key=? AND observed_at>=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 100",
                (reporter_key, stamp - 3600, stamp + 3600)).fetchall()
            duplicate = False
            for row in rows:
                previous = set(json.loads(row["token_hashes"]))
                similarity = len(tokens & previous) / max(1, len(tokens | previous))
                if row["problem_hash"] == problem_hash or (len(tokens) >= 5 and similarity >= 0.85):
                    duplicate = True
                    break
            # Flood counts only earlier events: shuffled offline input never flags the first requests of an hour.
            earlier = self.connection.execute("SELECT COUNT(*) FROM dedup WHERE reporter_key=? AND observed_at>? AND observed_at<=?",
                (reporter_key, stamp - 3600, stamp)).fetchone()[0]
            self.connection.execute("INSERT INTO dedup(reporter_key,problem_hash,token_hashes,observed_at) VALUES(?,?,?,?)", (reporter_key, problem_hash, json.dumps(sorted(tokens)), stamp))
            # Historical offline inputs may be shuffled. Do not purge them using the
            # newest event timestamp. Match both orders within the same one-hour window.
            # Live traffic gets a 48h TTL; all modes have a hard hashed-state row cap.
            if abs(stamp - time.time()) < 86400:
                self.connection.execute("DELETE FROM dedup WHERE observed_at<?", (time.time() - 172800,))
            self.connection.execute("DELETE FROM dedup WHERE id <= (SELECT COALESCE(MAX(id), 0) - 100000 FROM dedup)")
        return RepeatCheck(duplicate, int(earlier) + 1)

    def feedback(self, ticket_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM feedback WHERE ticket_id=? ORDER BY id", (ticket_id,))]
