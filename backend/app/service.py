from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import Counter, OrderedDict
from datetime import datetime, timezone

from .config import Settings
from .classifier import LocalIntentClassifier
from .generation import DraftGenerator
from .nlp import analyze
from .retrieval import RuleIndex
from .schemas import Diagnostics, DraftReply, Ticket, TriageRequest, TriageResponse
from .storage import TicketStore
from .taxonomy import load_taxonomy


class CopilotService:
    def __init__(self, settings: Settings, generator: DraftGenerator | None = None):
        self.settings = settings
        self.taxonomy = load_taxonomy(settings.taxonomy_path)
        self.index = RuleIndex(settings.rules_path, settings.local_encoder_path)
        if settings.mode == "production" and self.index.synthetic:
            raise ValueError("Production cannot use synthetic policies")
        self.classifier = LocalIntentClassifier(self.index.encoder) if self.index.encoder else None
        self.store = TicketStore(settings.database_path)
        self.generator = generator or DraftGenerator(settings)
        self.cache: OrderedDict[str, tuple] = OrderedDict()
        self.metrics = Counter()
        self.latencies: list[float] = []
        self._create_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.generator.close()
        self.store.close()

    def health(self) -> dict:
        return {"status": "ok", "mode": self.settings.mode, "auth_required": bool(self.settings.api_token),
                "rules_count": len(self.index.rules), "real_rules_loaded": not self.index.synthetic,
                "generation_mode": "groq_configured_not_verified" if self.settings.enable_groq and self.settings.groq_api_key else "local_template",
                "retrieval_mode": self.index.method, "local_encoder_loaded": bool(self.index.encoder),
                "classifier_mode": "local_e5_prototypes+lexical_not_finetuned" if self.classifier else "local_lexical_heuristics_not_trained", "model_quality_validated": False,
                "private_corpus_external_processing": self.settings.allow_private_data_to_groq,
                "rules_version": self.index.version, "taxonomy_version": self.taxonomy["version"], "taxonomy_draft": self.taxonomy["draft"]}

    async def process(self, request: TriageRequest, *, persist: bool = True, idempotency_key: str | None = None) -> Ticket:
        # Single-process SQLite queue: serialize state-changing ticket creation so retries
        # cannot race dedup or incur duplicate generation. Run bulk inference via CLI.
        async with self._create_lock:
            request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
            key = idempotency_key or ("ticket:" + request.ticket_id if request.ticket_id else None)
            if persist and key:
                existing = self.store.existing(key, request_hash)
                if existing is not None:
                    self.metrics["idempotency_hits"] += 1
                    return existing
            started = time.perf_counter()
            analysis = analyze(request)
            if self.classifier:
                analysis = self.classifier.refine(analysis, request.kind)
            nlp_ms = (time.perf_counter() - started) * 1000
            references = self.index.unresolved_references(analysis.extracted.rule_refs)
            cache_payload = {"text": analysis.text, "kind": request.kind, "lang": analysis.language,
                             "evidence": analysis.evidence_count, "nickname": analysis.extracted.nickname,
                             "refs": analysis.extracted.rule_refs, "server": analysis.extracted.server,
                             "rules": self.index.version, "model": self.settings.groq_model, "groq": self.settings.enable_groq}
            cache_key = hashlib.sha256(json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            cached = self.cache.get(cache_key)
            reasons = []
            warnings = ["baseline_classifier_uncalibrated", "no_ground_truth_category_priority_evaluation"]
            if analysis.category.value in self.taxonomy["mandatory_human"] and not analysis.sensitive:
                reasons.append("Категория требует ручного рассмотрения по таксономии")
            if analysis.sensitive:
                reasons.append("Обязательная ручная проверка: " + ", ".join(analysis.sensitive))
            if request.kind == "complaint" or analysis.category.value == "report.complaint":
                reasons.append("Обвинения игрока и любое решение о санкциях проверяет администратор")
            if analysis.injection:
                reasons.append("Обнаружена попытка изменить инструкции; использован безопасный шаблон")
            if analysis.language == "und" or analysis.mixed_language:
                reasons.append("Язык неопределён или смешанный; требуется проверка языка ответа")
            if analysis.confidence < 0.55:
                reasons.append("Недостаточная уверенность локального базового классификатора")
            if self.index.synthetic:
                reasons.append("Демонстрационные правила синтетические; автоматическая отправка запрещена")
                warnings.append("synthetic_rules_not_production_policy")
            if references:
                warnings.append("player_rule_refs_unknown_or_ambiguous:" + ",".join(references))
            retrieval_started = time.perf_counter()
            if cached:
                citations, generation, old_needed = cached
                self.cache.move_to_end(cache_key)
                self.metrics["cache_hits"] += 1
            else:
                citations = self.index.retrieve(analysis)
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
            requires_policy = analysis.category.value not in {"report.question", "report.offtopic", "report.payment"}
            if requires_policy and not citations:
                reasons.append("Не найдено достаточно релевантного пункта правил; нельзя делать вывод")
            if analysis.category.value == "report.question":
                reasons.append("Проверенная база инструкций по механикам не предоставлена")
            if self.settings.enable_groq:
                reasons.append("Любой модельный черновик требует проверки администратором")
            needs_human = bool(reasons)
            generation_started = time.perf_counter()
            if not cached or old_needed != needs_human:
                generation = await self.generator.generate(analysis, citations, needs_human, private_source=self.index.private_source)
                self.cache[cache_key] = (citations, generation, needs_human)
                if len(self.cache) > self.settings.cache_capacity:
                    self.cache.popitem(last=False)
            generation_ms = (time.perf_counter() - generation_started) * 1000
            warnings.extend(generation.warnings)
            stamp = request.created_at.timestamp() if request.created_at and request.created_at.tzinfo else (
                request.created_at.replace(tzinfo=timezone.utc).timestamp() if request.created_at else None)
            repeat = self.store.check_repeat(request.reporter_hash, analysis.text, stamp)
            duplicate = repeat.duplicate
            flood = repeat.position > self.settings.flood_limit_per_hour
            if duplicate:
                reasons.append("Повтор того же заявителя по той же проблеме в течение часа")
            if flood:
                reasons.append(f"Флуд: {repeat.position}-е обращение этого игрока за час (лимит {self.settings.flood_limit_per_hour})")
                self.metrics["flood"] += 1
            if analysis.spam:
                reasons.append("Повторяющийся или массовый текст: вероятный спам")
            # Spam/duplicate/flood is a queue signal, never deletion, rejection or automatic penalty.
            needs_human = needs_human or duplicate or flood or analysis.spam
            output_lang = analysis.language if analysis.language != "und" else "en"
            result = TriageResponse(lang=analysis.language, category=analysis.category, priority=analysis.priority,
                is_spam_or_duplicate=duplicate or flood or analysis.spam, extracted=analysis.extracted,
                draft_reply=DraftReply(lang=output_lang, text=generation.draft.text, cited=generation.draft.cited),
                needs_human=needs_human, confidence=round(analysis.confidence, 3), reasons=reasons)
            total_ms = (time.perf_counter() - started) * 1000
            diagnostics = Diagnostics(language_method="unicode+local_lexical_v1", classifier_method="local_e5_prototypes+regex_v1" if self.classifier else "local_regex_taxonomy_v1",
                retrieval_method=self.index.method, generation_mode=generation.mode, normalizations=analysis.normalizations,
                warnings=warnings, timings_ms={"nlp": round(nlp_ms, 3), "retrieval": round(retrieval_ms, 3),
                "generation": round(generation_ms, 3), "total": round(total_ms, 3)},
                tokens={"input": 0 if cached else generation.input_tokens, "output": 0 if cached else generation.output_tokens},
                estimated_cost_usd=0.0 if cached else generation.cost_usd, cache_hit=bool(cached), removed_admin_messages=analysis.removed_admin_messages)
            ticket = Ticket(id=str(uuid.uuid4()), text="\n".join(m.text for m in request.messages if m.role == "player"),
                normalized_text=analysis.text, kind=request.kind, created_at=datetime.now(timezone.utc).isoformat(),
                status="pending", player_id=request.reporter_hash, server=analysis.extracted.server,
                attachments_count=analysis.evidence_count, result=result, citations=citations, draft_reply=generation.draft.text,
                diagnostics=diagnostics)
            self.metrics["tickets_processed"] += 1
            self.metrics["needs_human"] += int(needs_human)
            self.metrics["spam_or_duplicate"] += int(result.is_spam_or_duplicate)
            self.metrics["groq_calls_accepted"] += int(generation.mode.startswith("groq:") and not cached)
            self.metrics["groq_api_attempts"] += 0 if cached else generation.api_attempts
            self.metrics["fallbacks"] += int(any("fallback" in w for w in generation.warnings))
            self.latencies.append(total_ms)
            self.latencies = self.latencies[-10_000:]
            if persist:
                self.store.add(ticket, key, request_hash)
            return ticket
