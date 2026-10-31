"""Deterministic, entirely local baseline; not a trained or calibrated classifier.

Only player messages enter classification. Counterparty/admin replies are not labels.
Optional local embeddings are used by retrieval, never a hosted extraction API.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .schemas import Category, Extracted, TriageRequest

# cp1251 substitutes. ќ→қ, ѕ→ң, ў→ұ, ї→ү are unambiguous. For ґ, є, ј the case text lists
# ґ→ғ, є→ә, ј→ө, while kz-server tickets read as Kazakh only with ґ→ө (кґмек, ґтініш),
# є→ғ (аєалар, ойынєа), ј→ә (јзірлік). Both readings are handled by position: Kazakh has no
# two vowels in a row, so next to a vowel the substitute is the consonant ғ, between
# consonants it is the vowel (ґ→ө, є→ә); ј is always a vowel, ө for known ө-stems, else ә.
KAZAKH_SUBSTITUTIONS = {"ќ": "қ", "ѕ": "ң", "ў": "ұ", "ї": "ү"}
AMBIGUOUS_VOWEL = {"ґ": "ө", "є": "ә"}
KAZAKH_VOWELS = set("аәеёиоөұүыіэюяуј")
O_STEMS = ("көмек", "көр", "көз", "көл", "көп", "көш", "көт", "көң", "сөз", "сөй", "өз", "өт", "өл", "өмір", "өн",
           "өр", "өш", "өк", "бөл", "бөг", "төл", "төм", "төр", "төб", "жөн", "мөл", "дөң", "сөн", "шөп", "қөз")
A_STEMS = ("әзір", "әке", "әже", "әкім", "әдем", "әлі", "әр", "әл", "сәлем", "мәсел", "кәзір", "бәр", "нәрсе", "кәсіп")


def _resolve_ambiguous(text: str) -> str:
    chars = list(text)
    lower = text.casefold()
    for i, ch in enumerate(lower):
        if ch not in AMBIGUOUS_VOWEL:
            continue
        prev = lower[i - 1] if i > 0 else ""
        nxt = lower[i + 1] if i + 1 < len(lower) else ""
        consonant = prev in KAZAKH_VOWELS or (nxt in KAZAKH_VOWELS and nxt != "")
        letter = "ғ" if consonant else AMBIGUOUS_VOWEL[ch]
        chars[i] = letter.upper() if text[i].isupper() else letter
    resolved = "".join(chars)

    def vowel_j(match: re.Match) -> str:
        word = match.group(0)
        folded = word.casefold()
        letter = "ө" if (folded.replace("ј", "ө").startswith(O_STEMS)
                         and not folded.replace("ј", "ә").startswith(A_STEMS)) else "ә"
        return "".join((letter.upper() if c == "Ј" else letter) if c in "јЈ" else c for c in word)

    return re.sub(r"\w*[јЈ]\w*", vowel_j, resolved)


TRANSLATION = str.maketrans(KAZAKH_SUBSTITUTIONS | {k.upper(): v.upper() for k, v in KAZAKH_SUBSTITUTIONS.items()})
# Seen only in substituted Kazakh. є/ї (and і) are real Ukrainian letters on cis servers
# (голосової, матюкається), ў is a real Uzbek letter.
KAZAKH_LEGACY_MARKERS = re.compile(r"[ќЌѕЅјЈґҐ]")
NICKNAME = re.compile(r"(?<![\w])([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{1,29}_[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{1,29})(?![\w])")
FULLWIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)} | {0x3000: 0x20}
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


def kazakh_legacy_context(region: str | None = None, server_lang: str | None = None) -> bool | None:
    """True on a kz server, False on any other known server, None without metadata."""
    if region is None and server_lang is None:
        return None
    return region == "kz" or server_lang == "kk"


def normalize(text: str, kazakh_context: bool | None = None) -> tuple[str, list[str]]:
    changes: list[str] = []
    # NFC, not NFKC: NFKC turns "№2.1" into "No2.1" and hides the rule reference.
    # Fullwidth ASCII (what NFKC was mostly useful for) is folded explicitly.
    current = unicodedata.normalize("NFC", text)
    current = current.translate(FULLWIDTH)
    if current != text:
        changes.append("unicode_normalized")
    # The legacy table only exists on kz servers (cis carries Ukrainian є/ї, uz carries
    # Uzbek ў). Without server metadata, only letters seen solely in substituted Kazakh
    # switch it on. Ў is also a real Uzbek letter and is kept in Uzbek sentences.
    apply_table = kazakh_context is True or (kazakh_context is None and bool(KAZAKH_LEGACY_MARKERS.search(current)))
    uzbek = bool(UZBEK_CYRILLIC.search(current)) or (
        "ў" in current.casefold() and not re.search(r"[ќґѕєјїәңөұүі]", current.casefold()))
    translation = TRANSLATION if apply_table else {}
    if uzbek:
        translation = {k: v for k, v in translation.items() if chr(k) not in "ўЎ"}
    translated = current.translate(translation)
    if apply_table:
        translated = _resolve_ambiguous(translated)
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
# Uzbek Latin without oʻ/gʻ ("meni kishanlab moshinaga ... sokindi") is common on uz servers.
# Frequent words of uz-server Latin tickets (>= 12 uses, >= 8x rarer on cis servers), minus
# words shared with en/es/pt (men, man, va, da, bola, esa) and game slang (ban, warn, rp).
LANG_WORDS["uz"] |= set(
    "onadan onamdan chora mani manga haqorat xaqorat qildi qilib qilish qilgan sababsiz sababsz"
    " besabab sabab deb iltmos sokdi sokish sokib sokindi sokvoti bilan ozi ozidan uzi uzidan otib"
    " berila berilgan berdi bering beringlar jazo bunga buni yana uchun olib assalomu alaykum kelib"
    " korila korilar korib talab keyin kunga dedi desam yoq kishan kishanlab yoki hech oldirdi"
    " shikoyat unga boshqa ekan qoida kere ketti keti ketdi emas edim sorab endi nega nma qanaqa"
    " hurmatli qamadi tashladi tashadi qoydi turgan adminlar faqat qolaman boglab bandan banga"
    " chiqib noroziman narsa xato qayta ogohlantirish".split())


def words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.casefold(), flags=re.UNICODE)


def detect_language(text: str, hint: str | None = None) -> tuple[str, float, bool]:
    text = without_identifiers(text)
    tokens = {token.replace("'", "") for token in words(text)}
    scores = {lang: float(len(tokens & vocab)) for lang, vocab in LANG_WORDS.items()}
    uz_cyrillic = len(UZBEK_CYRILLIC.findall(text))
    # і is left out: Ukrainian tickets (поможіть, переверніть) occur on cis servers.
    if re.search(r"[әғқңөұүһ]", text.casefold()) and not uz_cyrillic and not re.search(r"[ўҳ]", text.casefold()):
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
    # Bare "забан" mostly asks to ban someone else ("прошу забанить читера"); only one's own ban counts.
    "ban": r"разбан|бан\w*\s+(?:без|апел)|апелляц|обжал\w*\s+(?:бан|блок)|(?:меня|мой\s+акк\w*)\s+(?:\w+\s+)?забан|забан\w*\s+меня|заблокир|блокировк|оспорить.{0,20}наказан|банды\s+алып|unban|ban\s+appeal|banned|desban|banimento|bloqueo|ban\s+ber",
    "threat": r"убью\s+тебя\s+(?:в\s+реале|наяву)|найду\s+тебя\s+в\s+реале|угроз\w*\s+(?:жизни|вне\s+игры)|kill\s+you\s+(?:irl|in\s+real)|doxx|өмір\w*\s+қауіп",
    # "Массовые нарушения", "скам всего сервера" are complaints, not outages: a bug word is required.
    "mass_bug": r"(?:\bвсе\b|\bвесь\b|у\s+всех|массов|everyone|all\s+players).{0,25}(?:вылет\w*|\bбаг(?:и|а|ов|ом)?\b|\bлаг\w*|\bcrash\w*|\bbugs?\b|\blag\w*)|(?:сервер|server)\w*\s+(?:лежит|упал|down)",
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
# Game slang that names the violation directly; the most frequent values of the handout
# "пункт правил" field and complaint texts (оск, дм, дб, тк, софт, скам).
SLANG_PATTERNS = {
    "insult": r"\bоск\w*|\bosk\w*|\bock\b|\bоскар\w*|обзыва\w*|\bмат(?:ом|ы|ами|оми|ерится|юк\w*)?\b|\bродн(?:и|ю|ых|ым)\b"
              r"|haqorat|haqrat|xaqorat|sok(?:di|ish|ib|indi|voti)\b|onadan|onamdan",
    # Green-zone violations ("связка в зз") map to complaint.dm in the taxonomy (rules 5.3, 5.4, GZ).
    "dm": r"\bдб\b|\bdb\b|\bтк\b|\btk\b|\bск\b|\bsk\b|non\s*-?rp|\bнрп\b|\bnrp\b|sababsiz|besabab|\bзз\b|\bгз\b|\bgz\b",
    "cheat": r"\bсофт\w*|\bsoft\b|\bаим\w*|\baim\b",
    "scam": r"\bскам\w*|\bscam\w*|\bskam\w*|\bкинул\w*|\bразв[её]л\w*",
}
for _topic, _pattern in SLANG_PATTERNS.items():
    EXTRA_PATTERNS[_topic] = EXTRA_PATTERNS[_topic] + "|" + _pattern if _topic in EXTRA_PATTERNS else _pattern
# A complaint that disputes the player's own punishment is a complaint about the admin's
# decision ("не согласен с наказанием": ~6k handout complaints, mostly appeal verdicts).
EXTRA_PATTERNS["admin"] = (r"не\s*соглас\w*|несоглас\w*|оспор\w*.{0,20}(?:наказан|бан|мут|варн|решени)"
                           r"|пересмотр\w*.{0,20}(?:наказан|бан|мут|варн|решени|жалоб)|ошибк\w*\s+бан\w*|noroziman")
EXTRA_PATTERNS["ban"] += r"|не\s*соглас\w*\s+с\s+(?:наказан|бан|блок|решени)"
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


# Rule documents are numbered from 1.1 each, so a reference needs its document. Codes are
# the ones players and admins use ("2.1 ОП", "1.1 гз", "1.25 фв", "6.3 ПГО"); section ids
# follow rules.json, as in retrieval.relevant(). A bare number stays bare (ambiguous claim).
RULE_SECTION_CODES = {
    "ОП": ("30", ("оп", "op", "ор", "oп")),          # "ор"/"oп": mixed-script typos of ОП
    "ЖБ": ("31", ("жб", "jb")),
    "GZ": ("32", ("gz", "гз", "зз", "zz", "green")),
    "ПГО": ("34", ("пго", "pgo")),
    "FW": ("36", ("fw", "фв", "fv")),
    "ОПГ": ("40", ("опг", "opg")),
    "BW": ("41", ("bw", "бв")),
    "ФУРА": ("42", ("фура", "fura")),
}
_CODE_OF = {alias: code for code, (_, aliases) in RULE_SECTION_CODES.items() for alias in aliases}
_CODE_ALT = "|".join(sorted(map(re.escape, _CODE_OF), key=len, reverse=True))
_REF_NUM = r"\d{1,2}(?:\.\d{1,2}){1,2}"
RULE_REF = re.compile(
    rf"(?<![A-Za-z\d,])(?<!\d\.)(?:(?<![A-Za-zА-Яа-яЁё])(?P<code1>{_CODE_ALT})\s*(?P<num1>{_REF_NUM})"
    rf"|(?P<num2>{_REF_NUM}|\d{{1,2}},\d{{1,2}}(?=\s*(?:{_CODE_ALT})(?![A-Za-zА-Яа-яЁё])))"
    rf"(?:\s*(?P<code2>{_CODE_ALT})(?![A-Za-zА-Яа-яЁё]))?)(?!\d|[.,]\d)", re.IGNORECASE)
_FIELD_COMMA_REF = re.compile(r"^\s*(\d{1,2}),(\d{1,2})\s*$")   # the form field alone: "2,1"


def extract_rule_refs(text: str, form_field: str | None = None) -> list[str]:
    """Player-claimed refs: "2.1" for the general rules (as in the contract), "GZ 1.1" otherwise."""
    field = _FIELD_COMMA_REF.sub(r"\1.\2", form_field or "")
    refs = []
    for source in (field, text):
        for m in RULE_REF.finditer(source):
            number = (m.group("num1") or m.group("num2")).replace(",", ".")
            code = _CODE_OF.get((m.group("code1") or m.group("code2") or "").casefold())
            # The contract shows "2.1 ОП" as "2.1"; other documents keep their code.
            refs.append(number if code in (None, "ОП") else f"{code} {number}")
    return list(dict.fromkeys(refs))[:20]


def rule_hint(refs: list[str], rule_categories: dict[str, set[str]] | None, prefix: str) -> str | None:
    """Category the taxonomy ties to the first claimed ref that has exactly one;
    "GZ" in the taxonomy covers every "GZ x.y". "5.2 ОП + 5.3 ОП" follows the first ref."""
    for ref in refs:
        found: set[str] = set()
        for key in (ref, ref.split(" ")[0]) if " " in ref else (ref,):
            found |= {c for c in (rule_categories or {}).get(key, ()) if c.startswith(prefix)}
        if len(found) == 1:
            return found.pop()
    return None


# Below these probabilities the trained complaint model abstains and the rules decide. On the
# organizer valid, by admin outcome (270 complaints): rules alone 0.641, with the model 0.815.
MODEL_MIN_PROBABILITY = 0.4
MODEL_OVER_SIGNAL_PROBABILITY = 0.6
MODEL_SURE_PROBABILITY = 0.7
# Report model (manually labelled reports): chosen on dev, 18 reports — rules 0.611 acc / 0.565
# macro-F1, rules + model at 0.3: 0.778 / 0.776. Payment and account stay rule-only (p0 routes).
REPORT_MODEL_MIN_PROBABILITY = 0.3
GAME_FINE = re.compile(r"(?:о|за)?плат\w*\s+(?:\w+\s+){0,2}штраф\w*|штраф\w*", re.IGNORECASE)
# Links are masked as <url> in the handout; fraps/video links are how players attach evidence.
EVIDENCE_LINK = re.compile(r"<url>|https?://", re.IGNORECASE)
EVIDENCE_CLAIM = re.compile(
    r"скрин\w*|скриншот\w*|видео\w*|фрапс\w*|fraps\w*|док-?в\w*|доказательств\w*|пруф\w*"
    r"|дәлел\w*|skrin\w*|video\w*|dalil\w*|isbot\w*|screen\w*|proof\w*", re.IGNORECASE)
_NO_BEFORE = re.compile(r"\b(?:нет|без|не|нету|жоқ|yo'q|yoq|no|without)\s+$", re.IGNORECASE)
_NO_AFTER = re.compile(r"^\s*(?:нет|нету|жоқ|yo'q|yoq)\b", re.IGNORECASE)


def claims_evidence(text: str) -> bool:
    """The player says evidence exists ("скрины есть"), unless negated ("скринов нет")."""
    for m in EVIDENCE_CLAIM.finditer(text):
        if not (_NO_BEFORE.search(text[max(0, m.start() - 12):m.start()]) or _NO_AFTER.search(text[m.end():m.end() + 8])):
            return True
    return False


def rule_ref_key(ref: str) -> tuple[str | None, str]:
    """("30", "2.1") for "2.1 ОП"-style refs; (None, "2.1") for a bare, ambiguous number."""
    code, _, number = ref.rpartition(" ")
    if code.upper() in RULE_SECTION_CODES:
        return RULE_SECTION_CODES[code.upper()][0], number
    return None, ref


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


def analyze(request: TriageRequest, rule_categories: dict[str, set[str]] | None = None, complaint_model=None,
            report_model=None) -> Analysis:
    """rule_categories: taxonomy rule ref -> category codes (taxonomy.json categories[].rules),
    used only when no text signal names the problem ("2.1 ОП" alone).
    complaint_model: optional trained model (app.trained); when it is confident it decides the
    complaint category, otherwise the rules below do."""
    raw = "\n".join(m.text for m in request.messages if m.role == "player")
    text, changes = normalize(raw, kazakh_legacy_context(request.region, request.server_lang))
    lang, lang_confidence, mixed = detect_language(text, request.server_lang)
    signal_text = without_identifiers(text)
    if lang == "uz" or UZBEK_CYRILLIC.search(signal_text):
        signal_text += " " + uzbek_search_form(signal_text)
    hit = {key: bool(regex.search(signal_text)) for key, regex in COMPILED.items()}
    # "где оплатить штраф" is an in-game fine, not a real-money payment.
    hit["payment"] = bool(COMPILED["payment"].search(GAME_FINE.sub(" ", signal_text)))
    evidence = max(request.images_count, sum(m.attachments for m in request.messages if m.role == "player"))
    # has_evidence = attachments present or claimed (a fraps/video link, "скрины есть"); never proof.
    has_evidence = evidence > 0 or bool(EVIDENCE_LINK.search(raw)) or claims_evidence(text)
    refs = extract_rule_refs(text, request.rule_refs_raw)
    sensitive = [key for key in ("payment", "hack", "ban", "threat", "mass_bug") if hit[key]]
    if request.kind == "complaint":
        match = next((key for key in ("admin", "cheat", "scam", "rmt_ads", "insult", "dm") if hit[key]), None)
        by_rule = rule_hint(refs, rule_categories, "complaint.")
        if match:
            category = Category("complaint." + match)
            confidence = 0.73
        elif by_rule:
            # The claimed rule names the problem; the claim itself still needs checking.
            category, confidence = Category(by_rule), 0.6
        elif hit["question"] or len(words(text)) < 3:
            category, confidence = Category.invalid, 0.5
        else:
            category, confidence = Category.other, 0.35
        if complaint_model is not None:
            from .trained import request_text
            predicted, probability = complaint_model.predict(request_text(request))
            # Empty or question-only complaints ("жб", "вот он", "как купить дом") stay invalid
            # unless the model is sure ("за что бан?" is an appeal, not a question).
            # An explicit keyword signal (оск, дм, sababsiz, софт...) is overridden only by a fairly sure model.
            needed = (MODEL_SURE_PROBABILITY if category == Category.invalid
                      else MODEL_OVER_SIGNAL_PROBABILITY if match else MODEL_MIN_PROBABILITY)
            if probability >= needed:
                category, confidence = Category(predicted), max(0.55, min(0.95, probability))
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
        # The model separates help / question / complaint / off-topic; it never creates or
        # removes a payment or account route (mandatory human review, p0) on its own.
        if report_model is not None and category not in {Category.payment, Category.account}:
            from .trained import request_text
            predicted, probability = report_model.predict(request_text(request))
            if (probability >= REPORT_MODEL_MIN_PROBABILITY and predicted.startswith("report.")
                    and predicted not in {Category.payment.value, Category.account.value}):
                category, confidence = Category(predicted), max(0.55, min(0.95, probability))
    if category in {Category.account, Category.payment, Category.admin}:
        sensitive.append(category.value)
    # Payment words stay a sensitive (human) signal everywhere, but p0 needs a payment
    # report: complaints say "продаёт за донат". Every handout complaint has images_count >= 1,
    # so "with evidence -> p1" would put all complaints in p1 and leave the taxonomy's p2
    # (insults, DM) unreachable; p1 follows the taxonomy's named problems instead.
    if any(hit[k] for k in ("hack", "threat", "mass_bug")) or category == Category.payment:
        priority = "p0"
    elif category in {Category.cheat, Category.scam, Category.rmt_ads} or (
            category == Category.complaint and any(hit[k] for k in ("cheat", "scam", "rmt_ads"))):
        priority = "p1"
    elif category == Category.question and re.search(r"правил|ереже|qoida|\brules?\b|regla|regra", signal_text, re.I):
        priority = "p2"  # Taxonomy separates policy questions from game mechanics.
    elif category in {Category.question, Category.offtopic, Category.invalid} or (request.kind == "complaint" and not has_evidence):
        priority = "p3"
    else:
        priority = "p2"
    nickname = request.reported_nick
    if not nickname:
        found = NICKNAME.search(text)
        nickname = found.group(1) if found else None
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
                    Extracted(nickname=nickname, rule_refs=refs, has_evidence=has_evidence, server=server),
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
