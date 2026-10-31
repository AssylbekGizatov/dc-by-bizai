"""Report model trained on manually labelled rows; synthetic texts only."""
import json

import pytest

from app.nlp import analyze
from app.schemas import Category, TriageRequest
from app.trained import ComplaintModel, train_reports

HELP = ["застрял в текстурах помогите", "переверните машину пж", "достаньте из воды машину", "снимите наручники пожалуйста",
        "не могу выйти из дома застрял", "телепортируйте я застрял под картой"]
OFFTOPIC = ["привет", "ау", "как дела админы", "+", "хелп", "сос"]
QUESTION = ["как устроиться в полицию", "где купить лицензию на оружие", "как получить права", "где работа на заводе",
            "сколько стоит дом", "как вступить в семью"]
PAYMENT = ["донат не пришел", "оплатил гк не пришло", "списали деньги", "задонатил ничего нет", "оплата не прошла донат",
           "купил донат не начислили"]


def labelled(tmp_path, split="train"):
    rows = [{"kind": "report", "text": t, "field": "", "accused": "", "category": c, "split": split}
            for texts, c in ((HELP, "report.help"), (OFFTOPIC, "report.offtopic"), (QUESTION, "report.question"),
                             (PAYMENT, "report.payment")) for t in texts]
    rows += [{"kind": "complaint", "text": "оск родни", "field": "", "accused": "", "category": "complaint.insult", "split": "train"},
             {"kind": "report", "text": "застрял тестовый", "field": "", "accused": "", "category": "report.help", "split": "test"}]
    path = tmp_path / "labelled.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def report(text):
    return TriageRequest(kind="report", messages=[{"role": "player", "text": text}])


def test_trains_on_train_reports_only_and_round_trips(tmp_path):
    model, summary = train_reports(str(labelled(tmp_path)))
    assert summary["trained_on"] == 24 and set(model.classes) == {"report.help", "report.offtopic", "report.question", "report.payment"}
    model.save(str(tmp_path / "m.npz"))
    assert ComplaintModel.load(str(tmp_path / "m.npz")).predict("застрял в текстурах")[0] == "report.help"


def test_needs_labelled_reports(tmp_path):
    with pytest.raises(ValueError):
        train_reports(str(labelled(tmp_path, split="dev")))


def test_model_refines_report_category(tmp_path):
    model, _ = train_reports(str(labelled(tmp_path)))
    # "достаньте машину" has no rule keyword: rules say off-topic, the model says help.
    assert analyze(report("достаньте из воды машину")).category == Category.offtopic
    assert analyze(report("достаньте из воды машину"), report_model=model).category == Category.help


def test_model_never_creates_or_removes_payment_route(tmp_path):
    model, _ = train_reports(str(labelled(tmp_path)))
    assert analyze(report("купил донат не начислили"), report_model=model).category == Category.payment    # rules keep it
    current = analyze(report("ничего не пришло, ничего нет"), report_model=model)
    assert current.category != Category.payment and current.priority != "p0"


def test_complaints_ignore_the_report_model(tmp_path):
    model, _ = train_reports(str(labelled(tmp_path)))
    complaint = TriageRequest(kind="complaint", messages=[{"role": "player", "text": "застрял в текстурах помогите"}], images_count=1)
    assert analyze(complaint, report_model=model).category.value.startswith("complaint.")
