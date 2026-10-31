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
from .private_files import restrict_private_file


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


def read_manifest(path: str) -> list[dict]:
    """scripts/labeling.py writes manifest.jsonl (one row per task); a JSON list is accepted too."""
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if text.startswith("["):
        return [row for row in json.loads(text) if isinstance(row, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_gold(gold_path: str, manifest_path: str | None) -> dict[str, dict]:
    """ticket_id -> {"category", "priority"} from scripts/labeling.py gold rows (+ its manifest)."""
    by_annotation = {}
    if manifest_path:
        by_annotation = {m["annotation_id"]: m.get("ticket_id") for m in read_manifest(manifest_path)}
    gold: dict[str, dict] = {}
    with open(gold_path, encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            labels = row.get("labels") or {}
            ticket_id = row.get("ticket_id") or by_annotation.get(row.get("annotation_id"))
            if ticket_id and labels.get("category") and labels.get("priority"):
                gold[ticket_id] = {"category": labels["category"], "priority": labels["priority"]}
    if not gold:
        raise ValueError("No usable gold rows: pass --manifest when gold rows have no ticket_id")
    return gold


def _macro_f1(pairs: list[tuple[str, str]], labels: list[str]) -> float | None:
    scores = []
    for label in labels:
        tp = sum(g == label and p == label for g, p in pairs)
        fp = sum(g != label and p == label for g, p in pairs)
        fn = sum(g == label and p != label for g, p in pairs)
        if tp + fp + fn == 0:
            continue  # a class absent from both gold and predictions does not count
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return round(sum(scores) / len(scores), 4) if scores else None


def gold_metrics(scored: list[tuple[str, str, str, str, str]], gold_rows: int) -> dict:
    """Category accuracy and priority macro-F1, the case's classification metrics, on human labels."""
    def block(rows):
        if not rows:
            return None
        return {"n": len(rows), "category_accuracy": round(sum(g == p for _, g, p, _, _ in rows) / len(rows), 4),
                "priority_macro_f1": _macro_f1([(g, p) for *_, g, p in rows], ["p0", "p1", "p2", "p3"]),
                "confusion": {f"{g} -> {p}": n for (g, p), n in Counter((g, p) for _, g, p, _, _ in rows).most_common() if g != p}}
    overall = block(scored)
    return {"accuracy": overall["category_accuracy"] if overall else None,
            "macro_f1": overall["priority_macro_f1"] if overall else None,
            "gold": {"rows_in_gold": gold_rows, "rows_found_in_input": len(scored), "all": overall,
                     "complaint": block([r for r in scored if r[0] == "complaint"]),
                     "report": block([r for r in scored if r[0] == "report"])}}


RULES_REQUIRED = ("RULES_PATH is not set: predictions would cite the synthetic demo rules, which do not exist in rules.json.\n"
                  "Set RULES_PATH=/path/to/rules.json (and TAXONOMY_PATH=/path/to/taxonomy.json) in .env or the environment.\n"
                  "Не указан RULES_PATH: без настоящих правил цитаты будут выдуманными. Укажите путь к rules.json в .env.")


async def run(args: argparse.Namespace) -> int:
    settings = replace(Settings(), database_path=":memory:", enable_groq=False, groq_api_key=None)
    if not settings.rules_path and not args.allow_synthetic_rules:
        print(RULES_REQUIRED, file=sys.stderr)
        return 2
    gold = load_gold(args.gold, args.manifest) if getattr(args, "gold", None) else None
    model = None
    train_path = getattr(args, "train", None) or os.getenv("TRAIN_PATH") or None
    if train_path and not (settings.classifier_path and Path(settings.classifier_path).exists()):
        # No model file yet: train it now (about a minute on CPU) and keep it for later runs.
        from .trained import train
        model, trained = train(train_path, exclude_ids=set(gold) if gold else None)
        if settings.classifier_path:
            model.save(settings.classifier_path)
            restrict_private_file(Path(settings.classifier_path))
            model = None
        print(json.dumps({"complaint_model": trained}, ensure_ascii=False), file=sys.stderr)
    svc = CopilotService(settings)
    if model is not None:
        svc.complaint_model = model
    public_refs = {rule.ref for rule in svc.index.rules if rule.ref != "section"}
    scored: list[tuple[str, str, str, str, str]] = []  # kind, gold category, predicted, gold priority, predicted
    counts, languages, categories, priorities = Counter(), Counter(), Counter(), Counter()
    review_reasons, generation_modes = Counter(), Counter()
    latencies = []
    begin = time.perf_counter()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if Path(args.input).resolve() == output.resolve():
        raise ValueError("Input and output paths must differ")
    opener = gzip.open if str(args.input).endswith(".gz") else open
    temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, prefix=".copilot-", suffix=".tmp", delete=False)
    temporary_path = Path(temporary.name)
    restrict_private_file(temporary_path)
    sink = temporary if args.command == "predict" else None
    completed = False
    try:
        with opener(args.input, "rt", encoding="utf-8-sig") as source:
            for line_no, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if gold is not None and record.get("ticket_id") not in gold:
                        continue  # with --gold only the human-labelled tickets are scored
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
                review_reasons.update(result.reasons)
                generation_modes[ticket.diagnostics.generation_mode] += 1
                latencies.append(ticket.diagnostics.timings_ms["total"])
                if gold is not None:
                    labels = gold[record["ticket_id"]]
                    scored.append((request.kind, labels["category"], result.category.value, labels["priority"], result.priority))
        elapsed = time.perf_counter() - begin
        summary = {"schema_version": "1.0", "mode": "offline_local_encoder" if svc.index.encoder else "offline_local_baseline", "external_api_calls": 0,
                   "classifier_mode": svc.health()["classifier_mode"], "retrieval_mode": svc.index.method,
                   "counts": dict(counts), "languages_predicted": dict(languages), "categories_predicted": dict(categories),
                   "priorities_predicted": dict(priorities), "elapsed_seconds": round(elapsed, 4),
                   "review_reasons_nonexclusive": dict(review_reasons), "generation_modes": dict(generation_modes),
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
        if gold is not None:
            summary.update(gold_metrics(scored, len(gold)))
            summary["limitations"] = [x for x in summary["limitations"] if not x.startswith("Organizer validation has no")]
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
        mode.add_argument("--train", help="tickets_train.jsonl(.gz): train the complaint model first when "
                                          "CLASSIFIER_PATH is unset or missing (also TRAIN_PATH)")
        if command == "evaluate":
            mode.add_argument("--gold", help="gold.jsonl from scripts/labeling.py: score only those tickets")
            mode.add_argument("--manifest", help="labeling manifest.jsonl mapping annotation_id -> ticket_id")
    trainer = sub.add_parser("train", help="Train the complaint model on the private train split.")
    trainer.add_argument("--input", required=True, help="tickets_train.jsonl(.gz)")
    trainer.add_argument("--output", required=True, help="model .npz, outside Git")
    trainer.add_argument("--exclude-manifest", help="labeling manifest.jsonl: leave the human-labelled tickets out")
    args = parser.parse_args()
    if args.command == "train":
        from .trained import train
        excluded = None
        if args.exclude_manifest:
            excluded = {m["ticket_id"] for m in read_manifest(args.exclude_manifest) if m.get("ticket_id")}
        model, summary = train(args.input, exclude_ids=excluded)
        model.save(args.output)
        restrict_private_file(Path(args.output))
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
        return
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (ValueError, OSError) as exc:
        print(f"Cannot run: {type(exc).__name__}. Check input/output paths and configuration.", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
