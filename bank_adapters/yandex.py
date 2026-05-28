from __future__ import annotations

import re

from .models import apply_budget, canonical_operation, mark_internal, mark_review, match_any, parse_date, parse_money


def parse_yandex_wallet_eds(text: str, metadata: dict) -> list[dict]:
    return _parse_yandex_lines(text, metadata, "yandex_wallet_eds")


def parse_yandex_credit_contract(text: str, metadata: dict) -> list[dict]:
    return _parse_yandex_lines(text, metadata, "yandex_credit_contract")


def _parse_yandex_lines(text: str, metadata: dict, document_type: str) -> list[dict]:
    operations = []
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in lines:
        if not any(marker in line.casefold() for marker in ["yandex", "яндекс", "сбп", "оплата", "погашение", "перевод"]):
            continue
        amount = _find_amount(line) or 0.0
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type=document_type,
            bank="Яндекс Банк",
            account_type="loan_account" if document_type == "yandex_credit_contract" else "wallet",
            account_role=metadata.get("account_role", document_type),
            operation_datetime=parse_date(date_match.group(1), date_match.group(2)) if date_match else parse_date("01.01.1970"),
            description=line,
            bank_amount=amount,
        )
        if document_type == "yandex_credit_contract":
            _classify_yandex_credit(op)
        else:
            _classify_yandex_wallet(op)
        operations.append(op)
    return operations


def _find_amount(text: str) -> float | None:
    matches = re.findall(r"[+-]?\d[\d\s\u00a0]*[,.]\d{2}", text or "")
    return parse_money(matches[-1]) if matches else None


def _classify_yandex_wallet(operation: dict) -> None:
    text = operation.get("description", "")
    if match_any(text, ("Входящий перевод СБП", "Исходящий перевод СБП")):
        mark_internal(operation, "yandex_wallet_topup")
        return
    if match_any(text, ("YANDEX.TAXI", "YANDEX*4121*TAXI", "PAW*Yandex Go")):
        apply_budget(operation, "Личный расход", "Такси", "abs", 0.9, "yandex_merchant", True, True, False)
    elif match_any(text, ("YANDEX*5411*LAVKA", "YANDEX LAVKA")):
        apply_budget(operation, "Личный расход", "Продукты", "abs", 0.9, "yandex_merchant", True, True, False)
    elif match_any(text, ("YANDEX*5814*EDA",)):
        apply_budget(operation, "Личный расход", "Кафе и доставка", "abs", 0.9, "yandex_merchant", True, True, False)
    elif match_any(text, ("YANDEX PLUS", "YANDEX*5815*PLUS")):
        apply_budget(operation, "Личный расход", "Связь и подписки", "abs", 0.9, "yandex_merchant", True, True, False)
    elif match_any(text, ("Yandex Split", "YANDEX*5399*Split")):
        mark_review(operation, "yandex_split_review", 0.5)


def _classify_yandex_credit(operation: dict) -> None:
    text = operation.get("description", "")
    if match_any(text, ("Оплата товаров и услуг", "Оплата СБП QR")):
        apply_budget(operation, "credit_purchase", "Прочее / проверить", "abs", 0.75, "yandex_credit_purchase", True, True, True)
    elif "Погашение основного долга" in text:
        mark_internal(operation, "yandex_debt_repayment")
        operation["operation_type"] = "debt_repayment"
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
    elif "Отмена по операции" in text:
        apply_budget(operation, "refund", "Прочее / проверить", "-abs", 0.7, "yandex_refund", True, False, True)
