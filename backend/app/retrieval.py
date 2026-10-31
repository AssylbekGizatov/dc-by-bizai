"""Local BM25 + character TF-IDF, optionally + local multilingual E5 embeddings.

No implicit downloads. Rules are indexed by section:ref: bare refs are ambiguous.
The packaged corpus is explicitly synthetic and cannot enable production readiness.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from .nlp import Analysis, COMPILED, INJECTION, UZBEK_CYRILLIC, normalize, rule_ref_key, uzbek_search_form, without_identifiers, words
from .schemas import Category, Citation


ANCHORS = {
    "complaint.insult": ("оскорб", "матер", "расизм", "нецензур", "национальн"),
    "complaint.cheat": ("чит", "сторонн", "программ"),
    "complaint.dm": ("убий", "убив", "урон", "стрел", "deathmatch", "дм", "напад"),
    "complaint.scam": ("обман", "мошен", "вымог", "имуще"),
    "complaint.rmt_ads": ("реклам", "реальн", "продаж", "прода"),
    "complaint.admin": ("администратор", "администрац", "обжал"),
    "complaint.invalid": ("жалоб", "доказательств", "оформлен"),
    "report.help": ("застр", "текстур", "баг", "техническ", "помощ"),
    "report.account": ("аккаунт", "взлом", "доступ", "парол"),
    "report.payment": ("платеж", "платёж", "донат", "оплат", "возврат"),
}
EXPANSIONS = {
    "complaint.insult": "оскорбление игрока семьи нецензурная лексика расизм",
    "complaint.cheat": "использование читов стороннего программного обеспечения",
    "complaint.dm": "убийство урон без причины нападение стрельба DM",
    "complaint.scam": "обман мошенничество имущество деньги",
    "complaint.rmt_ads": "реклама продажа аккаунтов реальные деньги",
    "complaint.admin": "жалоба администратор обжалование действий",
    "complaint.invalid": "оформление жалобы доказательства",
    "report.help": "застрял текстуры техническая помощь баг",
    "report.account": "взлом аккаунта доступ безопасность пароль",
    "report.payment": "платеж донат оплата возврат",
}


def tokenize(text: str) -> list[str]:
    # Mild character-prefix normalization improves morphology without downloaded models.
    return [w[:7] for w in words(text) if len(w) >= 2]


def retrieval_topic(analysis: Analysis) -> str:
    """The report channel has one complaint label, but retrieval needs its topic.

    This is query expansion from observed local signals, never a player-supplied
    rule number or an administrator's historical answer.
    """
    if analysis.category != Category.complaint:
        return analysis.category.value
    text = without_identifiers(analysis.text)
    if analysis.language == "uz" or UZBEK_CYRILLIC.search(text):
        text += " " + uzbek_search_form(text)
    topic = next((name for name in ("admin", "cheat", "scam", "rmt_ads", "insult", "dm") if COMPILED[name].search(text)), None)
    return "complaint." + topic if topic else analysis.category.value


class LocalEncoder:
    def __init__(self, path: str):
        if not Path(path).is_dir():
            raise ValueError("LOCAL_ENCODER_PATH must refer to an existing local model directory")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        threads = int(os.getenv("LOCAL_MODEL_THREADS", "2"))
        if not 1 <= threads <= 16:
            raise ValueError("LOCAL_MODEL_THREADS must be between 1 and 16")
        try:
            import torch
            torch.set_num_threads(threads)
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ValueError("Install requirements-models.txt to enable local embeddings") from exc
        # local_files_only prevents all model-fetch traffic, including tokenizer files.
        self.model = SentenceTransformer(path, device="cpu", local_files_only=True, trust_remote_code=False, model_kwargs={"use_safetensors": True})

    def encode(self, values: list[str], prefix: str) -> np.ndarray:
        return self.model.encode([prefix + v for v in values], normalize_embeddings=True, show_progress_bar=False)


class RuleIndex:
    def __init__(self, path: str | None = None, encoder_path: str | None = None):
        fixture = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_rules.json"
        actual = Path(path) if path else fixture
        data_bytes = actual.read_bytes()
        if len(data_bytes) > 25_000_000:
            raise ValueError("Rule file exceeds 25 MB")
        data = json.loads(data_bytes)
        self.version = hashlib.sha256(data_bytes).hexdigest()[:16]
        self.synthetic = bool(data.get("synthetic", False)) or path is None
        self.private_source = path is not None
        self.source = str(data.get("source", "private approved rules"))[:300]
        self.rules: list[Citation] = []
        seen: set[str] = set()
        for section in data.get("rules", []):
            section_id = str(section["id"])
            title = str(section.get("category", section_id))
            if not re.fullmatch(r"[\w.-]{1,64}", section_id) or not title.strip() or len(title) > 300:
                raise ValueError("Invalid rule section identifier or title")
            if any(ord(c) < 32 for c in title) or "[" in title or "]" in title:
                raise ValueError("Rule section titles must be plain single-line labels")
            for point in section.get("points", []):
                ref = str(point["ref"]).strip()
                text = str(point["text"]).strip()
                if not re.fullmatch(r"[\w.-]{1,64}", ref):
                    raise ValueError("Rule references must be plain identifiers")
                key = f"{section_id}:{ref}"
                if key in seen:
                    raise ValueError(f"Duplicate compound rule ID: {key}")
                if not text or len(text) > 40_000:
                    raise ValueError("Rule text must be non-empty and at most 40000 characters")
                seen.add(key)
                self.rules.append(Citation(id=key, ref=ref, title=f"{title} · {ref}", text=text,
                    section=title, source=self.source, synthetic=self.synthetic))
            # Glossary sections without numbered points remain retrievable as a named section.
            if not section.get("points") and str(section.get("text", "")).strip():
                key = f"{section_id}:section"
                self.rules.append(Citation(id=key, ref="section", title=title, text=str(section["text"]),
                    section=title, source=self.source, synthetic=self.synthetic))
        if not self.rules:
            raise ValueError("Rule corpus must contain at least one non-empty rule")
        self.by_id = {r.id: r for r in self.rules}
        if len(self.by_id) != len(self.rules):
            raise ValueError("Duplicate rule identifier")
        self.ref_counts = Counter(r.ref for r in self.rules)
        self.contents = [normalize(r.text)[0].casefold() for r in self.rules]
        self.bm25 = BM25Okapi([tokenize(t) for t in self.contents])
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=75_000)
        self.matrix = self.vectorizer.fit_transform(self.contents)
        self.encoder = LocalEncoder(encoder_path) if encoder_path else None
        self.embeddings = self.encoder.encode(self.contents, "passage: ") if self.encoder else None
        self.method = "bm25+char_tfidf" + ("+local_e5_rrf" if self.encoder else " (lexical baseline)")

    def relevant(self, rule: Citation, analysis: Analysis) -> bool:
        # Scope-specific policy cannot be applied merely because it contains a keyword.
        section_id = rule.id.split(":", 1)[0]
        scope_terms = {"32": ("зел", "зон", "gz", "green", "жасыл", "yashil", "яшил"), "33": ("лидер", "замест"),
                       "34": ("гос", "полици", "фракц"), "35": ("волн", "департам"),
                       "36": ("семейн", "мероприят"), "40": ("опг", "банд", "мафи"),
                       "41": ("бизнес", "войн"), "42": ("фургон", "битв")}
        if section_id in scope_terms and not any(t in analysis.text.casefold() for t in scope_terms[section_id]):
            return False
        if section_id == "43":
            return False  # glossary context is not a numbered prohibition
        content = normalize(rule.text)[0].casefold()
        query = analysis.text.casefold()
        if INJECTION.search(content) or INJECTION.search(rule.section):
            return False  # Retrieved documents are data, not application instructions.
        # Complaint formatting is not evidence that the underlying player broke a rule.
        if section_id == "31" and analysis.category != Category.invalid:
            if not (analysis.category == Category.help and "техническ" in content and "поддержк" in content):
                return False
        if analysis.category == Category.help:
            return "техническ" in content and any(w in content for w in ("поддержк", "помощ"))
        # Topic-conditioned clauses must not become blanket prohibitions in a draft.
        conditions = [
            (("за реальные деньги", "за реальную валюту"), ("реаль", "за реал", "rmt", "real money", "нақты ақша", "haqiqiy pul", "реал пул")),
            (("никнейм", "имени персонажа", "никнейма"), ("никнейм", "ник ", "ник:", "nickname", "username", "аты")),
            (("номерных знаках", "номерного знака"), ("номер", "plate", "нөмір")),
            (("названия семей", "названия семьи"), ("назван", "назва", "атал", "family name")),
            (("территории дома", "дом или квартиру", "жильцам", "жильцов"), ("дом", "квартир", "жиль", "house", "home", "үй", "пәтер")),
            (("медийных", "стрим", "стримснайп"), ("стрим", "медиа", "stream", "видео")),
            (("покидать её", "преднамеренный уход", "намеренно покидать"), ("выход", "вышел", "уход", "афк", "afk", "quit", "disconnect")),
            (("расизм, ксенофобия", "религии и вероисповедания"), ("расизм", "наци", "религ", "ксено", "racis", "relig", "нәсіл", "ұлт")),
        ]
        for contextual, signals in conditions:
            if any(marker in content for marker in contextual) and not any(signal in query for signal in signals):
                return False
        anchors = ANCHORS.get(retrieval_topic(analysis), ())
        if anchors:
            return any((anchor in words(content) if len(anchor) <= 3 else anchor in content) for anchor in anchors)
        q = set(tokenize(analysis.text))
        return len(q & set(tokenize(content))) >= 2

    def retrieve(self, analysis: Analysis, top_k: int = 3, *, strategy: str | None = None) -> list[Citation]:
        strategy = strategy or ("hybrid_e5" if self.encoder is not None else "hybrid")
        if strategy not in {"bm25", "hybrid", "hybrid_e5"}:
            raise ValueError("Unknown retrieval strategy")
        if strategy == "hybrid_e5" and self.encoder is None:
            raise ValueError("hybrid_e5 requires an explicitly configured local encoder")
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")
        # Ordinary mechanics questions and empty/off-topic reports don't need fabricated policy.
        if analysis.category in {Category.question, Category.offtopic}:
            return []
        expansion = "" if strategy == "bm25" else EXPANSIONS.get(retrieval_topic(analysis), "")
        query = without_identifiers(analysis.text) + " " + expansion
        lex = self.bm25.get_scores(tokenize(query))
        char = np.asarray((self.matrix @ self.vectorizer.transform([query]).T).toarray()).ravel()
        lex = lex / max(float(np.max(lex)), 1e-9)
        combined = np.maximum(lex, 0) if strategy == "bm25" else 0.50 * np.maximum(lex, 0) + 0.50 * char
        if strategy == "hybrid_e5":
            query_vector = self.encoder.encode([query], "query: ")[0]
            dense = self.embeddings @ query_vector
            # Reciprocal rank fusion, with explicit lexical/anchor relevance gate retained.
            fusion = np.zeros(len(self.rules))
            for score in (combined, dense):
                for rank, index in enumerate(np.argsort(-score)):
                    fusion[index] += 1.0 / (60 + rank + 1)
            ordering = np.argsort(-fusion, kind="stable")
        else:
            ordering = np.argsort(-combined, kind="stable")
        result = []
        for idx in ordering:
            rule = self.rules[int(idx)]
            if combined[idx] < 0.15 or char[idx] < 0.025 or not self.relevant(rule, analysis):
                continue
            result.append(rule.model_copy(update={"score": round(float(combined[idx]), 4)}))
            if len(result) >= top_k:
                break
        return result

    def unresolved_references(self, raw_refs: list[str]) -> list[str]:
        # Player-supplied references are claims, never forced into the retrieval output.
        # A coded ref ("GZ 1.1") resolves to its section; a bare number only if it is unique.
        unresolved = []
        for ref in raw_refs:
            section, number = rule_ref_key(ref)
            known = f"{section}:{number}" in self.by_id if section else self.ref_counts.get(number, 0) == 1
            if not known:
                unresolved.append(ref)
        return unresolved
