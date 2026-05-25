from __future__ import annotations

import json
import re
from pathlib import Path

from .models import apply_budget, canonical_operation, mark_internal, parse_date, parse_money


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def parse_sovcombank_halva(text: str, metadata: dict) -> list[dict]:
    metadata.update(extract_sovcombank_metadata(text))
    operations = []
    for line in [line.strip() for line in (text or "").splitlines() if line.strip()]:
        folded = line.casefold()
        if "предоставление кредита заемщику" in folded:
            continue
        if not any(marker in folded for marker in ["платеж авторизация", "оплата по сбп", "покупка по qr", "погашение кредита", "зачисление перевода", "комиссия"]):
            continue
        amount = _find_amount(line) or 0.0
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        mcc_match = re.search(r"\bMCC\s*(\d{4})\b", line, flags=re.IGNORECASE)
        mcc = mcc_match.group(1) if mcc_match else ""
        op = canonical_operation(
            profile_id=metadata.get("profile_id", ""),
            source_file=metadata.get("source_file", ""),
            document_type="sovcombank_halva",
            bank="Совкомбанк",
            account_type="installment_card",
            account_role="sovcombank_halva",
            operation_datetime=parse_date(date_match.group(1), date_match.group(2)) if date_match else parse_date("01.01.1970"),
            description=line,
            raw_category=f"MCC {mcc}" if mcc else "",
            bank_amount=-abs(amount) if amount else amount,
            mcc=mcc,
        )
        _classify_halva(op)
        operations.append(op)
    return operations


def extract_sovcombank_metadata(text: str) -> dict:
    match = re.search(r"лимит кредитования\s*[:\-]?\s*([+\-]?\d[\d\s\u00a0]*[,.]\d{2})", text or "", flags=re.IGNORECASE)
    return {"credit_limit": parse_money(match.group(1)) or 0.0} if match else {}


def _find_amount(text: str) -> float | None:
    matches = re.findall(r"[+-]?\d[\d\s\u00a0]*[,.]\d{2}", text or "")
    return parse_money(matches[-1]) if matches else None


def _classify_halva(operation: dict) -> None:
    text = operation.get("description", "")
    folded = text.casefold()
    if "погашение кредита" in folded or "зачисление перевода" in folded:
        mark_internal(operation, "halva_debt_repayment")
        operation["operation_type"] = "debt_repayment"
        operation["debt_amount"] = abs(float(operation.get("bank_amount") or 0))
        return
    if "комиссия" in folded:
        apply_budget(operation, "Личный расход", "Кредиты / проценты / комиссии", "abs", 0.9, "halva_fee", True, False, False)
        return
    category = _mcc_category(operation.get("mcc", "")) or "Прочее / проверить"
    apply_budget(operation, "Личный расход", category, "abs", 0.9 if category != "Прочее / проверить" else 0.5, "halva_purchase", True, True, category == "Прочее / проверить")


def _mcc_category(mcc: str) -> str:
    path = CONFIG_DIR / "mcc_map.json"
    if not path.exists():
        return ""
    return json.loads(path.read_text(encoding="utf-8")).get(str(mcc), "")
