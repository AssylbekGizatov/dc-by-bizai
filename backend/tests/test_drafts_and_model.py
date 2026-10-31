"""Short category drafts, one relevant citation, the trained complaint model, cp1251 by position.

Everything here is synthetic: rule texts are placeholders with the real section ids and point
numbers, tickets are invented sentences.
"""
import asyncio
import gzip
import json
import re
from dataclasses import replace

import numpy as np
import pytest

from app.config import Settings
from app.generation import TEMPLATES, GeneratedDraft, approved_clauses, template_draft, validate_draft
from app.nlp import analyze, normalize
from app.retrieval import RuleIndex, policy_citations
from app.schemas import TriageRequest
from app.service import CopilotService
from app.trained import ComplaintModel, train, weak_label

POINTS = {
    30: ["1.4", "2.1", "2.3", "2.4", "2.6", "3.1", "3.4", "4.1", "4.2", "4.4", "5.2", "5.4"],
    31: ["1.1.2", "1.2.3", "1.2.7"],
    32: ["1.1", "1.2"],
}
TITLES = {30: "Общие правила игры", 31: "Правила жалоб", 32: "Правила нахождения в Зелёной Зоне"}


@pytest.fixture()
def rules_path(tmp_path):
    data = {"rules": [{"id": sid, "category": TITLES[sid],
                       "points": [{"ref": ref, "text": f"Синтетический пункт {ref} раздела {sid}."} for ref in refs]}
                      for sid, refs in POINTS.items()]}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def ticket(text, kind="complaint", **extra):
    return TriageRequest(kind=kind, messages=[{"role": "player", "text": text}], **extra)


@pytest.mark.parametrize("text,kind,expected", [
    ("Nick_Name оскорбил мою маму в чате", "complaint", ["30:2.1"]),
    ("убил меня в зз у больницы", "complaint", ["32:1.1"]),
    ("убил меня без причины на дороге", "complaint", []),
    ("использует читы, аимбот", "complaint", ["30:5.2"]),
    ("обманул при обмене машины", "complaint", ["30:4.1"]),
    ("админ выдал бан без причины, не согласен", "complaint", ["30:3.4"]),
    ("ау", "report", ["30:3.1"]),
    ("вокзал тп", "report", ["30:3.1"]),
    ("застрял в текстурах у моста, не могу выйти", "report", []),
    ("как устроиться в полицию", "report", []),
])
def test_one_citation_from_the_category_rules(rules_path, text, kind, expected):
    index = RuleIndex(rules_path)
    cited = [c.id for c in policy_citations(index, analyze(ticket(text, kind)))]
    assert cited == expected


def test_template_languages_have_the_same_reviewed_clauses():
    keys = set(TEMPLATES["ru"])
    for lang, clauses in TEMPLATES.items():
        assert set(clauses) == keys, lang
        for key, value in clauses.items():
            assert ("{refs}" in value) == ("{refs}" in TEMPLATES["ru"][key]), (lang, key)


PROMISES = re.compile(r"будет\s+(?:забанен|наказан|разбанен)|разбаним|вернём|вернем|получит\s+(?:бан|мут)"
                      r"|will\s+be\s+(?:banned|unbanned|refunded)|черновик|draft", re.I)


@pytest.mark.parametrize("lang", sorted(TEMPLATES))
@pytest.mark.parametrize("text,kind", [
    ("Nick_Name оскорбил мою маму", "complaint"), ("убил без причины", "complaint"), ("жб", "complaint"),
    ("не согласен с наказанием, разбаньте", "complaint"), ("ау", "report"), ("застрял в текстурах", "report"),
    ("оплатил донат, не пришло", "report"), ("взломали аккаунт", "report"), ("он меня оскорбляет", "report"),
])
def test_drafts_are_short_valid_and_promise_nothing(rules_path, lang, text, kind):
    index = RuleIndex(rules_path)
    analysis = analyze(ticket(text, kind))
    analysis = replace(analysis, language=lang)
    citations = policy_citations(index, analysis)
    draft = template_draft(analysis, citations, True)
    assert validate_draft(draft, citations, required=bool(draft.cited))
    assert validate_draft(draft, citations, required=bool(draft.cited),
                          allowed_clauses=approved_clauses(analysis, citations, True))
    assert len(draft.text) < 400
    assert not PROMISES.search(draft.text)
    assert set(re.findall(r"\[([^]\n]+)\]", draft.text)) == set(draft.cited)


def test_invented_sentence_is_rejected():
    assert not validate_draft(GeneratedDraft(text="Здравствуйте! Игрок будет забанен.", cited=[]), [], False)


def test_offtopic_report_is_answered_without_a_human(rules_path):
    async def run():
        svc = CopilotService(replace(Settings(), mode="test", database_path=":memory:", rules_path=rules_path,
                                     enable_groq=False, groq_api_key=None))
        try:
            offtopic = (await svc.process(ticket("ау", "report"), persist=False)).result
            payment = (await svc.process(ticket("оплатил донат, не пришло", "report"), persist=False)).result
            complaint = (await svc.process(ticket("Nick_Name оскорбил маму, скрины есть"), persist=False)).result
        finally:
            await svc.close()
        return offtopic, payment, complaint
    offtopic, payment, complaint = asyncio.run(run())
    assert offtopic.category.value == "report.offtopic" and offtopic.needs_human is False
    assert offtopic.draft_reply.cited == ["3.1"] and "3.1 ОП" in offtopic.draft_reply.text
    assert payment.needs_human is True and complaint.needs_human is True
    assert complaint.draft_reply.cited == ["2.1"] and "2.1 ОП" in complaint.draft_reply.text


@pytest.mark.parametrize("raw,expected", [
    ("Сєлеметсіз бе, ќалай ґой", "Сәлеметсіз бе, қалай ғой"),            # the case text's table
    ("кґмек керек, ойынєа кірдім", "көмек керек, ойынға кірдім"),        # as in kz-server tickets
    ("ќозґала алмаймын, Кјмектесіѕізші", "қозғала алмаймын, Көмектесіңізші"),
    ("јзірлік жаєдай", "әзірлік жағдай"),
])
def test_kazakh_substitutes_are_read_by_position(raw, expected):
    assert normalize(raw, kazakh_context=True)[0] == expected


SYNTHETIC_TRAIN = [
    ("оскорбил мою маму в чате", "2.1 ОП", None), ("оск родни", "2.1 ОП", None), ("матом обзывает семью", "2.1 OP", None),
    ("убил без причины у банка", "1.1 GZ", None), ("дм на спавне", "DM", None), ("сбил машиной и убил", "DB", None),
    ("не согласен с наказанием", None, "appeal_rejected"), ("снимите бан, я не виноват", None, "appeal_approved"),
    ("за что мут, ничего не писал", None, "appeal_rejected"),
]


def test_complaint_model_trains_on_admin_outcomes_and_holds_no_text(tmp_path):
    rows = []
    for i in range(6):
        for text, violation, verdict in SYNTHETIC_TRAIN:
            rows.append({"kind": "complaint", "messages": [{"role": "player", "text": f"{text} {i}"}],
                         "violation": violation, "verdict": verdict or "approved"})
    rows.append({"kind": "complaint", "messages": [{"role": "player", "text": "x"}], "verdict": "invalid_format"})
    path = tmp_path / "train.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as sink:
        sink.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    model, summary = train(str(path))
    assert summary["label_counts"] == {"complaint.admin": 18, "complaint.dm": 18, "complaint.insult": 18}
    out = tmp_path / "model.npz"
    model.save(str(out))
    with np.load(out, allow_pickle=False) as saved:
        assert set(saved.files) == {"version", "classes", "coef", "intercept", "idf"}
        assert saved["coef"].dtype == np.float16
    loaded = ComplaintModel.load(str(out))
    assert loaded.predict("оскорбил маму || 2.1 || ")[0] == "complaint.insult"
    assert weak_label({"verdict": "invalid_format"}) is None
    assert weak_label({"verdict": "approved", "violation": "Нарушение 5.2 ОП"}) == "complaint.cheat"
    request = ticket("он не согласен с наказанием")
    assert analyze(request, None, loaded).category.value == "complaint.admin"
