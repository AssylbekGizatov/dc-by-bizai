"""Synthetic checks of the annotation workflow; no organizer data."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import labeling  # noqa: E402

TAXONOMY = {"version": "synthetic", "categories": [
    {"code": c.value, "kind": c.value.split(".")[0], "title": f"Title {c.value}", "rules": [], "examples": ["пример"]}
    for c in labeling.Category], "priorities": [{"code": p, "title": p, "rule": "синтетика"} for p in labeling.PRIORITIES]}


def result(**choices):
    return [{"from_name": k, "type": "choices", "value": {"choices": v}} for k, v in choices.items()]


def test_config_is_channel_specific_and_keeps_codes_as_aliases():
    complaint = labeling.label_config("complaint", TAXONOMY)
    report = labeling.label_config("report", TAXONOMY)
    assert 'alias="complaint.insult"' in complaint and "report.payment" not in complaint
    assert 'alias="report.payment"' in report and "complaint.insult" not in report
    assert complaint.count('<Choices name="category"') == 1 and 'required="true"' in complaint


def test_displayed_labels_and_aliases_map_to_codes():
    assert labeling.choice_code("Title complaint.dm  [complaint.dm]") == "complaint.dm"
    assert labeling.choice_code("complaint.dm") == "complaint.dm"
    assert labeling.choice_code("Title (обычно p0 при взломе/потере доступа, иначе p2)  [report.account]") == "report.account"
    assert set(labeling.DEFAULT_PRIORITY) == {c.value for c in labeling.Category}
    assert labeling.choice_code("p0 — Критично: взлом") == "p0"
    assert labeling.choice_code("Да") == "yes"
    assert labeling.choice_code(labeling.MANDATORY_REASONS["payment"]) == "payment"


def test_validation_rejects_wrong_channel_and_inconsistent_reasons():
    values = labeling.parse_annotation(result(category=["report.help"], priority=["p2"], lang=["ru"],
                                              mandatory_human=["Нет"], spam=["Нет"]))
    _, errors = labeling.validate_labels("complaint", values, None)
    assert any("not a complaint category" in e for e in errors)
    values = labeling.parse_annotation(result(category=["complaint.insult"], priority=["p2"], lang=["ru"],
                                              mandatory_human=["Да"], spam=["Нет"]))
    assert any("no reason" in e for e in labeling.validate_labels("complaint", values, None)[1])


def test_valid_annotation_has_no_errors():
    values = labeling.parse_annotation(result(category=["complaint.dm"], priority=["p2"], lang=["uz"],
                                              mandatory_human=["Да"], mandatory_reasons=["punishment_appeal"], spam=["Нет"]))
    labels, errors = labeling.validate_labels("complaint", values, {"30:2.1"})
    assert errors == [] and labels["mandatory_reasons"] == ["punishment_appeal"]


def test_gold_marks_disagreement_and_never_promotes_invalid_rows(tmp_path):
    good = result(category=["complaint.dm"], priority=["p2"], lang=["ru"], mandatory_human=["Нет"], spam=["Нет"])
    other = result(category=["complaint.insult"], priority=["p2"], lang=["ru"], mandatory_human=["Нет"], spam=["Нет"])
    bad = result(category=["report.help"], priority=["p2"], lang=["ru"], mandatory_human=["Нет"], spam=["Нет"])
    export = [
        {"data": {"annotation_id": "a", "kind": "complaint", "split": "test"}, "annotations": [{"result": good}, {"result": good}]},
        {"data": {"annotation_id": "b", "kind": "complaint", "split": "test"}, "annotations": [{"result": good}, {"result": other}]},
        {"data": {"annotation_id": "c", "kind": "complaint", "split": "test"}, "annotations": [{"result": bad}]},
        {"data": {"annotation_id": "d", "kind": "complaint", "split": "test"},
         "annotations": [{"result": good}, {"result": other, "ground_truth": True}]},
    ]
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    gold, report = labeling.build_gold([str(path)], None)
    status = {g["annotation_id"]: (g["status"], g["labels"] and g["labels"]["category"]) for g in gold}
    assert status == {"a": ("agreed", "complaint.dm"), "b": ("needs_adjudication", None),
                      "c": ("has_errors", None), "d": ("adjudicated", "complaint.insult")}
    assert report["agreement_before_adjudication"]["category"]["n"] == 3


def test_groups_join_reporter_and_text_links():
    groups = labeling.Groups()
    groups.union("t1", "uA"); groups.union("t2", "uA"); groups.union("t2", "xT"); groups.union("t3", "xT")
    assert groups.find("t1") == groups.find("t3") != groups.find("t4")


def test_quotas_sum_exactly():
    assert sum(labeling.quotas(labeling.Counter({"a": 817, "b": 183}), 200).values()) == 200
