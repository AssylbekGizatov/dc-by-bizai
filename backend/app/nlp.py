"""Deterministic, entirely local baseline; not a trained or calibrated classifier.

Only player messages enter classification. Counterparty/admin replies are not labels.
Optional local embeddings are used by retrieval, never a hosted extraction API.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .schemas import Category, Extracted, TriageRequest

# Official handout cp1251 substitution table; preserve uppercase as well.
KAZAKH_SUBSTITUTIONS = {"ќ": "қ", "ґ": "ғ", "ѕ": "ң", "є": "ә", "ј": "ө", "ў": "ұ", "ї": "ү"}
TRANSLATION = str.maketrans(KAZAKH_SUBSTITUTIONS | {k.upper(): v.upper() for k, v in KAZAKH_SUBSTITUTIONS.items()})
NICKNAME = re.compile(r"(?<![\w])([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{1,29}_[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{1,29})(?![\w])")
UZBEK_CYRILLIC = re.compile(r"\b(?:салом|менга|менинг|илтимос|ёрдам|керак|тўлов\w*|ўйин\w*|ўзбек\w*|ўғир\w*|ҳақорат\w*|қил\w*|ҳисоб\w*|пул\w*|келмади|аккаунтим|қандай|қаер\w*|учун|рахмат)\b", re.I)


def without_identifiers(text: str) -> str:
    """Nicknames, URLs and redaction tokens are not linguistic/intent evidence."""
    text = NICKNAME.sub(" ", text)
    return re.sub(r"https?://\S+|<[^>]{1,40}>|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", " ", text)


def uzbek_search_form(text: str) -> str:
    """Script folding for matching only; the displayed normalized text is preserved."""
    source = "абвгдеёжзийклмнопрстуфхцчшъэюяўқғҳ"
    target = ["a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "x", "ts", "ch", "sh", "'", "e", "yu", "ya", "o'", "q", "g'", "h"]
    return text.casefold().translate(str.maketrans(dict(zip(source, target))))


def normalize(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    current = unicodedata.normalize("NFKC", text)
    if current != text:
        changes.append("unicode_nfkc")
    # Ў is also a real Uzbek letter. The handout's Kazakh legacy mapping must
    # not corrupt an Uzbek Cyrillic sentence. Distinctive legacy letters still
    # identify the Kazakh table when it is presented on its own.
    uzbek = bool(UZBEK_CYRILLIC.search(current)) or (
        "ў" in current.casefold() and not re.search(r"[ќґѕєјїәңөұүі]", current.casefold()))
    translation = TRANSLATION
    if uzbek:
        translation = {k: v for k, v in TRANSLATION.items() if chr(k) not in "ўЎ"}
    translated = current.translate(translation)
    if translated != current:
        changes.append("kazakh_cp1251_restored")
    apostrophized = re.sub(r"([oOgG])[‘’ʻʼ`´]", r"\1'", translated)
    if apostrophized != translated:
        changes.append("uzbek_apostrophe_normalized")
    current = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", apostrophized)
    if current != apostrophized:
        changes.append("invisible_controls_removed")
    clean = re.sub(r"\s+", " ", current).strip()
    if clean != current:
        changes.append("whitespace_normalized")
    return clean, changes


LANG_WORDS = {
    "ru": {"меня", "мой", "мне", "игрок", "правила", "помогите", "как", "где", "здравствуйте", "оскорбил", "застрял", "платеж", "аккаунт", "бан", "хочу", "деньги", "он", "не", "что", "привет"},
    "kk": {"мені", "маған", "менің", "мен", "қалай", "көмек", "көмектесіңіз", "көмектес", "сәлем", "сәлеметсіз", "жоқ", "бар", "ойыншы", "ақша", "төлем", "аккаунтым", "балағаттады", "беріңіз", "келмеді", "керек"},
    "uz": {"salom", "menga", "meni", "iltimos", "yordam", "kerak", "hisob", "akkaunt", "pul", "kelmadi", "qanday", "nima", "oyinchi", "haqorat", "tolov", "pulni", "qaytarishingizni", "sorayman", "qildim", "lekin", "xaridim", "yechildi", "салом", "ёрдам", "менга", "аккаунтим", "пул", "келмади"},
    "en": {"hello", "help", "please", "my", "the", "account", "stuck", "hacked", "payment", "player", "how", "where", "insulted", "money", "ban", "refund", "i", "is", "not"},
    "es": {"hola", "ayuda", "por", "favor", "mi", "cuenta", "pago", "dinero", "jugador", "insultó", "estoy", "como", "donde", "no", "gracias", "atrapado", "cobraron", "tarjeta", "compra", "reembolso", "quiero", "devolver"},
    "pt": {"olá", "ola", "ajuda", "minha", "conta", "pagamento", "dinheiro", "jogador", "estou", "como", "onde", "não", "obrigado", "preso", "por", "favor", "quero", "reembolso", "devolução", "cartão", "cobrado", "compra"},
}


def words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.casefold(), flags=re.UNICODE)


def detect_language(text: str, hint: str | None = None) -> tuple[str, float, bool]:
    text = without_identifiers(text)
    tokens = {token.replace("'", "") for token in words(text)}
    scores = {lang: float(len(tokens & vocab)) for lang, vocab in LANG_WORDS.items()}
    uz_cyrillic = len(UZBEK_CYRILLIC.findall(text))
    if re.search(r"[әғқңөұүһі]", text.casefold()) and not uz_cyrillic and not re.search(r"[ўҳ]", text.casefold()):
        scores["kk"] += 3.5
    if uz_cyrillic:
        scores["uz"] += min(5, uz_cyrillic)
    if re.search(r"[ўҳ]", text.casefold()) or re.search(r"(?:o|g)['‘’ʻ]", text.casefold()):
        scores["uz"] += 2.0
    ranked = sorted(scores, key=lambda l: scores[l], reverse=True)
    best, runner = ranked[:2]
    if scores[best] == 0:
        if re.search(r"[а-яё]", text.casefold()):
            return "ru", 0.45, False
        return "und", 0.15, False
    # A hint breaks a genuine lexical tie, never overrides observed text.
    if hint in scores and scores[hint] == scores[best]:
        best = hint
    runner = next(lang for lang in ranked if lang != best)
    mixed = scores[runner] >= 2 and scores[runner] >= scores[best] * 0.55
    confidence = min(0.9, 0.5 + 0.08 * scores[best])
    return best, confidence, mixed


PATTERNS = {
    "payment": r"донат|плат[её]ж|оплат|возврат\s+средств|верн\w*\s+деньг|деньги\s+(?:не\s+пришли|списал)|покупк\w*\s+гк|төле|теңгерім|ақша\s+түсп|ақша\s+келм|tolov|to['‘’ʻ]lov|pul\s+kelm|pul\s+to['‘’ʻ]lad|payment|paid|refund|chargeback|charged|purchase|credit\s+card|billing|donat|pago|pagamento|reembolso|pulni\s+qaytar|pul\s+yechil|aqsha|ақша\s+қайтар",
    "hack": r"взлом|украл\w*\s+акк|угнал\w*\s+акк|нет\s+доступ|потер[яе]\w*\s+доступ|не\s+могу\s+(?:войти|зайти)|аккаунт\w*\s+ұрла|аккаунт\w*\s+бұз|аккаунт\w*\s+кір|hacked|hacke|stolen\s+account|cannot\s+log|can't\s+log|lost\s+access|conta\s+roub|cuenta\s+rob|buzib|аккаунтим",
    "account": r"аккаунт|акк\b|пропал\w*\s+(?:машин|имущество|дом|деньг)|account|akkaunt|аккаунт|cuenta|conta|жоғал",
    "ban": r"разбан|бан\w*\s+(?:без|апел)|апелляц|обжал\w*\s+(?:бан|блок)|забан|заблокир|блокировк|оспорить.{0,20}наказан|банды\s+алып|unban|ban\s+appeal|banned|desban|banimento|bloqueo|ban\s+ber",
    "threat": r"убью\s+тебя\s+(?:в\s+реале|наяву)|найду\s+тебя\s+в\s+реале|угроз\w*\s+(?:жизни|вне\s+игры)|kill\s+you\s+(?:irl|in\s+real)|doxx|өмір\w*\s+қауіп",
    "mass_bug": r"(?:все|весь|массов|everyone|all\s+players).{0,25}(?:сервер|вылет|баг|server|crash)|сервер\s+(?:лежит|упал)",
    "cheat": r"чит(?:ер|ы|а|ов)?\b|аимбот|спидхак|телепорт\w*\s+чит|летает\s+по\s+воздуху|стреляет\s+через\s+стен|cheat|aimbot|speedhack|wallhack|читер",
    "scam": r"обман|мошен|вымога|(?:взял|забрал).{0,25}(?:не\s+отдал|не\s+вернул)|алдат|алдап|scam|fraud|firib|estafa|golpe",
    "rmt_ads": r"реал\w*\s+деньг|за\s+реал|прода[её]\w*\s+акк|реклам|rmt|real\s+money|selling\s+account|нақты\s+ақша|akkaunt\s+sot|dinero\s+real",
    "admin": r"админ\w*.{0,35}(?:наруш|выдал|неправ|без\s+причин|жалоб)|жалоб\w*.{0,20}админ|admin\w*.{0,20}(?:abus|unfair)|әкімш\w*.{0,20}шағым",
    "insult": r"оскорб|матер|расизм|токсич|семью|балағат|қорла|haqorat|ҳақорат|insult|racis|abuse|ofens|xing",
    "dm": r"\bдм\w*|\bdm\b|\brdm\b|убил|убива|без\s+причин|без\s+повод|зел[её]н\w*\s+зон|наруш\w*\s+рп|өлтір|killed|killing|o['‘’ʻ]ldir|mato|matou",
    "help": r"застр[яе]|текстур|вылет|баг|лага|телепорт|ошибк|қатып|тұрып\s+қал|stuck|bug|crash|error|lag|qotib|atrapad|travou",
    "question": r"\bкак\b|\bгде\b|почему|сколько|правил|қалай|қайда|неге|qanday|qayer|nima|\bhow\b|\bwhere\b|\bwhy\b|\bcomo\b|\bdonde\b|\bonde\b|лицензи|работ|купить|buy|comprar",
}
# Hand-written domain signals, not learned labels. Uzbek Cyrillic uses the same
# expressions after script folding; no external API is involved in extraction.
EXTRA_PATTERNS = {
    "payment": r"to'lov|to'ladim|pul.{0,20}(?:qaytar|tushma|yechil)|donat|ақшам.{0,20}(?:түсп|келм|қайтар)|төлед|донат(?:ил|нул)",
    "hack": r"akkaunt\w*.{0,25}(?:buz|o'g'ir|kir[ao]?\s+olma)|hisob\w*.{0,25}(?:buz|o'g'ir)|parol\w*.{0,20}(?:o'zgar|almashtir)|құпиясөз\w*.{0,25}өзгер|(?:аккаунт|тіркелгі)\w*.{0,25}(?:бұз|ұрла|кіре\s+алма)|менің\s+орныма\s+кір|доступ\w*.{0,20}(?:потер|укра)|акк\w*.{0,15}взлом",
    "account": r"(?:mashina|uy|mulk|pul|akkaunt)\w*.{0,20}yo'qol|тіркелгі",
    "ban": r"(?:ban(?:ni|dan|ga|im)?|бaн)\s+(?:oldim|olib|olgan|och|yech)|blok(?:dan|landi|lash)|тақиқ|бұғат|бан\s+алдым|баннан\s+шығар|блоктан\s+шығар|апеляц|разблокир|(?:выдал\w*|получил\w*|дали)\s+(?:мне\s+)?бан|сним\w*.{0,20}(?:бан|блок|огранич)",
    "scam": r"aldad|aldab|firibgar|алданд|ұрлап\s+кет",
    "insult": r"haqorat|so'k|сөк|балағат|оскарб|аскорб",
    "dm": r"o'ldir|sababsiz\s+(?:ur|ot)|себепсіз.{0,15}(?:өлтір|ат)",
    "help": r"qotib|tiqilib|chiqa\s+olma|тұрып\s+қал|қатып\s+қал",
    "question": r"qoida|ереже|qayer|nechta|qancha",
    "threat": r"hayot\w*.{0,20}tahdid|o'ldiraman.{0,20}(?:hayot|haqiqiy)|өмірде.{0,20}өлтір",
}
for _topic, _pattern in EXTRA_PATTERNS.items():
    PATTERNS[_topic] += "|" + _pattern
COMPILED = {k: re.compile(v, re.IGNORECASE) for k, v in PATTERNS.items()}
INJECTION = re.compile(
    r"ignore.{0,40}(?:instructions|rules|previous)|(?:игнорируй|забудь).{0,40}(?:инструкц|правил)|"
    r"system\s*(?:prompt|message|:)|developer\s*:|<\|(?:system|assistant)|\[INST\]|"
    r"выведи.{0,30}(?:секрет|ключ|api)|reveal.{0,30}(?:secret|prompt|key)|needs_human\s*[:=]\s*false|"
    r"системн\w*\s+(?:промпт|инструкц)|(?:нұсқау|ережелер|алдыңғы).{0,40}(?:елеме|ұмыт)|"
    r"(?:құпия|api).{0,20}(?:кілт|көрсет)|(?:oldingi|avvalgi|barcha).{0,30}(?:ko'rsatma|qoida).{0,30}(?:unut|e'tiborsiz)|"
    r"(?:maxfiy|api).{0,20}(?:kalit|chiqar)|(?:инструкция|қоида).{0,30}(?:унут|эътиборсиз)", re.IGNORECASE)


@dataclass(frozen=True)
class Analysis:
    text: str
    normalizations: list[str]
    language: str
    language_confidence: float
    mixed_language: bool
    category: Category
    priority: str
    confidence: float
    extracted: Extracted
    sensitive: list[str]
    injection: bool
    spam: bool
    removed_admin_messages: int
    evidence_count: int


def analyze(request: TriageRequest) -> Analysis:
    raw = "\n".join(m.text for m in request.messages if m.role == "player")
    text, changes = normalize(raw)
    lang, lang_confidence, mixed = detect_language(text, request.server_lang)
    signal_text = without_identifiers(text)
    if lang == "uz" or UZBEK_CYRILLIC.search(signal_text):
        signal_text += " " + uzbek_search_form(signal_text)
    hit = {key: bool(regex.search(signal_text)) for key, regex in COMPILED.items()}
    evidence = max(request.images_count, sum(m.attachments for m in request.messages if m.role == "player"))
    sensitive = [key for key in ("payment", "hack", "ban", "threat", "mass_bug") if hit[key]]
    if request.kind == "complaint":
        match = next((key for key in ("admin", "cheat", "scam", "rmt_ads", "insult", "dm") if hit[key]), None)
        if match:
            category = Category("complaint." + match)
            confidence = 0.73
        elif hit["question"] or len(words(text)) < 3:
            category, confidence = Category.invalid, 0.5
        else:
            category, confidence = Category.other, 0.35
    else:
        if hit["payment"]:
            category = Category.payment
        elif hit["hack"] or hit["account"] or hit["ban"]:
            category = Category.account
        elif any(hit[k] for k in ("cheat", "scam", "rmt_ads", "insult", "dm", "admin")):
            category = Category.complaint
        elif hit["help"]:
            category = Category.help
        elif hit["question"]:
            category = Category.question
        else:
            category = Category.offtopic
        confidence = 0.73 if category != Category.offtopic else 0.35
    if category in {Category.account, Category.payment, Category.admin}:
        sensitive.append(category.value)
    if any(hit[k] for k in ("payment", "hack", "threat", "mass_bug")):
        priority = "p0"
    elif any(hit[k] for k in ("cheat", "scam", "rmt_ads")) or (request.kind == "complaint" and evidence > 0):
        priority = "p1"
    elif category == Category.question and re.search(r"правил|ереже|qoida|\brules?\b|regla|regra", signal_text, re.I):
        priority = "p2"  # Taxonomy separates policy questions from game mechanics.
    elif category in {Category.question, Category.offtopic, Category.invalid} or (request.kind == "complaint" and not evidence):
        priority = "p3"
    else:
        priority = "p2"
    nickname = request.reported_nick
    if not nickname:
        found = NICKNAME.search(text)
        nickname = found.group(1) if found else None
    refs_text = (request.rule_refs_raw or "") + " " + text
    refs = list(dict.fromkeys(re.findall(r"(?<![\w.])(?:ЖБ\s+|ОП\s+|GZ\s+)?\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?!\w|\.\d)", refs_text, re.I)))[:20]
    server = request.server
    if not server:
        found = re.search(r"(?:сервер(?:е|і|де)?|server(?:da)?)\s*[№#:]?\s*(\d{1,3})\b", text, re.I)
        if not found:
            found = re.search(r"(?<![\w.])(\d{1,3})\s*(?:-?(?:й|м|ом|ші|шы))?[-\s]*(?:сервер(?:е|і|де)?|server(?:da)?)\b", text, re.I)
        server = found.group(1) if found else None
    tokens = words(text)
    repeated = len(tokens) >= 12 and len(set(tokens)) <= max(2, len(tokens) // 6)
    spam = bool(repeated or re.search(r"(.)\1{19,}", text) or len(re.findall(r"https?://", text)) >= 4)
    return Analysis(text, changes, lang, lang_confidence, mixed, category, priority, min(confidence, lang_confidence),
                    Extracted(nickname=nickname, rule_refs=refs, has_evidence=evidence > 0, server=server),
                    list(dict.fromkeys(sensitive)), bool(INJECTION.search(signal_text)), spam,
                    sum(m.role == "admin" for m in request.messages), evidence)


def redact_for_external(text: str) -> str:
    """No ticket identifiers, emails, phones, credentials or long number strings leave here."""
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    text = re.sub(r"(?:\+?\d[\s()\-]*){7,}", "[NUMBER]", text)
    text = re.sub(r"(?i)(?:password|пароль|құпиясөз|parol|парол|token|api[_ -]?key|секрет)\s*[:=]\s*\S+", "[SECRET]", text)
    text = re.sub(r"\b(?:gsk_|sk-)[A-Za-z0-9_-]{12,}\b", "[SECRET]", text)
    text = NICKNAME.sub("[NICKNAME]", text)
    return text
