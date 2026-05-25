from __future__ import annotations

import re

from .models import apply_budget, canonical_operation, mark_internal, mark_review, match_any, parse_date, parse_money


MONEY_RE = re.compile(r"^[+-]?\d[\d\s\u00a0]*,\d{2}$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
ONE_LINE_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2})\s+(?P<category>.+?)\s+(?P<amount>[+]?\d[\d\s\u00a0]*,\d{2})\s+(?P<balance>[+]?\d[\d\s\u00a0]*,\d{2})$"
)


def parse_sber_debit_account(text: str, metadata: dict) -> list[dict]:
    return _parse_sber_blocks(text, metadata, "sber_debit_account")


def parse_sber_credit_card(text: str, metadata: dict) -> list[dict]:
    metadata.update(extract_sber_credit_metadata(text))
    return _parse_sber_blocks(text, metadata, "sber_credit_card")


def extract_sber_credit_metadata(text: str) -> dict:
    result = {}
    patterns = {
        "credit_limit": r"Кредитный лимит\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*,\d{2}|\d[\d\s\u00a0]+)",
        "debt_end": r"Общая задолженность\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*,\d{2}|\d[\d\s\u00a0]+)",
        "grace_period": r"Льготный период\s*[:\-]?\s*([^\n]+)",
        "interest_rate": r"Процентная ставка\s*[:\-]?\s*([^\n]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        money = parse_money(value)
        result[key] = money if money is not None and key in {"credit_limit", "debt_end"} else value
    return result


def _parse_sber_blocks(text: str, metadata: dict, document_type: str) -> list[dict]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    operations: list[dict] = []
    index = 0
    while index < len(lines):
        parsed = _block_at(lines, index)
        if not parsed:
            parsed = _one_line_at(lines, index)
        if not parsed:
            index += 1
            continue
        date_text, time_text, category, amount_text, balance_text, next_index = parsed
        amount = parse_money(amount_text)
        if amount is None:
            index = next_index
            continue
        bank_amount = abs(amount) if amount_text.strip().startswith("+") else -abs(amount)
        processing_date = date_text
        auth_code = ""
        description_start = next_index
        if description_start < len(lines) and DATE_RE.match(lines[description_start]):
            processing_date = lines[description_start]
            description_start += 1
        if description_start < len(lines) and re.fullmatch(r"\d{4,8}", lines[description_start]):
            auth_code = lines[description_start]
            description_start += 1
        description_lines = []
        cursor = description_start
        while cursor < len(lines) and not _block_at(lines, cursor) and not _one_line_at(lines, cursor):
            line = lines[cursor]
            if not DATE_RE.match(line) and not TIME_RE.match(line) and not re.fullmatch(r"\d{4,8}", line):
                description_lines.append(line)
            cursor += 1
        description = " ".join(description_lines).strip() or category
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type=document_type,
            bank="Сбер",
            account_id=metadata.get("account_id", ""),
            account_type=metadata.get("account_type", "credit_card" if document_type == "sber_credit_card" else "debit_account"),
            account_role=metadata.get("account_role", metadata.get("account_type", "")),
            owner_name=metadata.get("owner_name", ""),
            operation_datetime=parse_date(date_text, time_text),
            processing_date=parse_date(processing_date)[:10],
            raw_category=category,
            description=description,
            bank_amount=bank_amount,
            auth_code=auth_code,
            raw_block="\n".join(lines[index:cursor]),
            operation_date=date_text,
            operation_time=time_text,
            amount_text=amount_text,
            balance_text=balance_text,
        )
        _classify_sber(op, document_type)
        operations.append(op)
        index = cursor
    return operations


def _block_at(lines: list[str], index: int) -> tuple[str, str, str, str, str, int] | None:
    if index + 4 >= len(lines):
        return None
    if DATE_RE.match(lines[index]) and TIME_RE.match(lines[index + 1]) and MONEY_RE.match(lines[index + 3]) and MONEY_RE.match(lines[index + 4]):
        return lines[index], lines[index + 1], lines[index + 2], lines[index + 3], lines[index + 4], index + 5
    return None


def _one_line_at(lines: list[str], index: int) -> tuple[str, str, str, str, str, int] | None:
    match = ONE_LINE_RE.match(lines[index])
    if not match:
        return None
    return match.group("date"), match.group("time"), match.group("category"), match.group("amount"), match.group("balance"), index + 1


def _classify_sber(operation: dict, document_type: str) -> None:
    text = f"{operation.get('raw_category', '')} {operation.get('description', '')}"
    category = operation.get("raw_category", "")
    if match_any(text, ("SBERBANK ONL@IN KARTA-VKLAD", "SBERBANK ONL@IN VKLAD-KARTA", "MAPP_SBERBANK_ONL@IN_PAY")):
        mark_internal(operation, "sber_system_internal_transfer")
        return
    if "Перевод" in category:
        mark_review(operation, "sber_transfer_review", 0.2)
        return
    if category == "Выдача наличных":
        apply_budget(operation, "cash_withdrawal", "Наличные / проверить", "0", 0.7, "sber_cash_withdrawal", False, False, True)
        return
    if operation.get("direction") == "income" and match_any(text, ("Заработная плата", "Аванс по заработной плате", "Премия, иные поощрительные выплаты")):
        apply_budget(operation, "Личный доход", "Зарплата / аванс / премия", "abs", 0.95, "sber_salary", True, False, False)
        return
    if document_type == "sber_credit_card" and operation.get("direction") == "income":
        apply_budget(operation, "debt_repayment", "Не учитывать", "0", 0.9, "sber_credit_repayment", False, False, False)
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
        operation["debt_type"] = "credit_card_repayment"
        return
    if match_any(text, ("погашение процентов", "проценты", "комиссия")):
        apply_budget(operation, "credit_interest", "Кредиты / проценты / комиссии", "abs", 0.9, "sber_credit_interest", True, False, False)
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
        return
    category_map = {
        "Супермаркеты": "Продукты / супермаркеты",
        "Рестораны и кафе": "Кафе / доставка / рестораны",
        "Транспорт": "Транспорт",
        "Автомобиль": "Авто / каршеринг",
        "Здоровье и красота": "Здоровье / аптеки",
        "Одежда и аксессуары": "Одежда",
        "Отдых и развлечения": "Развлечения",
        "Коммунальные платежи, связь, интернет.": "Связь / интернет / подписки",
    }
    if operation.get("direction") == "expense" and category in category_map:
        apply_budget(operation, "Личный расход", category_map[category], "abs", 0.85, "sber_bank_category", True, True, False)
