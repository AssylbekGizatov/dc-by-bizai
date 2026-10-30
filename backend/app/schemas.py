from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Category(str, Enum):
    insult = "complaint.insult"
    cheat = "complaint.cheat"
    dm = "complaint.dm"
    scam = "complaint.scam"
    rmt_ads = "complaint.rmt_ads"
    admin = "complaint.admin"
    other = "complaint.other"
    invalid = "complaint.invalid"
    question = "report.question"
    help = "report.help"
    complaint = "report.complaint"
    account = "report.account"
    payment = "report.payment"
    offtopic = "report.offtopic"


Language = Literal["ru", "kk", "uz", "en", "es", "pt", "und"]
Priority = Literal["p0", "p1", "p2", "p3"]
Status = Literal["pending", "reviewed", "escalated", "simulated_sent"]


class Message(StrictModel):
    role: Literal["player", "reported_player", "admin"]
    text: str = Field(max_length=12_000)
    attachments: int = Field(default=0, ge=0, le=10_000, strict=True)
    ts: str | None = Field(default=None, max_length=64)


class TriageRequest(StrictModel):
    kind: Literal["complaint", "report"]
    messages: list[Message] = Field(min_length=1, max_length=50)
    ticket_id: str | None = Field(default=None, max_length=128)
    reporter_hash: str | None = Field(default=None, max_length=128)
    reported_hash: str | None = Field(default=None, max_length=128)
    created_at: datetime | None = None
    region: str | None = Field(default=None, max_length=32)
    server_lang: Language | None = None
    lang: Language | None = None  # A dataset hint, never a replacement for local detection.
    reported_nick: str | None = Field(default=None, max_length=100)
    rule_refs_raw: str | None = Field(default=None, max_length=200)
    images_count: int = Field(default=0, ge=0, le=10_000, strict=True)
    server: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def player_text_required(self) -> "TriageRequest":
        if not any(m.role == "player" and m.text.strip() for m in self.messages):
            raise ValueError("At least one non-empty player message is required")
        if sum(len(m.text) for m in self.messages) > 24_000:
            raise ValueError("Combined message text is limited to 24000 characters")
        return self


class Extracted(StrictModel):
    nickname: str | None
    rule_refs: list[str]
    has_evidence: bool
    server: str | None


class DraftReply(StrictModel):
    lang: Language
    text: str = Field(min_length=1, max_length=5000)
    cited: list[str] = Field(max_length=5)


class TriageResponse(StrictModel):
    lang: Language
    category: Category
    priority: Priority
    is_spam_or_duplicate: bool
    extracted: Extracted
    draft_reply: DraftReply
    needs_human: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]


class Citation(StrictModel):
    id: str
    ref: str
    title: str
    text: str
    section: str
    source: str
    synthetic: bool
    score: float = 0.0


class Diagnostics(StrictModel):
    language_method: str
    classifier_method: str
    retrieval_method: str
    generation_mode: str
    normalizations: list[str]
    warnings: list[str]
    timings_ms: dict[str, float]
    tokens: dict[str, int]
    estimated_cost_usd: float | None
    cache_hit: bool = False
    removed_admin_messages: int = 0
    evidence_mode: str = "count_only_not_inspected"
    confidence_kind: str = "heuristic_uncalibrated"


class AdminCreate(StrictModel):
    text: str = Field(min_length=1, max_length=12_000)
    kind: Literal["complaint", "report"] = "report"
    player_id: str | None = Field(default=None, max_length=128)
    server: str | None = Field(default=None, max_length=100)
    attachments_count: int = Field(default=0, ge=0, le=10_000, strict=True)
    server_lang: Language | None = None


class ReviewRequest(StrictModel):
    draft_reply: str | None = Field(default=None, min_length=1, max_length=5000)
    status: Status | None = None
    reviewer_note: str | None = Field(default=None, max_length=3000)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def nonempty(self) -> "ReviewRequest":
        if self.draft_reply is None and self.status is None and self.reviewer_note is None:
            raise ValueError("At least one review field is required")
        return self


class Ticket(StrictModel):
    id: str
    text: str
    normalized_text: str
    kind: Literal["complaint", "report"]
    created_at: str
    status: Status
    player_id: str | None
    server: str | None
    attachments_count: int
    result: TriageResponse
    citations: list[Citation]
    reviewer_note: str = ""
    draft_reply: str
    diagnostics: Diagnostics
    revision: int = 1
