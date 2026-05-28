from __future__ import annotations

import re
import uuid
from typing import Any

from storage import CONFIG_DIR, default_profile_template, load_json, normalize_description


REVIEW_TYPE = "Проверить"
REVIEW_CATEGORY = "Прочее / проверить"
INTERNAL_TRANSFER_WORDS = (
    "пополнение кубышки",
    "перевод средств из кубышки",
    "sberbank onl@in karta-vklad",
    "sberbank onl@in vklad-karta",
    "внутренний перевод на договор",
    "внутрибанковский перевод с договора",
    "karta-vklad",
    "vklad-karta",
)
SALARY_WORDS = ("заработная плата", "аванс по заработной плате")
SOCIAL_WORDS = ("социальные выплаты",)
TRANSFER_WORDS = ("перевод", "перевод сбп", "перевод с карты", "перевод на карту", "внешний перевод")
TRAILING_LOCATION_WORDS = {
    "MOSCOW",
    "RUS",
    "RU",
    "SANKT-PETERBU",
    "SAINT-PETERSBURG",
    "SPB",
    "BARNAUL",
    "ALTAI",
}


def normalize(text: str) -> str:
    return (text or "").casefold()


def normalized_direction(value: str | None, amount: float | None = None) -> str:
    if value in {"income", "incoming"}:
        return "income"
    if value in {"expense", "outgoing"}:
        return "expense"
    return "income" if (amount or 0) >= 0 else "expense"


def operation_direction(amount: float) -> str:
    return "income" if amount >= 0 else "expense"


def extract_person_anchor(description: str) -> str:
    text = description or ""
    patterns = [
        r"Перевод от\s+(.+?)(?:\.\s*Операция|\s+Операция|$)",
        r"Перевод для\s+(.+?)(?:\.\s*Операция|\s+Операция|$)",
        r"Внешний перевод по номеру телефона\s+(\+?\d[\d\s().-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return mask_phone(match.group(1).strip())
    return ""


def mask_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        return f"+{digits[:1]}***{digits[-4:]}"
    return text


def extract_merchant_anchor(description: str, bank: str = "", raw_category: str = "") -> str:
    text = " ".join((description or "").strip().split())
    if not text:
        return ""
    lower = normalize(text)
    if "пополнение кубышки" in lower or "перевод средств из кубышки" in lower:
        return "Кубышка"
    if lower.startswith("оплата в "):
        merchant = re.sub(r"^Оплата в\s+", "", text, flags=re.IGNORECASE)
        return trim_merchant_location(merchant)
    if re.search(r"\bперевод\b", lower):
        return ""
    before_operation = re.split(r"\.\s*Операция\b|\s+Операция по\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return trim_merchant_location(before_operation)


def trim_merchant_location(text: str) -> str:
    merchant = text.strip(" .,-")
    if not merchant:
        return ""
    star_match = re.match(r"^([A-ZА-ЯЁ]+[*]\d{3,5}[*][A-ZА-ЯЁ0-9_-]+)", merchant, flags=re.IGNORECASE)
    if star_match:
        return star_match.group(1)
    words = merchant.split()
    while len(words) > 1 and words[-1].upper() in TRAILING_LOCATION_WORDS:
        words.pop()
    return " ".join(words).strip(" .,-")


def enrich_operation(operation: dict[str, Any]) -> dict[str, Any]:
    bank_amount = float(operation.get("bank_amount") or 0)
    description = operation.get("description") or operation.get("raw_description") or ""
    operation.setdefault("raw_description", description)
    operation["description"] = description
    operation["normalized_description"] = operation.get("normalized_description") or normalize_description(description)
    operation["direction"] = normalized_direction(operation.get("direction"), bank_amount)
    operation["merchant_anchor"] = operation.get("merchant_anchor") or extract_merchant_anchor(
        description,
        operation.get("bank", ""),
        operation.get("raw_category", ""),
    )
    operation["person_anchor"] = operation.get("person_anchor") or extract_person_anchor(description)
    operation.setdefault("confidence", 0.0)
    operation.setdefault("classification_source", "")
    return operation


def mode_amount(bank_amount: float, mode: str | None) -> float:
    if mode == "0":
        return 0.0
    if mode == "-abs":
        return -abs(bank_amount)
    if mode in {"abs", "bank_abs"}:
        return abs(bank_amount)
    return abs(bank_amount) if bank_amount < 0 else bank_amount


def searchable_text(operation: dict[str, Any]) -> str:
    return normalize(
        " ".join(
            str(operation.get(key) or "")
            for key in ["description", "raw_description", "normalized_description", "merchant_anchor", "person_anchor"]
        )
    )


def rule_matches(operation: dict[str, Any], rule: dict[str, Any]) -> bool:
    if rule.get("enabled") is False:
        return False
    text = searchable_text(operation)
    amount = float(operation.get("bank_amount") or 0)
    operation_direction_value = normalized_direction(operation.get("direction"), amount)
    if rule.get("bank") and normalize(rule["bank"]) != normalize(operation.get("bank", "")):
        return False
    if rule.get("direction") and normalized_direction(rule["direction"]) != operation_direction_value:
        return False
    if rule.get("merchant_anchor") and normalize(rule["merchant_anchor"]) != normalize(operation.get("merchant_anchor", "")):
        return False
    if rule.get("person_anchor") and normalize(rule["person_anchor"]) != normalize(operation.get("person_anchor", "")):
        return False
    if rule.get("amount_min") is not None and abs(amount) < float(rule["amount_min"]):
        return False
    if rule.get("amount_max") is not None and abs(amount) > float(rule["amount_max"]):
        return False
    contains_any = [normalize(item) for item in rule.get("contains_any", []) if item]
    if contains_any and not any(item in text for item in contains_any):
        return False
    contains_all = [normalize(item) for item in rule.get("contains_all", []) if item]
    if contains_all and not all(item in text for item in contains_all):
        return False
    return True


def apply_rule(operation: dict[str, Any], rule: dict[str, Any], source: str = "user_rule") -> dict[str, Any]:
    bank_amount = float(operation.get("bank_amount") or 0)
    return apply_classification(
        operation,
        operation_type=rule.get("operation_type") or rule.get("type") or REVIEW_TYPE,
        category=rule.get("budget_category") or rule.get("category") or "",
        personal_amount=mode_amount(bank_amount, rule.get("personal_amount_mode")),
        confidence=float(rule.get("confidence", 0.95)),
        source=rule.get("id") or source,
        rule_id=rule.get("id", ""),
        force_review=rule.get("needs_review"),
    )


def apply_classification(
    operation: dict[str, Any],
    operation_type: str,
    category: str,
    personal_amount: float,
    confidence: float,
    source: str,
    rule_id: str = "",
    force_review: bool | None = None,
) -> dict[str, Any]:
    if confidence < 0.5:
        operation_type = REVIEW_TYPE
        category = REVIEW_CATEGORY
        personal_amount = 0.0
    operation["operation_type"] = operation_type
    operation["budget_category"] = category or REVIEW_CATEGORY
    operation["personal_amount"] = float(personal_amount)
    operation["confidence"] = float(confidence)
    operation["classification_source"] = source
    operation["rule_id"] = rule_id
    operation["needs_review"] = force_review if force_review is not None else confidence < 0.85 or operation_type == REVIEW_TYPE
    return operation


def mark_review(operation: dict[str, Any], confidence: float = 0.2, source: str = "review_fallback") -> dict[str, Any]:
    return apply_classification(operation, REVIEW_TYPE, REVIEW_CATEGORY, 0.0, confidence, source, force_review=True)


def global_merchant_rules() -> list[dict[str, Any]]:
    rules = load_json(CONFIG_DIR / "global_merchant_rules.json", [])
    for index, rule in enumerate(rules):
        rule.setdefault("id", f"global_merchant_{index}")
        rule.setdefault("direction", "expense")
        rule.setdefault("confidence", 0.9)
    return rules


def suggest_category_for_operation(operation: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    for rule in profile.get("merchant_rules", []) or []:
        if rule.get("enabled", True) and rule_matches(operation, rule):
            return {
                "suggested_category": rule.get("budget_category") or rule.get("plan_category") or REVIEW_CATEGORY,
                "confidence": rule.get("confidence", 0.95),
                "source": "personal_rule",
                "reason": "Совпало личное правило профиля",
            }
    text = searchable_text(operation)
    for rule in global_merchant_rules():
        patterns = rule.get("patterns") or rule.get("contains_any") or []
        if any(normalize(pattern) in text for pattern in patterns):
            return {
                "suggested_category": rule.get("category") or rule.get("budget_category") or REVIEW_CATEGORY,
                "confidence": rule.get("confidence", 0.9),
                "source": "global_merchant_rule",
                "reason": "Совпало правило глобального справочника",
            }
    return {
        "suggested_category": REVIEW_CATEGORY,
        "confidence": 0.2,
        "source": "fallback",
        "reason": "Нет подходящего правила",
    }


def bank_category_map() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "bank_category_map.json", {})


def classify_internal_transfer(operation: dict[str, Any]) -> dict[str, Any] | None:
    text = searchable_text(operation)
    if any(word in text for word in INTERNAL_TRANSFER_WORDS):
        return apply_classification(
            operation,
            "Внутренний перевод",
            "Не учитывать",
            0.0,
            0.9,
            "system_internal_transfer",
        )
    return None


def classify_income_system(operation: dict[str, Any]) -> dict[str, Any] | None:
    if operation.get("direction") != "income":
        return None
    text = searchable_text(operation)
    if any(word in text for word in SALARY_WORDS):
        return apply_classification(
            operation,
            "Личный доход",
            "Зарплата / аванс",
            abs(float(operation.get("bank_amount") or 0)),
            0.95,
            "system_salary",
        )
    if any(word in text for word in SOCIAL_WORDS):
        return apply_classification(
            operation,
            "Личный доход",
            "Социальные выплаты",
            abs(float(operation.get("bank_amount") or 0)),
            0.8,
            "system_social_income",
            force_review=True,
        )
    if normalize(operation.get("bank", "")) in {"т-банк", "tbank", "t-bank", "тинькофф"} and "индивидуальный предприниматель" in text:
        return mark_review(operation, 0.5, "system_tbank_ip_income_review")
    return None


def classify_transfers_to_people(operation: dict[str, Any]) -> dict[str, Any] | None:
    raw_category = normalize(operation.get("raw_category", ""))
    text = searchable_text(operation)
    if operation.get("person_anchor") or any(word in raw_category for word in TRANSFER_WORDS) or "внешний перевод" in text:
        return mark_review(operation, 0.2, "system_transfer_review")
    return None


def classify_by_bank_category(operation: dict[str, Any]) -> dict[str, Any] | None:
    bank = operation.get("bank", "")
    raw_category = operation.get("raw_category", "")
    if not bank or not raw_category:
        return None
    bank_map = bank_category_map().get(bank, {})
    rule = bank_map.get(raw_category)
    if not rule:
        return None
    return apply_classification(
        operation,
        rule.get("operation_type") or rule.get("type") or REVIEW_TYPE,
        rule.get("budget_category") or rule.get("category") or REVIEW_CATEGORY,
        mode_amount(float(operation.get("bank_amount") or 0), rule.get("personal_amount_mode", "abs")),
        float(rule.get("confidence", 0.5)),
        f"bank_category:{bank}:{raw_category}",
    )


def classify_operation(operation: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    operation = enrich_operation(operation)
    for rule in list(profile.get("rules", [])):
        if rule_matches(operation, rule):
            return apply_rule(operation, rule, "profile_rule")
    for rule in list(profile.get("person_rules", [])):
        if rule_matches(operation, rule):
            return apply_rule(operation, rule, "person_rule")
    for rule in list(profile.get("merchant_rules", [])):
        if rule_matches(operation, rule):
            return apply_rule(operation, rule, "merchant_rule")
    source = str(operation.get("classification_source") or "")
    if (
        source.startswith(("adapter_", "sber_", "tbank_", "yandex_", "wb_", "alfa_", "halva_"))
        and operation.get("operation_type") != REVIEW_TYPE
        and float(operation.get("confidence") or 0) >= 0.7
    ):
        return operation
    for rule in global_merchant_rules():
        if rule_matches(operation, rule):
            return apply_rule(operation, rule, "global_merchant_rule")

    for classifier in [
        classify_internal_transfer,
        classify_income_system,
        classify_transfers_to_people,
        classify_by_bank_category,
    ]:
        result = classifier(operation)
        if result:
            return result

    for rule in default_profile_template().get("base_rules", []):
        if rule_matches(operation, rule):
            return apply_rule(operation, rule, "base_rule")
    return mark_review(operation)


def classify_operations(operations: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [classify_operation(operation, profile) for operation in operations]


def build_rule_from_operation(
    operation: dict[str, Any],
    operation_type: str,
    category: str,
    personal_amount: float,
) -> dict[str, Any]:
    operation = enrich_operation(operation)
    amount = float(operation.get("bank_amount") or 0)
    if personal_amount == 0:
        mode = "0"
    elif personal_amount < 0:
        mode = "-abs"
    else:
        mode = "abs" if amount < 0 else "bank_abs"
    rule: dict[str, Any] = {
        "id": f"user_{uuid.uuid4().hex[:10]}",
        "enabled": True,
        "direction": operation.get("direction"),
        "bank": operation.get("bank"),
        "operation_type": operation_type,
        "budget_category": category,
        "personal_amount_mode": mode,
        "confidence": 0.95,
    }
    if operation.get("person_anchor"):
        rule["person_anchor"] = operation["person_anchor"]
    elif operation.get("merchant_anchor"):
        rule["merchant_anchor"] = operation["merchant_anchor"]
        rule["contains_any"] = [operation["merchant_anchor"]]
    else:
        phrase = " ".join([word for word in normalize(operation.get("description", "")).split() if len(word) >= 4][:3])
        rule["contains_all"] = [phrase] if phrase else []
    return rule
