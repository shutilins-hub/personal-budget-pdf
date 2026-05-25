from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from privacy import sanitize_text


def normalize_description(description: str) -> str:
    return " ".join((description or "").casefold().split())


def extract_person_anchor(description: str) -> str:
    text = description or ""
    patterns = [
        r"Перевод от\s+(.+?)(?:\.\s*Операция|\s+Операция|$|,)",
        r"Перевод для\s+(.+?)(?:\.\s*Операция|\s+Операция|$|,)",
        r"Отправитель\s+(.+?)(?:$|,)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return sanitize_text(match.group(1).strip())
    return ""


def extract_merchant_anchor(description: str, bank: str = "", raw_category: str = "") -> str:
    text = " ".join((description or "").strip().split())
    if not text or re.search(r"\bперевод\b", text, flags=re.IGNORECASE):
        return ""
    if text.casefold().startswith("оплата в "):
        text = re.sub(r"^Оплата в\s+", "", text, flags=re.IGNORECASE)
    text = re.split(r"\.\s*Операция\b|\s+Операция по\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    star_match = re.match(r"^([A-ZА-ЯЁ]+[*]\d{3,5}[*][A-ZА-ЯЁ0-9_-]+)", text, flags=re.IGNORECASE)
    if star_match:
        return star_match.group(1)
    words = text.strip(" .,-").split()
    trailing = {"MOSCOW", "RUS", "RU", "BARNAUL", "SPB", "ALTAI"}
    while len(words) > 1 and words[-1].upper() in trailing:
        words.pop()
    return " ".join(words).strip(" .,-")


EXPENSE_REVIEW_CATEGORY = "Прочее / проверить"
INTERNAL_TRANSFER_TYPE = "Внутренний перевод"


def parse_date(date_text: str, time_text: str | None = None) -> str:
    raw = (date_text or "").strip().replace("/", ".")
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            value = datetime.strptime(raw, fmt)
            break
        except ValueError:
            value = None
    if value is None:
        return datetime.now().isoformat(timespec="seconds")
    if time_text:
        parts = [int(part) for part in time_text.split(":")]
        value = value.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) > 2 else 0)
    return value.isoformat(timespec="seconds")


def parse_money(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("\u00a0", " ")
    sign = -1 if text.startswith("-") else 1
    text = text.replace("+", "").replace("-", "")
    text = re.sub(r"[^\d,.\s]", "", text).strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(" ", "").replace(",", ".")
    else:
        text = text.replace(" ", "")
    try:
        return sign * float(text)
    except ValueError:
        return None


def direction_from_amount(amount: float) -> str:
    return "income" if amount >= 0 else "expense"


def normalize_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def extract_phone_anchor(description: str) -> str:
    match = re.search(r"(?:\+7|8)\s*[\d\s().-]{8,}", description or "")
    if not match:
        return ""
    digits = normalize_phone(match.group(0))
    return f"+{digits[:1]}***{digits[-4:]}" if len(digits) >= 10 else ""


def extract_card_last4(description: str) -> str:
    match = re.search(r"(?:\*{2,}|карта|сч[её]т)\s*(\d{4})\b", description or "", flags=re.IGNORECASE)
    return match.group(1) if match else ""


def canonical_operation(
    *,
    profile_id: str = "",
    source_file: str = "",
    document_type: str = "",
    bank: str = "",
    account_id: str = "",
    account_type: str = "unknown",
    account_role: str = "",
    owner_name: str = "",
    operation_datetime: str = "",
    processing_date: str = "",
    raw_category: str = "",
    description: str = "",
    bank_amount: float = 0.0,
    direction: str | None = None,
    operation_type: str = "Проверить",
    budget_category: str = EXPENSE_REVIEW_CATEGORY,
    budget_amount: float = 0.0,
    planning_amount: float = 0.0,
    count_in_budget: bool = False,
    count_in_plan: bool = False,
    count_in_cashflow: bool = True,
    debt_amount: float = 0.0,
    debt_type: str = "",
    confidence: float = 0.2,
    needs_review: bool = True,
    classification_source: str = "adapter_review_fallback",
    rule_id: str = "",
    linked_operation_id: str = "",
    duplicate_extra: str = "",
    **extra: Any,
) -> dict[str, Any]:
    original_description = description or ""
    description = sanitize_text(description)
    raw_description = sanitize_text(extra.pop("raw_description", description))
    amount = float(bank_amount or 0)
    direction = direction or direction_from_amount(amount)
    normalized_description = normalize_description(description)
    auth_code = str(extra.get("auth_code") or "")
    card_last4 = str(extra.get("card_last4") or extract_card_last4(description))
    merchant_anchor = extra.pop("merchant_anchor", "") or extract_merchant_anchor(description, bank, raw_category)
    person_anchor = extra.pop("person_anchor", "") or extract_person_anchor(description)
    phone_anchor = extra.pop("phone_anchor", "") or extract_phone_anchor(original_description)
    duplicate_key = build_duplicate_key(
        profile_id,
        bank,
        account_id,
        operation_datetime,
        amount,
        normalized_description,
        auth_code,
        card_last4,
        duplicate_extra,
    )
    operation = {
        "id": uuid.uuid4().hex,
        "profile_id": profile_id,
        "source_file": source_file,
        "document_type": document_type,
        "bank": bank,
        "account_id": account_id,
        "account_type": account_type,
        "account_role": account_role or account_type,
        "owner_name": owner_name,
        "operation_datetime": operation_datetime or datetime.now().isoformat(timespec="seconds"),
        "processing_date": processing_date or (operation_datetime or datetime.now().isoformat(timespec="seconds"))[:10],
        "raw_category": sanitize_text(raw_category),
        "raw_description": raw_description,
        "description": description,
        "normalized_description": normalized_description,
        "merchant_anchor": merchant_anchor,
        "person_anchor": person_anchor,
        "phone_anchor": phone_anchor,
        "card_last4": card_last4,
        "auth_code": auth_code,
        "bank_amount": amount,
        "direction": direction,
        "cashflow_amount": amount,
        "operation_type": operation_type,
        "budget_category": budget_category,
        "personal_amount": budget_amount,
        "budget_amount": budget_amount,
        "planning_amount": planning_amount,
        "count_in_budget": bool(count_in_budget),
        "count_in_plan": bool(count_in_plan),
        "count_in_cashflow": bool(count_in_cashflow),
        "plan_category": extra.pop("plan_category", budget_category),
        "plan_exclusion_reason": extra.pop("plan_exclusion_reason", ""),
        "debt_amount": debt_amount,
        "debt_type": debt_type,
        "confidence": confidence,
        "needs_review": needs_review,
        "classification_source": classification_source,
        "rule_id": rule_id,
        "linked_operation_id": linked_operation_id,
        "duplicate_key": duplicate_key,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "comment": extra.pop("comment", ""),
    }
    operation.update(extra)
    return operation


def build_duplicate_key(
    profile_id: str,
    bank: str,
    account_id: str,
    operation_datetime: str,
    amount: float,
    normalized_description: str,
    auth_code: str = "",
    card_last4: str = "",
    duplicate_extra: str = "",
) -> str:
    parts = [
        profile_id,
        bank,
        account_id,
        operation_datetime,
        f"{float(amount or 0):.2f}",
        normalized_description,
        auth_code,
        card_last4,
        duplicate_extra,
    ]
    return "|".join(str(part or "") for part in parts)


def apply_budget(
    operation: dict[str, Any],
    operation_type: str,
    category: str,
    mode: str = "abs",
    confidence: float = 0.9,
    source: str = "adapter_rule",
    count_in_budget: bool = True,
    count_in_plan: bool = True,
    needs_review: bool | None = None,
) -> dict[str, Any]:
    amount = abs(float(operation.get("bank_amount") or 0))
    if mode == "0":
        budget_amount = 0.0
    elif mode == "-abs":
        budget_amount = -amount
    elif mode == "signed":
        budget_amount = float(operation.get("bank_amount") or 0)
    else:
        budget_amount = amount
    operation.update(
        operation_type=operation_type,
        budget_category=category,
        personal_amount=budget_amount,
        budget_amount=budget_amount,
        planning_amount=budget_amount if count_in_plan else 0.0,
        count_in_budget=count_in_budget,
        count_in_plan=count_in_plan,
        plan_category=category if count_in_plan else "Не учитывать",
        confidence=confidence,
        needs_review=(confidence < 0.85) if needs_review is None else needs_review,
        classification_source=source,
    )
    return operation


def mark_internal(operation: dict[str, Any], source: str = "adapter_internal_transfer", confidence: float = 0.9, needs_review: bool = False) -> dict[str, Any]:
    return apply_budget(operation, INTERNAL_TRANSFER_TYPE, "Не учитывать", "0", confidence, source, False, False, needs_review)


def mark_review(operation: dict[str, Any], source: str = "adapter_review", confidence: float = 0.2) -> dict[str, Any]:
    operation.update(
        operation_type="Проверить",
        budget_category=EXPENSE_REVIEW_CATEGORY,
        personal_amount=0.0,
        budget_amount=0.0,
        planning_amount=0.0,
        count_in_budget=False,
        count_in_plan=False,
        confidence=confidence,
        needs_review=True,
        classification_source=source,
    )
    return operation


def match_any(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    folded = (text or "").casefold()
    return any(needle.casefold() in folded for needle in needles)


def is_probable_own_transfer(operation: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    identity = profile.get("own_identity") or {}
    description = " ".join(
        str(operation.get(key) or "")
        for key in ["description", "raw_description", "person_anchor", "phone_anchor", "card_last4"]
    ).casefold()
    aliases = [identity.get("full_name", ""), *(identity.get("name_aliases") or [])]
    aliases = [alias.casefold() for alias in aliases if alias]
    phones = [normalize_phone(phone) for phone in identity.get("phones", []) if phone]
    last4s = [str(item) for item in identity.get("account_last4", []) if item]
    name_match = any(alias and alias in description for alias in aliases)
    compact_description_digits = normalize_phone(description)
    phone_match = any(phone and phone in compact_description_digits for phone in phones)
    if not phone_match and operation.get("phone_anchor"):
        phone_match = any(phone[-4:] and phone[-4:] in str(operation.get("phone_anchor")) for phone in phones)
    card_match = any(last4 and last4 in description for last4 in last4s)
    if name_match and (phone_match or card_match or operation.get("linked_operation_id")):
        return {"is_own_transfer": True, "confidence": 0.98, "reason": "name + phone/card/link"}
    if name_match:
        return {"is_own_transfer": True, "confidence": 0.85, "reason": "name only"}
    return {"is_own_transfer": False, "confidence": 0.0, "reason": "no identity match"}


def apply_own_identity(operation: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    result = is_probable_own_transfer(operation, profile)
    if not result["is_own_transfer"]:
        return operation
    exact = result["confidence"] >= 0.95
    return mark_internal(
        operation,
        source="own_identity_exact" if exact else "own_identity_name_only",
        confidence=result["confidence"],
        needs_review=not exact,
    )


def link_internal_transfers(profile_id: str, operations: list[dict[str, Any]] | None = None) -> list[tuple[str, str]]:
    if operations is None:
        from storage import operations_df, update_operation

        df = operations_df(profile_id)
        records = df.to_dict("records")
        persist = True
    else:
        records = operations
        persist = False
        update_operation = None
    pairs: list[tuple[str, str]] = []
    for left in records:
        if left.get("direction") not in {"expense", "outgoing"}:
            continue
        left_dt = _parse_iso(left.get("operation_datetime"))
        left_amount = abs(float(left.get("bank_amount") or 0))
        if not left_dt or not left_amount:
            continue
        for right in records:
            if right.get("direction") not in {"income", "incoming"} or left.get("id") == right.get("id"):
                continue
            right_dt = _parse_iso(right.get("operation_datetime"))
            right_amount = abs(float(right.get("bank_amount") or 0))
            if not right_dt or abs((right_dt - left_dt).days) > 2:
                continue
            if abs(left_amount - right_amount) > max(1.0, left_amount * 0.01):
                continue
            if not _looks_internal_pair(left, right):
                continue
            pairs.append((left["id"], right["id"]))
            if persist and update_operation:
                update_operation(left["id"], {"operation_type": INTERNAL_TRANSFER_TYPE, "budget_amount": 0.0, "planning_amount": 0.0, "personal_amount": 0.0, "linked_operation_id": right["id"], "count_in_budget": False, "count_in_plan": False, "needs_review": False, "classification_source": "linked_internal_transfer"})
                update_operation(right["id"], {"operation_type": INTERNAL_TRANSFER_TYPE, "budget_amount": 0.0, "planning_amount": 0.0, "personal_amount": 0.0, "linked_operation_id": left["id"], "count_in_budget": False, "count_in_plan": False, "needs_review": False, "classification_source": "linked_internal_transfer"})
            break
    return pairs


def _parse_iso(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _looks_internal_pair(left: dict[str, Any], right: dict[str, Any]) -> bool:
    text = f"{left.get('description', '')} {right.get('description', '')}".casefold()
    markers = ("пополнение", "кошел", "эдс", "карта", "сч", "внутрен", "кубыш", "сбербанк", "т-банк", "яндекс", "wildberries", "вб")
    return any(marker in text for marker in markers)
