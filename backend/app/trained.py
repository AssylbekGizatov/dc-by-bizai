"""Complaint category model trained on the organizers' train split, labelled by admin outcomes.

Labels come from what the admin wrote in the reply template (`violation`, `verdict`), not from
the player's claim: "2.1 ОП" -> complaint.insult, "5.2" -> cheat, DM/SK/DB/GZ -> dm,
"4.1"/"4.2" -> scam, "2.3"/"4.4" -> rmt_ads, appeal_* -> admin.
Tickets whose outcome names none of these are not used.

Features are hashed (HashingVectorizer), so the saved model holds only numbers: no vocabulary,
no text from the data. The model file is built locally (`make train`) and stays out of Git.
Inference input is the player's text, the "rule" form field and the accused player's comment;
admin replies, verdicts and punishments are never inference input.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from .schemas import TriageRequest

VERSION = "complaint-hash-lr-v1"
CHAR = HashingVectorizer(analyzer="char_wb", ngram_range=(2, 5), n_features=2 ** 17, alternate_sign=False, norm=None)
WORD = HashingVectorizer(analyzer="word", ngram_range=(1, 2), n_features=2 ** 16, alternate_sign=False, norm=None,
                         token_pattern=r"(?u)\b\w+\b")


def weak_label(record: dict) -> str | None:
    """Category from the admin's outcome; None when the outcome does not name one."""
    violation = str(record.get("violation") or "").upper()
    verdict = record.get("verdict")
    if verdict in ("appeal_approved", "appeal_rejected"):
        return "complaint.admin"
    # invalid_format is not used: it marks formatting faults (evidence host, 48 hours, missing
    # form fields) that the text does not show; "not a complaint / no content" is left to rules.
    if re.search(r"\b2[.,]\s?[146]\b", violation):
        return "complaint.insult"
    if re.search(r"\b5[.,]\s?2\b", violation):
        return "complaint.cheat"
    if re.search(r"\b5[.,]\s?[34]\b|\bDM\b|\bДМ\b|\bDB\b|\bSK\b|\bTK\b|GZ|NONRP|НОН ?РП", violation):
        return "complaint.dm"
    if re.search(r"\b4[.,]\s?[12]\b", violation):
        return "complaint.scam"
    if re.search(r"\b2[.,]\s?3\b|\b4[.,]\s?4\b", violation):
        return "complaint.rmt_ads"
    return None


def model_text(player: str, rule_field: str | None, accused: str) -> str:
    return (player + " || " + (rule_field or "") + " || " + accused).lower()


def record_text(record: dict) -> str:
    messages = record.get("messages") or []
    player = " ".join(m.get("text", "") for m in messages if m.get("role") == "player")
    accused = " ".join(m.get("text", "") for m in messages if m.get("role") == "reported_player")
    return model_text(player, record.get("rule_refs_raw"), accused)


def request_text(request: TriageRequest) -> str:
    player = " ".join(m.text for m in request.messages if m.role == "player")
    accused = " ".join(m.text for m in request.messages if m.role == "reported_player")
    return model_text(player, request.rule_refs_raw, accused)


def _counts(texts: list[str]):
    from scipy.sparse import hstack
    return hstack([CHAR.transform(texts), WORD.transform(texts)]).tocsr()


def _tfidf(counts, idf: np.ndarray):
    from sklearn.preprocessing import normalize
    weighted = counts.copy()
    weighted.data = np.log1p(weighted.data)  # sublinear tf
    weighted = weighted.multiply(idf).tocsr()
    return normalize(weighted)


class ComplaintModel:
    def __init__(self, classes: list[str], coef: np.ndarray, intercept: np.ndarray, idf: np.ndarray):
        self.classes, self.coef, self.intercept, self.idf = classes, coef.astype(np.float32), intercept, idf

    @classmethod
    def load(cls, path: str) -> "ComplaintModel":
        with np.load(path, allow_pickle=False) as data:
            if str(data["version"]) != VERSION:
                raise ValueError("Unsupported complaint model version")
            return cls([str(c) for c in data["classes"]], data["coef"], data["intercept"], data["idf"])

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, version=np.array(VERSION), classes=np.array(self.classes),
                            coef=self.coef.astype(np.float16), intercept=self.intercept.astype(np.float32),
                            idf=self.idf.astype(np.float32))

    def predict(self, text: str) -> tuple[str, float]:
        x = _tfidf(_counts([text]), self.idf)
        scores = np.asarray(x @ self.coef.T).ravel() + self.intercept
        scores = np.exp(scores - scores.max())
        probs = scores / scores.sum()
        best = int(np.argmax(probs))
        return self.classes[best], float(probs[best])


def iter_records(path: str):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def _fit(texts: list[str], labels: list[str], C: float) -> ComplaintModel:
    from sklearn.linear_model import LogisticRegression
    counts = _counts(texts)
    document_frequency = np.bincount(counts.indices, minlength=counts.shape[1])
    idf = np.log((1 + counts.shape[0]) / (1 + document_frequency)) + 1.0
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(_tfidf(counts, idf), labels)
    return ComplaintModel(list(clf.classes_), clf.coef_, clf.intercept_, idf)


def train_reports(path: str, C: float = 4.0) -> tuple[ComplaintModel, dict]:
    """Report-channel model trained on manually labelled tickets (scripts/labeling.py rows:
    kind, text, field, accused, category, split). Only split == "train" is used, so the dev
    and human test parts never enter training. Same hashed features as the complaint model."""
    texts, labels = [], []
    for row in iter_records(path):
        if row.get("kind") != "report" or row.get("split") != "train" or not str(row.get("category", "")).startswith("report."):
            continue
        texts.append(model_text(row.get("text", ""), row.get("field"), row.get("accused", "")))
        labels.append(row["category"])
    if len(set(labels)) < 2:
        raise ValueError("Not enough labelled reports to train")
    model = _fit(texts, labels, C)
    return model, {"version": VERSION, "channel": "report", "trained_on": len(labels),
                   "label_counts": {c: labels.count(c) for c in sorted(set(labels))}}


def train(path: str, exclude_texts: set[str] | None = None, exclude_ids: set[str] | None = None) -> tuple[ComplaintModel, dict]:
    """exclude_ids: ticket_ids kept out of training (human-labelled test tickets come from train)."""
    from sklearn.linear_model import LogisticRegression
    texts, labels = [], []
    for record in iter_records(path):
        if record.get("kind") != "complaint":
            continue
        label = weak_label(record)
        if label is None or (exclude_ids and record.get("ticket_id") in exclude_ids):
            continue
        text = record_text(record)
        if exclude_texts and text.split(" || ")[0].strip() in exclude_texts:
            continue
        texts.append(text)
        labels.append(label)
    if len(set(labels)) < 2:
        raise ValueError("Not enough labelled complaints to train")
    counts = _counts(texts)
    document_frequency = np.bincount(counts.indices, minlength=counts.shape[1])
    idf = np.log((1 + counts.shape[0]) / (1 + document_frequency)) + 1.0
    features = _tfidf(counts, idf)
    clf = LogisticRegression(C=4, max_iter=2000, class_weight="balanced")
    clf.fit(features, labels)
    model = ComplaintModel(list(clf.classes_), clf.coef_, clf.intercept_, idf)
    summary = {"version": VERSION, "trained_on": len(labels), "excluded_ids": len(exclude_ids or ()),
               "label_counts": {c: labels.count(c) for c in sorted(set(labels))}}
    return model, summary
