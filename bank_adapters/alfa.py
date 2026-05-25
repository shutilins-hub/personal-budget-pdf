from __future__ import annotations

import re

from .models import apply_budget, canonical_operation, mark_internal, mark_review, match_any, parse_date, parse_money


def parse_alfa_current_account(text: str, metadata: dict) -> list[dict]:
    return _parse_alfa(text, metadata, "alfa_current_account", "debit_account")


def parse_alfa_credit_card(text: str, metadata: dict) -> list[dict]:
    metadata.update(extract_alfa_credit_metadata(text))
    return _parse_alfa(text, metadata, "alfa_credit_card", "credit_card")


def extract_alfa_credit_metadata(text: str) -> dict:
    result = {}
    patterns = {
        "credit_limit": r"плат[её]жный лимит\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*[,.]\d{2})",
        "debt_end": r"общая задолженность к погашению\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*[,.]\d{2})",
        "current_balance": r"текущий баланс\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*[,.]\d{2})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            result[key] = parse_money(match.group(1)) or 0.0
    return result


def _parse_alfa(text: str, metadata: dict, document_type: str, account_type: str) -> list[dict]:
    operations = []
    for line in [line.strip() for line in (text or "").splitlines() if line.strip()]:
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        amount = _find_amount(line)
        if not date_match or amount is None:
            continue
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type=document_type,
            bank="Альфа-Банк",
            account_type=account_type,
            account_role=document_type,
            operation_datetime=parse_date(date_match.group(1), date_match.group(2)),
            description=line,
            bank_amount=amount,
        )
        _classify_alfa(op, document_type)
        operations.append(op)
    return operations


def _find_amount(text: str) -> float | None:
    matches = re.findall(r"[+-]?\d[\d\s\u00a0]*[,.]\d{2}", text or "")
    return parse_money(matches[-1]) if matches else None


def _classify_alfa(operation: dict, document_type: str) -> None:
    text = operation.get("description", "")
    if "Внутрибанковский перевод между счетами" in text:
        mark_internal(operation, "alfa_internal_transfer")
    elif match_any(text, ("Перевод через СБП", "Перевод денежных средств")):
        mark_review(operation, "alfa_transfer_review", 0.2)
    elif document_type == "alfa_credit_card" and "Предоставление транша" in text:
        mark_internal(operation, "alfa_credit_draw")
        operation["operation_type"] = "credit_draw"
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
    elif document_type == "alfa_credit_card" and match_any(text, ("Погашение процентов",)):
        apply_budget(operation, "credit_interest", "Кредиты / проценты / комиссии", "abs", 0.9, "alfa_credit_interest", True, False, False)
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
    elif document_type == "alfa_credit_card" and match_any(text, ("Погашение ОД", "Погашение основного долга")):
        mark_internal(operation, "alfa_debt_repayment")
        operation["operation_type"] = "debt_repayment"
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
    elif "Комиссия" in text:
        apply_budget(operation, "Личный расход", "Кредиты / проценты / комиссии", "abs", 0.9, "alfa_fee", True, False, False)
    elif "Платеж" in text or "Платёж" in text:
        apply_budget(operation, "Личный расход", "Прочее / проверить", "abs", 0.5, "alfa_purchase_review", True, True, True)
