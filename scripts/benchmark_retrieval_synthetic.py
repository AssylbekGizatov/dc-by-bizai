#!/usr/bin/env python3
"""Reproducible retrieval regression, with invented rules and hand-written queries.

This is NOT a labeled evaluation of the organizer's corpus. No train/valid text,
historical admin answers or downloaded datasets are used. Optional E5 loads only
from an explicitly supplied local directory; it never downloads during inference.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.nlp import analyze
from app.retrieval import RuleIndex
from app.schemas import TriageRequest


CORPUS = {"synthetic": True, "source": "Invented benchmark policies, not Grand Mobile rules", "rules": [
    {"id": "general", "category": "Синтетический общий раздел", "points": [
        {"ref": "1.1", "text": "Учебная норма: оскорбление и нецензурная лексика в обычном чате передаются для проверки модератору."},
        {"ref": "1.2", "text": "Учебная норма: использование читов и стороннего программного обеспечения проверяет сотрудник поддержки."},
        {"ref": "1.3", "text": "Учебная норма: убийство и урон без причины, нападение без ролевого повода требуют разбора контекста."},
        {"ref": "1.4", "text": "Учебная норма: обман и мошенничество при обмене имуществом передаются для ручного рассмотрения."},
        {"ref": "1.5", "text": "Учебная норма: техническая поддержка уточняет место и время, если игрок застрял в текстурах."},
    ]},
    {"id": "41", "category": "Синтетическая война за бизнес", "points": [
        {"ref": "1.1", "text": "Учебная норма только для войны за бизнес: оскорбление участников мероприятия требует отдельного рассмотрения."},
    ]},
]}

# Expected IDs were written for this invented fixture. They are not expert gold
# labels and must never be mixed with real validation/hidden-test metrics.
CASES = [
    ("ru-insult", "ru", "report", "Игрок бранится и оскорбляет меня в обычном чате", ["general:1.1"]),
    ("kk-insult", "kk", "report", "Ойыншы мені чатта балағаттады", ["general:1.1"]),
    ("uz-insult", "uz", "report", "O'yinchi meni chatda haqorat qildi", ["general:1.1"]),
    ("ru-cheat", "ru", "complaint", "Другой участник использует speedhack и читы", ["general:1.2"]),
    ("kk-cheat", "kk", "complaint", "Ойыншы чит қолданады, тексеріңіз", ["general:1.2"]),
    ("uz-cheat", "uz", "complaint", "O'yinchi cheat ishlatyapti, yordam kerak", ["general:1.2"]),
    ("ru-dm", "ru", "report", "Меня убили без причины во время прогулки", ["general:1.3"]),
    ("kk-dm", "kk", "report", "Мені себепсіз өлтірді, көмек керек", ["general:1.3"]),
    ("uz-dm", "uz", "report", "Meni sababsiz o'ldirdi, yordam kerak", ["general:1.3"]),
    ("ru-scam", "ru", "complaint", "Другой игрок обманул при обмене имуществом", ["general:1.4"]),
    ("kk-scam", "kk", "complaint", "Ойыншы мені алдап кетті", ["general:1.4"]),
    ("uz-scam", "uz", "complaint", "O'yinchi meni aldadi, iltimos yordam bering", ["general:1.4"]),
    ("ru-help", "ru", "report", "Я застрял в текстурах около моста", ["general:1.5"]),
    ("kk-help", "kk", "report", "Ойында тұрып қалдым, көмек керек", ["general:1.5"]),
    ("uz-help", "uz", "report", "O'yinda qotib qoldim, yordam kerak", ["general:1.5"]),
    ("ru-abstain", "ru", "report", "Где устроиться на работу? Игрок написал пункт 99.99", []),
    ("kk-abstain", "kk", "report", "Сәлем! Жұмысқа қалай орналасамын?", []),
    ("uz-abstain", "uz", "report", "Salom! Qanday ish topish mumkin?", []),
]


def run(encoder_path: str | None = None, rounds: int = 3) -> dict:
    with tempfile.TemporaryDirectory(prefix="copilot-synthetic-retrieval-") as folder:
        path = Path(folder) / "rules.json"
        path.write_text(json.dumps(CORPUS, ensure_ascii=False), encoding="utf-8")
        started = time.perf_counter()
        index = RuleIndex(str(path), encoder_path)
        startup_ms = (time.perf_counter() - started) * 1000
        methods = ["bm25", "hybrid"] + (["hybrid_e5"] if encoder_path else [])
        results = {}
        for method in methods:
            observations, durations = [], []
            for case_id, language, kind, text, expected in CASES:
                current = analyze(TriageRequest(kind=kind, messages=[{"role": "player", "text": text}]))
                for repetition in range(rounds):
                    started = time.perf_counter()
                    found = index.retrieve(current, strategy=method)
                    durations.append((time.perf_counter() - started) * 1000)
                actual = [item.id for item in found]
                observations.append({"case_id": case_id, "language": language, "detected_language": current.language,
                    "expected": expected, "retrieved": actual, "hit_at_3": bool(set(actual) & set(expected)) if expected else None,
                    "abstained_correctly": not actual if not expected else None,
                    "irrelevant_count": len(set(actual) - set(expected))})
            positives = [row for row in observations if row["expected"]]
            negatives = [row for row in observations if not row["expected"]]
            results[method] = {"positive_cases": len(positives), "hit_at_3": sum(row["hit_at_3"] for row in positives) / len(positives),
                "negative_cases": len(negatives), "correct_abstentions": sum(row["abstained_correctly"] for row in negatives),
                "irrelevant_results": sum(row["irrelevant_count"] for row in observations),
                "retrieval_only_ms": {"p50": statistics.median(durations), "p95_nearest_rank": sorted(durations)[math.ceil(.95 * len(durations)) - 1]},
                "by_language": {lang: {"positive_cases": sum(row["language"] == lang for row in positives),
                    "hits": sum(row["hit_at_3"] for row in positives if row["language"] == lang)} for lang in ("ru", "kk", "uz")},
                "observations": observations}
        return {"synthetic_only": True, "cases": len(CASES), "rounds": rounds, "startup_ms": startup_ms,
            "methods": results, "dense_status": "measured_local_e5" if encoder_path else "not_measured_no_encoder_path",
            "reranker": "not_added_without_measured_need", "category_accuracy": None, "priority_macro_f1": None,
            "limitation": "Small authored regression fixture, not independent expert labels. Retrieval timing excludes generation and HTTP; no production SLO claim."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder-path")
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.encoder_path, args.rounds)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
