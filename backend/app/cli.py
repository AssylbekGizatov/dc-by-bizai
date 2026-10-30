"""Offline JSONL adapter. Never sends organizer data to any external API."""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import tempfile
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from .config import Settings
from .schemas import TriageRequest
from .service import CopilotService


INFERENCE_FIELDS = {"ticket_id", "kind", "created_at", "region", "server_lang", "reporter_hash", "reported_hash",
                    "reported_nick", "rule_refs_raw", "images_count", "server"}
LANGUAGES = {"ru", "kk", "uz", "en", "es", "pt", "und"}


def to_inference(record: dict) -> TriageRequest:
    if not isinstance(record, dict):
        raise ValueError("Each JSONL record must be an object")
    # Explicit allowlist: verdict, punishment, violation, status, gold category/priority,
    # heuristic language label, and all administrator replies are NEVER inference input.
    selected = {key: value for key, value in record.items() if key in INFERENCE_FIELDS}
    if selected.get("server_lang") not in LANGUAGES:
        selected.pop("server_lang", None)
    raw_messages = record.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError("messages must be an array")
    selected["messages"] = [{k: m[k] for k in ("role", "text", "attachments", "ts") if k in m}
                            for m in raw_messages if isinstance(m, dict) and m.get("role") in {"player", "reported_player"}]
    return TriageRequest.model_validate(selected)


RULES_REQUIRED = ("RULES_PATH is not set: predictions would cite the synthetic demo rules, which do not exist in rules.json.\n"
                  "Set RULES_PATH=/path/to/rules.json (and TAXONOMY_PATH=/path/to/taxonomy.json) in .env or the environment.\n"
                  "Не указан RULES_PATH: без настоящих правил цитаты будут выдуманными. Укажите путь к rules.json в .env.")


async def run(args: argparse.Namespace) -> int:
    settings = replace(Settings(), database_path=":memory:", enable_groq=False, groq_api_key=None)
    if not settings.rules_path and not args.allow_synthetic_rules:
        print(RULES_REQUIRED, file=sys.stderr)
        return 2
    svc = CopilotService(settings)
    public_refs = {rule.ref for rule in svc.index.rules if rule.ref != "section"}
    counts, languages, categories, priorities = Counter(), Counter(), Counter(), Counter()
    latencies = []
    begin = time.perf_counter()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if Path(args.input).resolve() == output.resolve():
        raise ValueError("Input and output paths must differ")
    opener = gzip.open if str(args.input).endswith(".gz") else open
    temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, prefix=".copilot-", suffix=".tmp", delete=False)
    temporary_path = Path(temporary.name)
    sink = temporary if args.command == "predict" else None
    completed = False
    try:
        with opener(args.input, "rt", encoding="utf-8-sig") as source:
            for line_no, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    request = to_inference(record)
                    ticket = await svc.process(request, persist=False)
                except (ValueError, ValidationError, TypeError) as exc:
                    # Never print raw records or validation inputs to stderr.
                    print(f"Invalid input at line {line_no}: {type(exc).__name__}. No row was silently skipped.", file=sys.stderr)
                    return 2
                result = ticket.result
                if sink:
                    # ticket_id первым полем: по нему проверяющие сопоставляют предсказание с обращением.
                    row = {"ticket_id": request.ticket_id} if request.ticket_id is not None else {}
                    row.update(result.model_dump(mode="json"))
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts["processed"] += 1
                counts["needs_human"] += int(result.needs_human)
                counts["spam_or_duplicate"] += int(result.is_spam_or_duplicate)
                counts["with_citations"] += int(bool(result.draft_reply.cited))
                counts["citations_exist"] += int(all(ref in public_refs for ref in result.draft_reply.cited))
                counts["synthetic_rule_tickets"] += int(any(c.synthetic for c in ticket.citations))
                counts["normalized_kazakh"] += int("kazakh_cp1251_restored" in ticket.diagnostics.normalizations)
                languages[result.lang] += 1
                categories[result.category.value] += 1
                priorities[result.priority] += 1
                latencies.append(ticket.diagnostics.timings_ms["total"])
        elapsed = time.perf_counter() - begin
        summary = {"schema_version": "1.0", "mode": "offline_local_encoder" if svc.index.encoder else "offline_local_baseline", "external_api_calls": 0,
                   "classifier_mode": svc.health()["classifier_mode"], "retrieval_mode": svc.index.method,
                   "counts": dict(counts), "languages_predicted": dict(languages), "categories_predicted": dict(categories),
                   "priorities_predicted": dict(priorities), "elapsed_seconds": round(elapsed, 4),
                   "latency_ms": {"p50": float(np.percentile(latencies, 50)) if latencies else None,
                                  "p95": float(np.percentile(latencies, 95)) if latencies else None,
                                  "max": max(latencies) if latencies else None},
                   "estimated_external_api_cost_usd": 0, "compute_cost_usd": None,
                   "rules_version": svc.index.version, "synthetic_rules": svc.index.synthetic,
                   "accuracy": None, "macro_f1": None, "draft_quality": None, "citation_relevance_accuracy": None,
                   "limitations": ["Category and priority are local heuristic predictions, not calibrated probabilities.",
                                   "Organizer validation has no category/priority ground truth; no accuracy/F1 is claimed.",
                                   "Citation existence is a schema check, not proof of semantic relevance.",
                                   "Language labels are heuristic; human native-speaker review is required.",
                                   "Latency excludes cold-start dependency/model loading. Compute costs are not measured.",
                                   "Batch cache and deduplication are local to this run; the first processed record in each duplicate group is retained.",
                                   "Validation overlaps training users and texts; it is not an independent holdout."]}
        if args.command == "evaluate":
            temporary.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        else:
            print(json.dumps({"processed": counts["processed"], "external_api_calls": 0}), file=sys.stderr)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary.close()
        os.replace(temporary_path, output)
        completed = True
        return 0
    finally:
        temporary.close()
        if not completed:
            temporary_path.unlink(missing_ok=True)
        await svc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("predict", "evaluate"):
        mode = sub.add_parser(command)
        mode.add_argument("--input", required=True)
        mode.add_argument("--output", required=True)
        mode.add_argument("--allow-synthetic-rules", action="store_true",
                          help="Only for tests and demos: run without RULES_PATH on synthetic rules.")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (ValueError, OSError) as exc:
        print(f"Cannot run: {type(exc).__name__}. Check input/output paths and configuration.", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
