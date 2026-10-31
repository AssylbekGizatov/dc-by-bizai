"""Synthetic regressions for NLP behaviour derived from handout statistics.

Texts are hand-written; no organizer tickets, labels or rule texts are stored here.
"""
import json

import pytest

from app.nlp import analyze, extract_rule_refs, normalize, rule_ref_key
from app.retrieval import RuleIndex
from app.schemas import Category, TriageRequest

RULE_CATEGORIES = {"2.1": {"complaint.insult"}, "5.2": {"complaint.cheat"}, "5.3": {"complaint.dm"},
                   "GZ": {"complaint.dm"}, "4.1": {"complaint.scam"}}


def ticket(text, kind="report", **kwargs):
    return TriageRequest(kind=kind, messages=[{"role": "player", "text": text}], **kwargs)


# --- cp1251 legacy letters ------------------------------------------------------

def test_legacy_table_only_on_kz_server_or_with_kazakh_markers():
    ukrainian = "Поможіть, голосової чат не працює, він матюкається"
    assert normalize(ukrainian, kazakh_context=False)[0] == ukrainian
    assert normalize(ukrainian)[0] == ukrainian          # no metadata, no Kazakh-only marker
    assert normalize("ойынєа кірдім", kazakh_context=True)[0] == "ойынға кірдім"
    assert normalize("Машина аударылып ќалды")[0] == "Машина аударылып қалды"   # ќ is a Kazakh-only marker


def test_server_metadata_reaches_normalization():
    assert "kazakh_cp1251_restored" in analyze(ticket("кґмек керек", region="kz")).normalizations
    assert "kazakh_cp1251_restored" not in analyze(ticket("він матюкається", region="cis")).normalizations


def test_numero_sign_survives_normalization():
    assert normalize("пункт №2.1")[0] == "пункт №2.1"
    assert analyze(ticket("нарушение пункт №2.1", kind="complaint")).extracted.rule_refs == ["2.1"]
    assert normalize("ＡＢＣ　１２")[0] == "ABC 12"           # fullwidth still folded


# --- language -----------------------------------------------------------------

@pytest.mark.parametrize("text", ["Допоможіть будь ласка", "переверніть машину пж", "адмін поможіть"])
def test_ukrainian_i_is_not_kazakh(text):
    # "мені" is a word of both Kazakh and Ukrainian and stays a Kazakh lexical signal.
    assert analyze(ticket(text)).language != "kk"


@pytest.mark.parametrize("text", ["meni kishanlab moshinaga solib olib ketdi", "sababsiz sokdi chora korilsin", "nega ban berdi"])
def test_uzbek_latin_without_apostrophes(text):
    assert analyze(ticket(text)).language == "uz"


# --- rule references --------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("2.1 ОП", ["2.1"]), ("2.1оп", ["2.1"]), ("2.1 op", ["2.1"]), ("5,2 ОП", ["5.2"]),
    ("п.2.1", ["2.1"]), ("1.1 гз", ["GZ 1.1"]), ("ЖБ 1.1.2", ["ЖБ 1.1.2"]), ("1.25 фв", ["FW 1.25"]),
    ("6.3 ПГО", ["ПГО 6.3"]), ("2.1 опг", ["ОПГ 2.1"]), ("1.13 bw", ["BW 1.13"]),
    ("3,5,7", []), ("14.03.2026", []), ("v1.2", []),
])
def test_rule_reference_codes(text, expected):
    assert extract_rule_refs(text) == expected


def test_rule_reference_form_field_comma():
    assert extract_rule_refs("оск", "2,1") == ["2.1"]


def test_coded_reference_resolves_to_its_section(tmp_path):
    rules = {"synthetic": True, "rules": [
        {"id": 30, "category": "Synthetic general", "points": [{"ref": "1.1", "text": "Синтетический общий пункт."}]},
        {"id": 32, "category": "Synthetic zone", "points": [{"ref": "1.1", "text": "Синтетический пункт зоны."}]}]}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    index = RuleIndex(str(path))
    assert rule_ref_key("GZ 1.1") == ("32", "1.1")
    assert index.unresolved_references(["GZ 1.1", "1.1", "ПГО 9.9"]) == ["1.1", "ПГО 9.9"]


# --- category ------------------------------------------------------------------

@pytest.mark.parametrize("text,category", [
    ("оск родни", Category.insult), ("обзывает матом", Category.insult), ("дб у банка", Category.dm),
    ("связка в зз", Category.dm), ("софт, летает", Category.cheat), ("скам на машину", Category.scam),
    ("не согласен с наказанием", Category.admin),
])
def test_complaint_slang_and_appeals(text, category):
    assert analyze(ticket(text, kind="complaint", images_count=1)).category == category


def test_appeal_is_a_mandatory_human_signal():
    assert "ban" in analyze(ticket("не согласен с наказанием, прошу пересмотреть", kind="complaint")).sensitive


def test_claimed_rule_names_the_category_only_without_text_signal():
    bare = ticket("2.1 ОП <url>", kind="complaint", images_count=1)
    assert analyze(bare).category == Category.invalid                      # no taxonomy loaded
    assert analyze(bare, RULE_CATEGORIES).category == Category.insult
    assert analyze(ticket("1.1 гз", kind="complaint"), RULE_CATEGORIES).category == Category.dm
    assert analyze(ticket("5.2 ОП + 5.3 ОП", kind="complaint"), RULE_CATEGORIES).category == Category.cheat
    assert analyze(ticket("софт 2.1 ОП", kind="complaint"), RULE_CATEGORIES).category == Category.cheat


def test_request_to_ban_someone_else_is_not_an_account_problem():
    current = analyze(ticket("прошу забанить читера"))
    assert current.category != Category.account and "ban" not in current.sensitive


# --- priority and payments -------------------------------------------------------

def test_game_fine_is_not_a_payment():
    current = analyze(ticket("где оплатить штраф?"))
    assert current.category != Category.payment and current.priority != "p0"


def test_payment_word_in_complaint_is_sensitive_but_not_p0():
    current = analyze(ticket("продаёт аккаунт за донат", kind="complaint", images_count=1))
    assert "payment" in current.sensitive and current.priority != "p0"


def test_payment_report_stays_p0():
    assert analyze(ticket("оплатил донат, деньги не пришли")).priority == "p0"


@pytest.mark.parametrize("text,images,priority", [
    ("оскорбил меня в чате", 1, "p2"), ("дм у спавна", 2, "p2"),
    ("использует читы", 1, "p1"), ("обманул на машину", 1, "p1"),
    ("оскорбил меня в чате", 0, "p3"),
])
def test_complaint_priority_follows_taxonomy_problem(text, images, priority):
    assert analyze(ticket(text, kind="complaint", images_count=images)).priority == priority


@pytest.mark.parametrize("text,expected", [
    ("Массовые нарушения DM", False), ("на видео все видно, багажник пустой", False),
    ("у всех вылетает игра", True), ("сервер лежит", True),
])
def test_mass_bug_needs_a_bug_word(text, expected):
    assert ("mass_bug" in analyze(ticket(text)).sensitive) is expected


# --- evidence ---------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("вот фрапс <url>", True), ("скрины есть", True), ("скринов нет", False), ("без доказательств", False),
    ("оскорбил меня", False),
])
def test_has_evidence_counts_links_and_claims(text, expected):
    assert analyze(ticket(text, kind="complaint")).extracted.has_evidence is expected
