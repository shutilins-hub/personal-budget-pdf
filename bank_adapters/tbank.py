from __future__ import annotations

import re

from .models import apply_budget, canonical_operation, mark_internal, mark_review, match_any, parse_date, parse_money


def parse_tbank_statement(text: str, metadata: dict) -> list[dict]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    metadata["account_role"] = metadata.get("account_role") or _detect_role(text)
    operations = []
    for index, line in enumerate(lines):
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        if not date_match:
            continue
        amount = _find_amount(line)
        description = line
        if amount is None and index + 1 < len(lines):
            amount = _find_amount(lines[index + 1])
            description = f"{line} {lines[index + 1]}"
        if amount is None:
            continue
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type=metadata.get("document_type", "tbank_statement"),
            bank="Т-Банк",
            account_type=metadata.get("account_type", "unknown"),
            account_role=metadata.get("account_role", _detect_role(text)),
            operation_datetime=parse_date(date_match.group(1), date_match.group(2)),
            raw_category="",
            description=description,
            bank_amount=amount,
        )
        _classify_tbank(op)
        operations.append(op)
    if not operations:
        for index, line in enumerate(lines):
            if any(marker in line for marker in ["Оплата в ", "Пополнение Кубышки", "Внутренний перевод", "Внешний перевод", "Пополнение."]):
                amount = _find_amount(" ".join(lines[index:index + 4])) or 0.0
                op = canonical_operation(
                    profile_id=metadata.get("profile_id", ""),
                    source_file=metadata.get("source_file", ""),
                    document_type=metadata.get("document_type", "tbank_statement"),
                    bank="Т-Банк",
                    account_type=metadata.get("account_type", "unknown"),
                    account_role=metadata.get("account_role", _detect_role(text)),
                    operation_datetime=parse_date("01.01.1970"),
                    description=line,
                    bank_amount=amount,
                )
                _classify_tbank(op)
                operations.append(op)
    return operations


def _detect_role(text: str) -> str:
    folded = (text or "").casefold()
    spending = folded.count("оплата в ")
    system = sum(folded.count(marker) for marker in ["кубыш", "внутренний перевод на договор", "пополнение. индивидуальный предприниматель"])
    if system >= 2 and system >= spending:
        return "tbank_main_contract"
    if spending >= 2:
        return "tbank_card_spending"
    return "unknown"


def _find_amount(text: str) -> float | None:
    matches = re.findall(r"[+-]?\d[\d\s\u00a0]*[,.]\d{2}|[+-]\d[\d\s\u00a0]+", text or "")
    return parse_money(matches[-1]) if matches else None


def _classify_tbank(operation: dict) -> None:
    text = operation.get("description", "")
    if match_any(text, ("Внутренний перевод на договор", "Внутрибанковский перевод с договора", "Пополнение Кубышки", "Перевод средств из Кубышки")):
        mark_internal(operation, "tbank_internal_transfer")
        operation["merchant_anchor"] = "Кубышка" if "Кубыш" in text else operation.get("merchant_anchor", "")
        return
    if match_any(text, ("Пополнение. ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ", "Пополнение. Система быстрых платежей", "Внешний перевод по номеру телефона", "Внешний перевод по номеру карты")):
        mark_review(operation, "tbank_transfer_review", 0.5 if "ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ" in text else 0.2)
        operation["operation_type"] = "unknown_transfer"
        return
    if "Плата за перевод денежных средств" in text:
        apply_budget(operation, "Личный расход", "Кредиты / проценты / комиссии", "abs", 0.9, "tbank_fee", True, True, False)
        return
    if "Оплата в " in text:
        merchant = operation.get("merchant_anchor", "")
        if match_any(merchant, ("MARIYA-RA", "МАРИЯ-РА", "PYATEROCHKA", "MAGNIT", "LENTA")):
            category = "Продукты"
        elif match_any(merchant, ("TRANSPORT", "METRO")):
            category = "Транспорт"
        else:
            category = "Прочее / проверить"
        apply_budget(operation, "Личный расход", category, "abs", 0.9 if category != "Прочее / проверить" else 0.45, "tbank_purchase", True, True, category == "Прочее / проверить")
