#!/usr/bin/env python3
"""Manual annotation workflow for Label Studio: sample -> label -> gold.

  sample   grouped train/dev/test sample from the training handout + Label Studio tasks
  config   Label Studio configs (one per channel) built from the private taxonomy.json
  gold     Label Studio JSON exports -> validated gold rows in the docs/ANNOTATION.md schema

All outputs contain private data and MUST stay outside Git/CI. Annotators see only player
messages, the accused player's comment and request metadata: no administrator reply,
verdict, punishment, violation, status or heuristic prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.cli import to_inference  # noqa: E402
from app.nlp import analyze, kazakh_legacy_context, normalize  # noqa: E402
from app.schemas import Category  # noqa: E402
from app.taxonomy import load_taxonomy  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_data import fingerprint, records  # noqa: E402

LANGUAGES = ["ru", "kk", "uz", "en", "es", "pt", "und"]       # schemas.Language
PRIORITIES = ["p0", "p1", "p2", "p3"]
# docs/ANNOTATION.md step 4: mandatory human review reasons, separate from category.
MANDATORY_REASONS = {
    "payment": "Платёж / донат",
    "punishment_appeal": "Апелляция своего наказания",
    "account_access": "Взлом / потеря доступа к аккаунту",
    "sanction_decision": "Требуется решение о наказании другого игрока",
}
# Annotator guidance shown next to each category: taxonomy priority criteria, plus team
# decisions where the taxonomy is silent or contradicts the data (admin, help, account;
# "complaints with evidence -> p1" would cover every handout complaint). Not a label.
DEFAULT_PRIORITY = {
    "complaint.insult": "p2", "complaint.cheat": "p1", "complaint.dm": "p2", "complaint.scam": "p1",
    "complaint.rmt_ads": "p1", "complaint.admin": "p2", "complaint.other": "p2", "complaint.invalid": "p3",
    "report.question": "p3", "report.help": "p2", "report.complaint": "p2",
    "report.account": "p0 при взломе/потере доступа, иначе p2", "report.payment": "p0", "report.offtopic": "p3",
}
PRIORITY_EXCEPTIONS = ("Исключения: p0 в любой категории при угрозе в реальной жизни, взломе/потере доступа "
                       "или платеже; p3 для жалобы без доказательств (нет скринов, ссылок, видео).")
CHANNEL_CATEGORIES = {kind: [c.value for c in Category if c.value.startswith(kind + ".")] for kind in ("complaint", "report")}
RULE_UID = re.compile(r"^\d{1,4}:(?:\d{1,2}(?:\.\d{1,2}){0,3}|section)$")
SPLITS = ("test", "dev", "train")
# Identical texts link tickets into one group only when they say something specific:
# "помогите"/"+" from thousands of players are not one case and carry no leakage risk.
MIN_WORDS_TO_LINK_TEXT = 4


# --- sample ------------------------------------------------------------------------

class Groups:
    """Union-find over reporters and specific identical texts (docs/ANNOTATION.md split rule)."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def player_text(row: dict) -> str:
    return "\n".join(m.get("text", "") for m in row.get("messages", []) if m.get("role") == "player")


def lang_bucket(row: dict) -> str:
    """Organizer heuristic language, only as a sampling stratum (never a label)."""
    lang = row.get("lang") or "und"
    return lang if lang in {"ru", "uz", "kk"} else "other"


def quotas(weights: Counter, total: int) -> dict:
    """Largest-remainder rounding of total over weights."""
    norm = sum(weights.values())
    raw = {k: total * v / norm for k, v in weights.items()}
    out = {k: math.floor(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out.values())]:
        out[k] += 1
    return out


def task_data(row: dict, annotation_id: str) -> dict:
    request = to_inference(row)            # drops admin messages and outcome fields
    original = "\n".join(m.text for m in request.messages if m.role == "player")
    restored, changes = normalize(original, kazakh_legacy_context(request.region, request.server_lang))
    accused = "\n".join(m.text for m in request.messages if m.role == "reported_player")
    meta = [f"канал: {request.kind}", f"сервер: {request.region or '—'}",
            f"вложений: {max(request.images_count, sum(m.attachments for m in request.messages))}"]
    if request.rule_refs_raw:
        meta.append(f"поле «пункт правил»: {request.rule_refs_raw}")
    if request.reported_nick:
        meta.append(f"обвиняемый: {request.reported_nick}")
    return {"annotation_id": annotation_id, "kind": request.kind, "player_text": original,
            "restored_text": restored if "kazakh_cp1251_restored" in changes else "",
            "accused_text": accused, "meta": " · ".join(meta)}


def build_sample(train_path, valid_path, taxonomy_path, sizes: dict, seed: int):
    valid = list(records(valid_path))
    valid_users = {r["reporter_hash"] for r in valid if r.get("reporter_hash")}
    valid_texts = {fingerprint(r) for r in valid} - {None}
    # Test/dev mirror the organizer validation recipe (kind x language), which the
    # hidden test follows; train adds coverage of rare heuristic categories.
    valid_mix = Counter((r["kind"], lang_bucket(r)) for r in valid)
    rule_categories = load_taxonomy(taxonomy_path)["rule_categories"]

    rows, groups, excluded = [], Groups(), Counter()
    for row in records(train_path):
        text_fp = fingerprint(row)
        if row.get("reporter_hash") in valid_users or text_fp in valid_texts:
            excluded["valid_user_or_text"] += 1
            continue
        if not player_text(row).strip():
            excluded["empty_player_text"] += 1
            continue
        index = len(rows)
        rows.append(row)
        groups.find(f"t{index}")
        if row.get("reporter_hash"):
            groups.union(f"t{index}", "u" + row["reporter_hash"])
        if text_fp and len(player_text(row).split()) >= MIN_WORDS_TO_LINK_TEXT:
            groups.union(f"t{index}", "x" + text_fp)

    by_split = {s: defaultdict(list) for s in SPLITS}
    group_of, sizes_of = {}, Counter()
    for index in range(len(rows)):
        group_of[index] = groups.find(f"t{index}")
        sizes_of[group_of[index]] += 1
    for index, row in enumerate(rows):
        # Whole groups go to one split, decided by a seeded hash of the group.
        u = int(hashlib.sha256(f"{seed}:{group_of[index]}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        split = "test" if u < 0.2 else "dev" if u < 0.3 else "train"
        by_split[split][(row["kind"], lang_bucket(row))].append(index)

    rng = random.Random(seed)
    for split in SPLITS:
        for bucket in by_split[split].values():
            rng.shuffle(bucket)
    chosen, used_groups = [], set()

    def take(split, stratum, count, predicate=None):
        taken = 0
        for index in by_split[split].get(stratum, []):
            if taken >= count:
                break
            if group_of[index] in used_groups or (predicate and not predicate(index)):
                continue
            used_groups.add(group_of[index])          # one ticket per group: more players, less memorizing
            chosen.append((split, index))
            taken += 1
        return taken

    for split in ("test", "dev"):
        for stratum, count in quotas(valid_mix, sizes[split]).items():
            take(split, stratum, count)
    # Train: half by the validation recipe, half spread over heuristic categories so that
    # rare classes (payment, account, rmt_ads, admin...) get examples to learn from.
    hint = {}
    for split_name, index in [("train", i) for bucket in by_split["train"].values() for i in bucket]:
        hint[index] = analyze(to_inference(rows[index]), rule_categories).category.value
    coverage = sizes["train"] // 2
    per_category = max(1, coverage // len(Category))
    for category in Category:
        kind = category.value.split(".")[0]
        left = per_category
        for stratum in sorted(by_split["train"], key=lambda s: -valid_mix.get(s, 0)):
            if stratum[0] == kind and left:
                left -= take("train", stratum, left, lambda i, c=category.value: hint.get(i) == c)
    remaining = sizes["train"] - sum(1 for s, _ in chosen if s == "train")
    for stratum, count in quotas(valid_mix, remaining).items():
        take("train", stratum, count)

    tasks, manifest = defaultdict(list), []
    for number, (split, index) in enumerate(sorted(chosen, key=lambda x: (SPLITS.index(x[0]), x[1])), 1):
        row = rows[index]
        annotation_id = f"gm-{split}-{number:04d}"
        project = f"{row['kind']}_{'test' if split == 'test' else 'trainval'}"
        tasks[project].append({"data": task_data(row, annotation_id) | {"split": split}})
        manifest.append({"annotation_id": annotation_id, "split": split, "ticket_id": row.get("ticket_id"),
                         "group_id": hashlib.sha256(group_of[index].encode()).hexdigest()[:16],
                         "stratum_hint_not_gold": {"kind": row["kind"], "organizer_lang": row.get("lang"),
                                                   "heuristic_category": hint.get(index)}})
    per_split = {s: {group_of[i] for split, i in chosen if split == s} for s in SPLITS}
    summary = {
        "schema_version": 1, "seed": seed, "sizes_requested": sizes,
        "sizes_built": dict(Counter(m["split"] for m in manifest)),
        "by_split_kind_lang": {s: dict(Counter(f"{m['stratum_hint_not_gold']['kind']}/{m['stratum_hint_not_gold']['organizer_lang']}"
                                                for m in manifest if m["split"] == s)) for s in SPLITS},
        "projects": {name: len(items) for name, items in tasks.items()},
        "train_rows_considered": len(rows), "excluded": dict(excluded),
        "groups": {"count": len(set(group_of.values())), "largest": max(sizes_of.values()),
                   "rule": f"same reporter_hash, or identical player text with >= {MIN_WORDS_TO_LINK_TEXT} words"},
        "leakage_checks": {
            "groups_in_two_splits": sum(len(per_split[a] & per_split[b]) for a, b in (("test", "dev"), ("test", "train"), ("dev", "train"))),
            "valid_users_or_texts_in_sample": sum(rows[i].get("reporter_hash") in valid_users or fingerprint(rows[i]) in valid_texts
                                                  for _, i in chosen),
            "admin_or_outcome_fields_in_tasks": sum(any(word in json.dumps(t["data"], ensure_ascii=False)
                                                        for word in ('"verdict"', '"punishment"', '"violation"'))
                                                    for items in tasks.values() for t in items)},
        "limitations": ["Heuristic category/language only steer sampling; they are not labels.",
                        "Test/dev mirror the organizer validation mix; train is not a prevalence estimate.",
                        "Organizer validation is never sampled; it remains a separate check."],
    }
    return tasks, manifest, summary


# --- Label Studio config -----------------------------------------------------------------

def label_config(kind: str, taxonomy: dict) -> str:
    titles = {c["code"]: c["title"] for c in taxonomy["categories"]}
    examples = {c["code"]: "; ".join(c.get("examples", [])) for c in taxonomy["categories"]}
    priority_rules = {p["code"]: f"{p['title']}: {p['rule']}" for p in taxonomy["priorities"]}

    def choices(name, values, labels=None, hints=None, required=True, multiple=False, extra=""):
        # Label Studio shows `value`; `alias` (the contract code) is what the export stores.
        attr = lambda text: escape(text, {'"': "&quot;"})
        lines = [f'  <Choices name="{name}" toName="player" choice="{"multiple" if multiple else "single"}"'
                 f' required="{"true" if required else "false"}" showInline="false"{extra}>']
        for code in values:
            hint = f' hint="{attr(hints[code])}"' if hints and code in hints else ""
            lines.append(f'    <Choice value="{attr((labels or {}).get(code, code))}" alias="{attr(code)}"{hint}/>')
        lines.append("  </Choices>")
        return "\n".join(lines)

    category_labels = {c: f"{titles[c]} (обычно {DEFAULT_PRIORITY[c]})  [{c}]" for c in CHANNEL_CATEGORIES[kind]}
    category_hints = {c: f"Например: {examples[c]}" for c in CHANNEL_CATEGORIES[kind] if examples[c]}
    return "\n".join([
        "<View>",
        '  <Header value="$annotation_id · $split"/>',
        '  <Text name="meta" value="$meta"/>',
        '  <Header value="Сообщение игрока" size="5"/>',
        '  <Text name="player" value="$player_text"/>',
        '  <Header value="Восстановленные казахские буквы (если были)" size="6"/>',
        '  <Text name="restored_text" value="$restored_text"/>',
        '  <Header value="Комментарий обвиняемого (если есть)" size="6"/>',
        '  <Text name="accused" value="$accused_text"/>',
        # Two clicks per ticket: the scored fields (category accuracy, priority macro-F1).
        # Language, mandatory-human reasons, spam and rule UIDs are not labelled in this round.
        '  <Header value="1. Категория (по смыслу сообщения игрока)" size="5"/>',
        choices("category", CHANNEL_CATEGORIES[kind], category_labels, category_hints),
        '  <Header value="2. Приоритет" size="5"/>',
        choices("priority", PRIORITIES, {p: f"{p} — {priority_rules[p]}" for p in PRIORITIES}),
        f'  <Header value="{escape(PRIORITY_EXCEPTIONS)}" size="6"/>',
        "</View>",
    ]) + "\n"


# --- export -> gold --------------------------------------------------------------------------

_DISPLAYED = {"Да": "yes", "Нет": "no", "В сообщении смешаны языки": "mixed"} | {v: k for k, v in MANDATORY_REASONS.items()}


def choice_code(value: str) -> str:
    """Exports may carry the alias (code) or the displayed label; map both to the code."""
    if value in _DISPLAYED:
        return _DISPLAYED[value]
    tagged = re.search(r"\[((?:complaint|report)\.[a-z_]+)\]\s*$", value)
    if tagged:
        return tagged.group(1)
    head = value.split(" ", 1)[0]
    return head if head in PRIORITIES else value


def parse_annotation(result: list) -> dict:
    values = {}
    for item in result:
        name, value = item.get("from_name"), item.get("value", {})
        if "choices" in value:
            values[name] = [choice_code(v) for v in value["choices"]]
        elif "text" in value:
            values[name] = " ".join(value["text"]).strip()
    return values


def validate_labels(kind: str, values: dict, rule_uids_known: set[str] | None) -> tuple[dict, list[str]]:
    errors = []
    one = lambda name: (values.get(name) or [None])[0]
    labels = {"lang": one("lang"), "category": one("category"), "category_alt": one("category_alt"),
              "priority": one("priority"), "mandatory_human": {"yes": True, "no": False}.get(one("mandatory_human")),
              "mandatory_reasons": sorted(values.get("mandatory_reasons") or []) if one("mandatory_human") == "yes" else [],
              "is_spam": {"yes": True, "no": False}.get(one("spam")),
              "mixed_language": "mixed" in (values.get("mixed_language") or []),
              "relevant_rule_uids": [u.strip() for u in re.split(r"[,\s;]+", values.get("rule_uids") or "") if u.strip()],
              "duplicate_group": None}
    if labels["category"] not in CHANNEL_CATEGORIES[kind]:
        errors.append(f"category {labels['category']!r} is not a {kind} category")
    if labels["category_alt"] not in (None, *CHANNEL_CATEGORIES[kind]) or labels["category_alt"] == labels["category"]:
        errors.append("category_alt must differ from category and match the channel")
    if labels["priority"] not in PRIORITIES:
        errors.append("priority missing")
    # Optional fields: validated only when a (fuller) config collected them.
    if labels["lang"] is not None and labels["lang"] not in LANGUAGES:
        errors.append(f"unknown lang {labels['lang']!r}")
    if not set(values.get("mandatory_reasons") or []) <= set(MANDATORY_REASONS):
        errors.append("unknown mandatory reason")
    if labels["mandatory_human"] is False and values.get("mandatory_reasons"):
        errors.append("mandatory reasons given although mandatory_human is 'no'")
    if labels["mandatory_human"] is True and not labels["mandatory_reasons"]:
        errors.append("mandatory_human is 'yes' but no reason selected")
    for uid in labels["relevant_rule_uids"]:
        if not RULE_UID.match(uid) or (rule_uids_known is not None and uid not in rule_uids_known):
            errors.append(f"unknown rule uid {uid!r} (expected section:ref from rules.json)")
    return labels, errors


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / len(pairs) ** 2
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def build_gold(export_paths: list[str], rules_path: str | None):
    known = None
    if rules_path:
        data = json.loads(Path(rules_path).read_text(encoding="utf-8"))
        known = {f"{s['id']}:{p['ref']}" for s in data["rules"] for p in s.get("points", [])}
        known |= {f"{s['id']}:section" for s in data["rules"] if not s.get("points")}
    gold, problems, pairs = [], [], defaultdict(list)
    for path in export_paths:
        for task in json.loads(Path(path).read_text(encoding="utf-8")):
            data = task["data"]
            done = [a for a in task.get("annotations", []) if not a.get("was_cancelled") and a.get("result")]
            parsed, notes, invalid = [], [], 0
            for annotation in done:
                values = parse_annotation(annotation["result"])
                labels, errors = validate_labels(data["kind"], values, known)
                notes.append(values.get("notes", ""))
                if errors:      # an invalid annotation never becomes gold; fix it in Label Studio
                    invalid += 1
                else:
                    parsed.append((annotation, labels))
                problems += [{"annotation_id": data["annotation_id"], "annotator": annotation.get("completed_by"), "error": e} for e in errors]
            if len(parsed) >= 2:
                for field in ("category", "priority", "lang", "mandatory_human"):
                    pairs[field].append((str(parsed[0][1][field]), str(parsed[1][1][field])))
            adjudicated = [p for p in parsed if p[0].get("ground_truth")]
            agree = len(parsed) >= 2 and all(p[1] == parsed[0][1] for p in parsed)
            final = adjudicated[0] if adjudicated else parsed[0] if len(parsed) == 1 or agree else None
            status = ("adjudicated" if adjudicated else "has_errors" if invalid else "agreed" if agree else
                      "single_annotator" if len(parsed) == 1 else "needs_adjudication" if parsed else "unlabeled")
            if status == "has_errors":
                final = None
            gold.append({"annotation_id": data["annotation_id"], "split": data.get("split"), "kind": data["kind"],
                         "labels": final[1] if final else None, "status": status,
                         "annotators": [p[0].get("completed_by") for p in parsed],
                         "adjudicator": adjudicated[0][0].get("completed_by") if adjudicated else None,
                         "label_source": "human", "notes": [n for n in notes if n]})
    report = {"rows": len(gold), "status": dict(Counter(g["status"] for g in gold)),
              "by_split": dict(Counter(g["split"] for g in gold if g["labels"])), "problems": problems,
              "agreement_before_adjudication": {
                  field: {"n": len(p), "raw": round(sum(a == b for a, b in p) / len(p), 3) if p else None,
                          "cohen_kappa": cohen_kappa(p)} for field, p in pairs.items()}}
    return gold, report


# --- split between annotators ------------------------------------------------------------------

TASK_FILES = ("tasks_complaint_test.json", "tasks_report_test.json",
              "tasks_complaint_trainval.json", "tasks_report_trainval.json")


def split_tasks(src: Path, people: int) -> list[dict[str, list]]:
    """Disjoint, equal shares; every file and split is dealt round-robin, so each person
    gets the same mix of channels and test/dev/train."""
    shares = [{name: [] for name in TASK_FILES} for _ in range(people)]
    load = [0] * people
    for name in TASK_FILES:
        tasks = json.loads((src / name).read_text(encoding="utf-8"))
        for task in sorted(tasks, key=lambda t: t["data"]["annotation_id"]):
            who = load.index(min(load))
            shares[who][name].append(task)
            load[who] += 1
    return shares


# --- CLI -------------------------------------------------------------------------------------

def write_private(path: Path, text: str) -> None:
    from app.private_files import restrict_private_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    restrict_private_file(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--train", required=True); s.add_argument("--valid", required=True)
    s.add_argument("--taxonomy", required=True); s.add_argument("--out-dir", required=True)
    s.add_argument("--test", type=int, default=200); s.add_argument("--dev", type=int, default=100)
    s.add_argument("--train-size", type=int, default=500); s.add_argument("--seed", type=int, default=20261031)
    c = sub.add_parser("config")
    c.add_argument("--taxonomy", required=True); c.add_argument("--out-dir", required=True)
    d = sub.add_parser("split")
    d.add_argument("--in-dir", required=True); d.add_argument("--out-dir", required=True)
    d.add_argument("--people", type=int, default=2)
    g = sub.add_parser("gold")
    g.add_argument("--export", nargs="+", required=True); g.add_argument("--rules")
    g.add_argument("--output", required=True); g.add_argument("--report", required=True)
    args = parser.parse_args()

    if args.command == "sample":
        sizes = {"test": args.test, "dev": args.dev, "train": args.train_size}
        if not all(0 <= v <= 5000 for v in sizes.values()):
            parser.error("split sizes must be 0..5000")
        tasks, manifest, summary = build_sample(args.train, args.valid, args.taxonomy, sizes, args.seed)
        out = Path(args.out_dir)
        for project, items in tasks.items():
            write_private(out / f"tasks_{project}.json", json.dumps(items, ensure_ascii=False, indent=1))
        write_private(out / "manifest.jsonl", "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in manifest))
        write_private(out / "sample_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps({k: summary[k] for k in ("sizes_built", "projects", "leakage_checks")}, ensure_ascii=False))
    elif args.command == "config":
        taxonomy = json.loads(Path(args.taxonomy).read_text(encoding="utf-8"))
        load_taxonomy(args.taxonomy)        # same validation as the service: codes must match the contract
        for kind in CHANNEL_CATEGORIES:
            write_private(Path(args.out_dir) / f"label_config_{kind}.xml", label_config(kind, taxonomy))
        print(json.dumps({"configs": [f"label_config_{k}.xml" for k in CHANNEL_CATEGORIES]}))
    elif args.command == "split":
        if not 2 <= args.people <= 10:
            parser.error("people must be 2..10")
        src, out = Path(args.in_dir), Path(args.out_dir)
        for number, share in enumerate(split_tasks(src, args.people), 1):
            folder = out / f"person_{number}"
            for name, tasks in share.items():
                write_private(folder / name, json.dumps(tasks, ensure_ascii=False, indent=1))
            for kind in CHANNEL_CATEGORIES:
                config = src / f"label_config_{kind}.xml"
                write_private(folder / config.name, config.read_text(encoding="utf-8"))
            print(json.dumps({f"person_{number}": {n: len(t) for n, t in share.items()}}))
    else:
        gold, report = build_gold(args.export, args.rules)
        write_private(Path(args.output), "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in gold))
        write_private(Path(args.report), json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: report[k] for k in ("rows", "status")} | {"problems": len(report["problems"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
