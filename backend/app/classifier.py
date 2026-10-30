"""Optional local multilingual encoder intent fallback; zero-shot, NOT fine-tuned.

The phrases below are synthetic intent descriptions, never historical admin labels.
Only unresolved lexical classifications can change. Escalation rules remain independent.
"""
from dataclasses import replace

import numpy as np

from .nlp import Analysis
from .schemas import Category

PROTOTYPES = {
    "complaint.insult": "A player insults and harasses me or my family in chat. Игрок оскорбляет меня в чате. Ойыншы мені балағаттады.",
    "complaint.cheat": "A player uses cheats or forbidden software to gain an advantage. Игрок использует читы. Ойыншы чит қолданады.",
    "complaint.dm": "A player kills or damages me without a roleplay reason. Игрок убивает без причины. Ойыншы себепсіз өлтірді.",
    "complaint.scam": "A player deceived me during a property or money exchange. Игрок обманул при сделке. Ойыншы мені алдап кетті.",
    "complaint.rmt_ads": "A player advertises or sells an account for real money. Продажа аккаунта за реальные деньги и реклама.",
    "complaint.admin": "Complaint about an administrator abusing powers. Жалоба на действия администратора. Әкімшінің әрекетіне шағым.",
    "complaint.other": "An unspecified rule violation by another player needs clarification. Другое нарушение правил, нужны подробности.",
    "complaint.invalid": "An empty or incorrectly submitted complaint without a clear allegation. Непонятная или неправильно оформленная жалоба.",
    "report.question": "Question asking how a game mechanic works or where to find a job. Вопрос о механике игры. Ойында жұмысқа қалай орналасамын?",
    "report.help": "Player is stuck in textures or encounters a technical bug and needs help. Застрял в текстурах, помогите выбраться. Ойында қатып қалдым.",
    "report.complaint": "Report that another player insults, attacks, cheats or breaks rules. Жалоба на нарушение другого игрока через репорт.",
    "report.account": "Account access, account theft, missing property or suspected hack. Проблема с аккаунтом или пропажа имущества. Аккаунтқа кіре алмаймын.",
    "report.payment": "A real money payment or donation did not arrive, billing or refund issue. Платёж и донат не пришёл. Төлем келмеді. To‘lov kelmadi.",
    "report.offtopic": "Greeting, empty message or unrelated conversation with no clear request. Приветствие или сообщение без понятной просьбы.",
}


class LocalIntentClassifier:
    def __init__(self, encoder):
        self.encoder = encoder
        self.codes = list(PROTOTYPES)
        self.vectors = encoder.encode(list(PROTOTYPES.values()), "passage: ")

    def refine(self, analysis: Analysis, kind: str) -> Analysis:
        if analysis.category not in {Category.other, Category.offtopic}:
            return analysis
        query = self.encoder.encode([analysis.text], "query: ")[0]
        scores = self.vectors @ query
        eligible = [i for i, code in enumerate(self.codes) if code.startswith(kind + ".")]
        ordered = sorted(eligible, key=lambda i: float(scores[i]), reverse=True)
        best, second = ordered[:2]
        margin = float(scores[best] - scores[second])
        # Conservative abstention: these are deployment defaults, not calibrated thresholds.
        if float(scores[best]) < 0.76 or margin < 0.035:
            return analysis
        category = Category(self.codes[best])
        sensitive = list(analysis.sensitive)
        priority = analysis.priority
        if category in {Category.account, Category.payment, Category.admin}:
            sensitive.append(category.value)
        if category == Category.payment:
            priority = "p0"
        elif category in {Category.cheat, Category.scam, Category.rmt_ads} and priority != "p0":
            priority = "p1"
        elif category in {Category.question, Category.offtopic} and priority != "p0":
            priority = "p3"
        elif kind == "report" and category in {Category.help, Category.complaint, Category.account} and priority not in {"p0", "p1"}:
            priority = "p2"
        return replace(analysis, category=category, priority=priority, sensitive=list(dict.fromkeys(sensitive)),
                       confidence=min(analysis.language_confidence, 0.60))
