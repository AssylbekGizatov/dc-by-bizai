"""Repeats by accused player, scoring against human labels, training the model inside predict.

All tickets, labels and rules here are synthetic.
"""
import argparse
import asyncio
import gzip
import json

from app import cli
from app.storage import TicketStore


def test_repeat_complaint_about_the_same_player_within_an_hour():
    store = TicketStore(":memory:")
    try:
        assert store.check_repeat("r1", "оскорбил мою маму в общем чате", 1000.0, "Nick_A").duplicate is False
        # Different words, same reporter, same accused player, 20 minutes later: same case.
        assert store.check_repeat("r1", "опять пишет гадости, скрины прикладываю", 2200.0, "nick_a").duplicate is True
        # Another accused player is another problem.
        assert store.check_repeat("r1", "убил без причины у банка", 2300.0, "Nick_B").duplicate is False
        # More than an hour later is a new ticket.
        assert store.check_repeat("r1", "снова оскорбления в чате", 9000.0, "Nick_A").duplicate is False
        # Another reporter about the same player is not a duplicate of r1.
        assert store.check_repeat("r2", "оскорбил мою маму в общем чате", 2400.0, "Nick_A").duplicate is False
    finally:
        store.close()


def test_repeat_report_with_similar_words():
    store = TicketStore(":memory:")
    try:
        assert store.check_repeat("p", "застрял в текстурах у моста", 0.0).duplicate is False
        assert store.check_repeat("p", "застрял в текстурах у моста помогите", 600.0).duplicate is True
        assert store.check_repeat("p", "как устроиться в полицию", 900.0).duplicate is False
    finally:
        store.close()


def test_old_dedup_table_gets_the_subject_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE dedup (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_key TEXT NOT NULL, "
                       "problem_hash TEXT NOT NULL, token_hashes TEXT NOT NULL, observed_at REAL NOT NULL)")
    connection.commit()
    connection.close()
    store = TicketStore(str(path))
    try:
        assert store.check_repeat("r", "текст жалобы на игрока", 10.0, "Nick").duplicate is False
        assert store.check_repeat("r", "другой текст", 20.0, "Nick").duplicate is True
    finally:
        store.close()


def test_gold_metrics_are_accuracy_and_priority_macro_f1(tmp_path):
    gold = tmp_path / "gold.jsonl"
    manifest = tmp_path / "manifest.jsonl"
    gold.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
        {"annotation_id": "gm-test-0001", "kind": "complaint", "status": "single_annotator",
         "labels": {"category": "complaint.insult", "priority": "p2"}},
        {"annotation_id": "gm-test-0002", "kind": "report", "status": "single_annotator",
         "labels": {"category": "report.offtopic", "priority": "p3"}},
        {"annotation_id": "gm-test-0003", "kind": "report", "status": "has_errors", "labels": None},
    ]), encoding="utf-8")
    manifest.write_text("\n".join(json.dumps(row) for row in [
        {"annotation_id": "gm-test-0001", "split": "test", "ticket_id": "t1"},
        {"annotation_id": "gm-test-0002", "split": "test", "ticket_id": "t2"},
    ]), encoding="utf-8")
    loaded = cli.load_gold(str(gold), str(manifest))
    assert loaded == {"t1": {"category": "complaint.insult", "priority": "p2"},
                      "t2": {"category": "report.offtopic", "priority": "p3"}}
    metrics = cli.gold_metrics([("complaint", "complaint.insult", "complaint.insult", "p2", "p2"),
                                ("report", "report.offtopic", "report.help", "p3", "p2")], 2)
    assert metrics["accuracy"] == 0.5
    assert metrics["macro_f1"] == round((2 / 3 + 0.0) / 2, 4)  # p2: P=0.5 R=1; p3: 0
    assert metrics["gold"]["complaint"]["category_accuracy"] == 1.0
    assert metrics["gold"]["report"]["confusion"] == {"report.offtopic -> report.help": 1}


def _rules(tmp_path):
    data = {"rules": [{"id": 30, "category": "Общие правила игры",
                       "points": [{"ref": r, "text": f"Синтетический пункт {r}."} for r in ("2.1", "3.1", "3.4", "5.2")]},
                      {"id": 31, "category": "Правила жалоб",
                       "points": [{"ref": r, "text": f"Синтетический пункт {r}."} for r in ("1.1.2", "1.2.3", "1.2.7")]}]}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_predict_trains_the_model_when_it_is_missing(tmp_path, monkeypatch):
    train_rows = []
    for i in range(8):
        for text, violation, verdict in [("оскорбил маму", "2.1 ОП", "approved"), ("дм на спавне", "DM", "approved"),
                                         ("не согласен с наказанием", None, "appeal_rejected")]:
            train_rows.append({"ticket_id": f"x{i}{text}", "kind": "complaint", "verdict": verdict, "violation": violation,
                               "messages": [{"role": "player", "text": f"{text} {i}"}]})
    train_path = tmp_path / "train.jsonl.gz"
    with gzip.open(train_path, "wt", encoding="utf-8") as sink:
        sink.write("\n".join(json.dumps(r, ensure_ascii=False) for r in train_rows))
    tickets = tmp_path / "tickets.jsonl"
    tickets.write_text(json.dumps({"ticket_id": "t1", "kind": "complaint", "images_count": 1,
                                   "messages": [{"role": "player", "text": "он не согласен с наказанием"}]},
                                  ensure_ascii=False), encoding="utf-8")
    model_path = tmp_path / "model.npz"
    monkeypatch.setenv("RULES_PATH", str(_rules(tmp_path)))
    monkeypatch.setenv("CLASSIFIER_PATH", str(model_path))
    monkeypatch.setenv("APP_MODE", "test")
    args = argparse.Namespace(command="predict", input=str(tickets), output=str(tmp_path / "pred.jsonl"),
                              allow_synthetic_rules=False, train=str(train_path))
    assert asyncio.run(cli.run(args)) == 0
    assert model_path.exists()
    row = json.loads((tmp_path / "pred.jsonl").read_text(encoding="utf-8"))
    assert row["ticket_id"] == "t1" and row["category"] == "complaint.admin"
    assert row["draft_reply"]["cited"] == ["3.4"]
