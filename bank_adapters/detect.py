from __future__ import annotations

import json
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "document_type_rules.json"


def detect_document_type(text: str) -> dict:
    folded = (text or "").casefold()
    rules = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else []
    best: dict | None = None
    best_score = 0.0
    for rule in rules:
        contains_all = [item.casefold() for item in rule.get("contains_all", [])]
        contains_any = [item.casefold() for item in rule.get("contains_any", [])]
        all_ok = all(item in folded for item in contains_all) if contains_all else True
        any_ok = any(item in folded for item in contains_any) if contains_any else True
        if not all_ok or not any_ok:
            continue
        score = float(rule.get("confidence") or (0.95 if contains_all else 0.75))
        if contains_all:
            score += min(0.04, 0.01 * len(contains_all))
        if score > best_score:
            best = rule
            best_score = score
    if best:
        result = {
            "document_type": best.get("document_type", "unknown_document"),
            "bank": best.get("bank", "Неизвестный банк"),
            "account_type": best.get("account_type", "unknown"),
            "account_role": best.get("account_role", best.get("account_type", "unknown")),
            "confidence": min(1.0, best_score),
            "reason": best.get("reason") or "matched document_type_rules",
        }
        if result["document_type"] == "tbank_statement":
            result.update(_detect_tbank_role(folded))
        return result
    return {
        "document_type": "unknown_document",
        "bank": "Неизвестный банк",
        "account_type": "unknown",
        "account_role": "unknown",
        "confidence": 0.0,
        "reason": "no document_type_rules matched",
    }


def _detect_tbank_role(folded_text: str) -> dict:
    spending = folded_text.count("оплата в ")
    system = sum(folded_text.count(marker) for marker in ["кубыш", "внутренний перевод на договор", "пополнение. индивидуальный предприниматель"])
    if system >= 2 and system >= spending:
        return {"document_type": "tbank_main_contract", "account_role": "tbank_main_contract"}
    if spending >= 2:
        return {"document_type": "tbank_card_statement", "account_role": "tbank_card_spending"}
    return {"account_role": "unknown"}
