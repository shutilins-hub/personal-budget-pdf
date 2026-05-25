from __future__ import annotations

import re

from .models import apply_budget, canonical_operation, mark_internal, parse_date, parse_money


def parse_wb_wallet(text: str, metadata: dict) -> list[dict]:
    operations = []
    for line in [line.strip() for line in (text or "").splitlines() if line.strip()]:
        if "Зачисление перевода СБП" not in line and "Оплата на Wildberries" not in line:
            continue
        amount = _find_amount(line) or 0.0
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type="wb_wallet",
            bank="ВБ Банк",
            account_type="marketplace_wallet",
            account_role="wb_wallet",
            operation_datetime=parse_date(date_match.group(1), date_match.group(2)) if date_match else parse_date("01.01.1970"),
            description=line,
            bank_amount=amount,
        )
        if "Зачисление перевода СБП" in line:
            mark_internal(op, "wb_wallet_topup")
            op["operation_type"] = "wallet_topup"
        else:
            apply_budget(op, "Личный расход", "Маркетплейсы", "abs", 0.95, "wb_purchase", True, True, False)
        operations.append(op)
    return operations


def _find_amount(text: str) -> float | None:
    matches = re.findall(r"[+-]?\d[\d\s\u00a0]*[,.]\d{2}", text or "")
    return parse_money(matches[-1]) if matches else None
