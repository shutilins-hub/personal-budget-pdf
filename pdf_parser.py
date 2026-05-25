from __future__ import annotations

import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

try:
    import fitz
except ModuleNotFoundError:
    fitz = None

from privacy import sanitize_text


DATE_RE = re.compile(r"(\d{2}[./]\d{2}[./]\d{2,4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?")
AMOUNT_RE = re.compile(r"([+-]?\s?\d[\d\s.,]*)(?:\s?₽|\s?руб\.?|\s?RUB)?")
SBER_MONEY_RE = re.compile(r"^[+]?\d[\d\s\u00A0]*,\d{2}$")
SBER_OPERATION_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<category>.+?)\s+"
    r"(?P<amount>[+]?\d[\d\s\u00A0]*,\d{2})\s+"
    r"(?P<balance>[+]?\d[\d\s\u00A0]*,\d{2})$"
)
AUTH_DESCRIPTION_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+\d{5,8}\b")
SBER_DATE_LINE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
SBER_TIME_LINE_RE = re.compile(r"^\d{2}:\d{2}$")
AUTH_CODE_LINE_RE = re.compile(r"^\d{5,8}$")
EXPORTS_DIR = Path(__file__).resolve().parent / "exports"
SBER_DEBUG_PATH = EXPORTS_DIR / "sber_raw_lines_debug.txt"
SERVICE_LINE_MARKERS = (
    "Выписка по",
    "Страница",
    "Продолжение",
    "Дата формирования",
    "Дата закрытия",
    "Дата открытия",
    "Владелец счёта",
    "Номер счёта",
    "Остаток на",
    "ИТОГО",
    "Пополнение",
    "Списание",
    "ПАО Сбербанк",
    "Для проверки",
    "QR-код",
    "Генеральная лицензия",
    "ДАТА ОПЕРАЦИИ",
    "Дата обработки",
    "и код авторизации",
    "КАТЕГОРИЯ",
    "Описание операции",
    "СУММА В ВАЛЮТЕ СЧЁТА",
    "Сумма в валюте",
    "операции²",
    "ОСТАТОК СРЕДСТВ",
    "В валюте счёта",
    "За период",
)


def extract_text_from_pdf(path: Path) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Install requirements.txt before importing PDF files.")
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def extract_text_from_uploaded_pdf(uploaded_file: BinaryIO) -> str:
    suffix = Path(getattr(uploaded_file, "name", "statement.pdf")).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp.flush()
        return extract_text_from_pdf(Path(tmp.name))


def parse_uploaded_pdf(uploaded_file: BinaryIO, profile_id: str) -> list[dict]:
    text = extract_text_from_uploaded_pdf(uploaded_file)
    bank = detect_bank(text)
    source_file = sanitize_text(getattr(uploaded_file, "name", "uploaded.pdf"))
    return parse_text(text, profile_id, source_file, bank)


def parse_text(text: str, profile_id: str, source_file: str, bank: str | None = None) -> list[dict]:
    bank = bank or detect_bank(text)
    if bank == "Сбер":
        return parse_sber(text, profile_id, source_file)
    if bank == "Яндекс Банк":
        return parse_yandex(text, profile_id, source_file)
    if bank == "ВБ Банк":
        return parse_wb(text, profile_id, source_file)
    if bank == "Т-Банк":
        return parse_generic(text, profile_id, source_file, "Т-Банк")
    return parse_generic(text, profile_id, source_file, "Неизвестный банк")


def detect_bank(text: str) -> str:
    lower = text.casefold()
    if "сбер" in lower or "sber" in lower:
        return "Сбер"
    if "т-банк" in lower or "тбанк" in lower or "тинькофф" in lower or "t-bank" in lower or "tbank" in lower:
        return "Т-Банк"
    if "яндекс банк" in lower or "yandex bank" in lower:
        return "Яндекс Банк"
    if "вб банк" in lower or "wildberries bank" in lower or "wb bank" in lower:
        return "ВБ Банк"
    return "Неизвестный банк"


def parse_sber(text: str, profile_id: str, source_file: str) -> list[dict]:
    operations = []
    lines = normalized_lines(text)
    debug_statuses = ["SKIP" for _ in lines]
    debug_details = ["" for _ in lines]
    index = 0
    while index < len(lines):
        block = sber_block_at(lines, index)
        if block:
            operation, next_index, description_indexes = build_sber_block_operation(
                lines,
                index,
                profile_id,
                source_file,
            )
            operations.append(operation)
            debug_statuses[index] = "OPERATION_START"
            debug_details[index] = (
                f"date={block['date']} | time={block['time']} | category={block['category']} | "
                f"amount={block['amount']} | balance={block['balance']}"
            )
            for description_index in description_indexes:
                debug_statuses[description_index] = "DESCRIPTION_LINE"
            index = next_index
            continue
        match = SBER_OPERATION_RE.match(lines[index])
        if match and not is_service_line(lines[index]):
            operation, description_index = build_sber_one_line_operation(
                lines,
                index,
                match,
                profile_id,
                source_file,
            )
            operations.append(operation)
            debug_statuses[index] = "OPERATION_START"
            debug_details[index] = (
                f"date={match.group('date')} | time={match.group('time')} | "
                f"category={match.group('category')} | amount={match.group('amount')} | "
                f"balance={match.group('balance')}"
            )
            if description_index is not None:
                debug_statuses[description_index] = "DESCRIPTION_LINE"
            index += 1
            continue
        index += 1
    write_sber_debug(lines, debug_statuses, debug_details)
    return operations


def sber_block_at(lines: list[str], index: int) -> dict[str, str] | None:
    if index + 4 >= len(lines):
        return None
    date_line = lines[index]
    time_line = lines[index + 1]
    category = lines[index + 2]
    amount = lines[index + 3]
    balance = lines[index + 4]
    if is_service_line(date_line) or is_service_line(category):
        return None
    if not SBER_DATE_LINE_RE.fullmatch(date_line):
        return None
    if not SBER_TIME_LINE_RE.fullmatch(time_line):
        return None
    if not category or parse_money(category) is not None:
        return None
    if parse_money(amount) is None or parse_money(balance) is None:
        return None
    return {
        "date": date_line,
        "time": time_line,
        "category": category.strip(" -—;"),
        "amount": amount,
        "balance": balance,
    }


def build_sber_block_operation(
    lines: list[str],
    index: int,
    profile_id: str,
    source_file: str,
) -> tuple[dict, int, list[int]]:
    block = sber_block_at(lines, index)
    if block is None:
        raise ValueError("No Sber operation block at index")
    amount_text = block["amount"]
    amount = parse_money(amount_text)
    if amount is None:
        raise ValueError("Invalid Sber amount")
    bank_amount = abs(amount) if amount_text.strip().startswith("+") else -abs(amount)
    processing_date = parse_date(block["date"], None)[:10]
    description_start = index + 5
    auth_code = ""
    if description_start < len(lines) and SBER_DATE_LINE_RE.fullmatch(lines[description_start]):
        processing_date = parse_date(lines[description_start], None)[:10]
        description_start += 1
    if description_start < len(lines) and AUTH_CODE_LINE_RE.fullmatch(lines[description_start]):
        auth_code = lines[description_start]
        description_start += 1
    description_lines, description_indexes, next_index = collect_sber_description(lines, description_start)
    description = " ".join(description_lines).strip() or block["category"]
    operation = build_operation(
        profile_id=profile_id,
        bank="Сбер",
        source_file=source_file,
        operation_datetime=parse_date(block["date"], block["time"]),
        processing_date=processing_date,
        description=description,
        raw_category=block["category"],
        bank_amount=bank_amount,
    )
    operation.update(
        {
            "raw_block": "\n".join(lines[index:next_index]),
            "operation_date": block["date"],
            "operation_time": block["time"],
            "amount_text": block["amount"],
            "balance_text": block["balance"],
            "auth_code": auth_code,
        }
    )
    return (
        operation,
        next_index,
        description_indexes,
    )


def collect_sber_description(lines: list[str], start_index: int) -> tuple[list[str], list[int], int]:
    description_lines = []
    description_indexes = []
    index = start_index
    while index < len(lines):
        if sber_block_at(lines, index):
            break
        line = lines[index]
        if is_service_line(line):
            index += 1
            continue
        if SBER_DATE_LINE_RE.fullmatch(line) and index + 1 < len(lines) and AUTH_CODE_LINE_RE.fullmatch(lines[index + 1]):
            index += 2
            continue
        if SBER_DATE_LINE_RE.fullmatch(line) or SBER_TIME_LINE_RE.fullmatch(line) or AUTH_CODE_LINE_RE.fullmatch(line):
            index += 1
            continue
        description_lines.append(line)
        description_indexes.append(index)
        index += 1
    return description_lines, description_indexes, index


def build_sber_one_line_operation(
    lines: list[str],
    index: int,
    match: re.Match,
    profile_id: str,
    source_file: str,
) -> tuple[dict, int | None]:
    amount_text = match.group("amount")
    amount = parse_money(amount_text)
    if amount is None:
        raise ValueError("Invalid Sber amount")
    bank_amount = abs(amount) if amount_text.strip().startswith("+") else -abs(amount)
    raw_category = match.group("category").strip(" -—;")
    description_index = next_description_index(lines, index + 1)
    description_line = lines[description_index] if description_index is not None else ""
    processing_date = parse_processing_date(description_line) or parse_date(match.group("date"), None)[:10]
    auth_match = re.match(r"^\d{2}\.\d{2}\.\d{4}\s+(\d{4,8})\b", description_line or "")
    description = cleanup_sber_description(description_line) if description_line else raw_category
    operation = build_operation(
        profile_id=profile_id,
        bank="Сбер",
        source_file=source_file,
        operation_datetime=parse_date(match.group("date"), match.group("time")),
        processing_date=processing_date,
        description=description,
        raw_category=raw_category,
        bank_amount=bank_amount,
    )
    operation.update(
        {
            "raw_block": "\n".join(lines[index : (description_index + 1 if description_index is not None else index + 1)]),
            "operation_date": match.group("date"),
            "operation_time": match.group("time"),
            "amount_text": amount_text,
            "balance_text": match.group("balance"),
            "auth_code": auth_match.group(1) if auth_match else "",
        }
    )
    return (
        operation,
        description_index,
    )


def next_description_index(lines: list[str], start_index: int) -> int | None:
    for offset, line in enumerate(lines[start_index : start_index + 4], start=start_index):
        if is_service_line(line):
            continue
        if sber_block_at(lines, offset) or SBER_OPERATION_RE.match(line):
            return None
        return offset
    return None


def parse_yandex(text: str, profile_id: str, source_file: str) -> list[dict]:
    return parse_generic(text, profile_id, source_file, "Яндекс Банк")


def parse_wb(text: str, profile_id: str, source_file: str) -> list[dict]:
    return parse_generic(text, profile_id, source_file, "ВБ Банк")


def parse_generic(text: str, profile_id: str, source_file: str, bank: str) -> list[dict]:
    operations = []
    lines = normalized_lines(text)
    for index, line in enumerate(lines):
        if is_service_line(line):
            continue
        date_match = DATE_RE.search(line)
        if not date_match:
            continue
        amount = find_amount(line)
        if amount is None and index + 1 < len(lines):
            if is_service_line(lines[index + 1]):
                continue
            amount = find_amount(lines[index + 1])
            line = f"{line} {lines[index + 1]}"
        if amount is None:
            continue
        operation_dt = parse_date(date_match.group(1), date_match.group(2))
        description = cleanup_description(line, date_match.group(0), amount)
        operations.append(
            build_operation(
                profile_id=profile_id,
                bank=bank,
                source_file=source_file,
                operation_datetime=operation_dt,
                processing_date=datetime.now().date().isoformat(),
                description=description,
                raw_category="",
                bank_amount=amount,
            )
        )
    return operations


def normalized_lines(text: str) -> list[str]:
    return [sanitize_text(line.strip()) for line in text.splitlines() if line.strip()]


def is_service_line(line: str) -> bool:
    lower = line.casefold()
    return any(marker.casefold() in lower for marker in SERVICE_LINE_MARKERS)


def parse_money(raw: str) -> float | None:
    if not SBER_MONEY_RE.fullmatch(raw.strip()):
        return None
    clean = raw.replace(" ", "").replace(",", ".")
    clean = clean.replace("\u00A0", "")
    if clean in {"", "+", "-"}:
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def next_description_line(lines: list[str], start_index: int) -> str:
    for line in lines[start_index : start_index + 4]:
        if is_service_line(line):
            continue
        if SBER_OPERATION_RE.match(line):
            return ""
        if AUTH_DESCRIPTION_RE.match(line):
            return line
        if re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\b", line):
            return ""
        return line
    return ""


def parse_processing_date(line: str) -> str | None:
    match = re.match(r"^(\d{2}\.\d{2}\.\d{4})\b", line or "")
    if not match:
        return None
    return parse_date(match.group(1), None)[:10]


def cleanup_sber_description(line: str) -> str:
    text = re.sub(r"^\d{2}\.\d{2}\.\d{4}\s+", "", line or "")
    text = re.sub(r"^\d{4,8}\s+", "", text)
    return sanitize_text(text.strip(" -—;")) or "Описание не распознано"


def write_sber_debug(lines: list[str], statuses: list[str], details: list[str]) -> None:
    EXPORTS_DIR.mkdir(exist_ok=True)
    rows = []
    for index, line in enumerate(lines, start=1):
        detail = f" | {details[index - 1]}" if details[index - 1] else ""
        rows.append(f"{index:04d} | {statuses[index - 1]}{detail} | {line}")
    SBER_DEBUG_PATH.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def build_operation(
    profile_id: str,
    bank: str,
    source_file: str,
    operation_datetime: str,
    processing_date: str,
    description: str,
    raw_category: str,
    bank_amount: float,
) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "profile_id": profile_id,
        "bank": bank,
        "source_file": source_file,
        "operation_datetime": operation_datetime,
        "processing_date": processing_date,
        "description": sanitize_text(description),
        "raw_description": sanitize_text(description),
        "raw_category": sanitize_text(raw_category),
        "bank_amount": bank_amount,
        "direction": "income" if bank_amount >= 0 else "expense",
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "confidence": 0.0,
        "classification_source": "",
        "needs_review": True,
        "rule_id": "",
        "comment": "",
        "normalized_description": "",
        "merchant_anchor": "",
        "person_anchor": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def find_amount(line: str) -> float | None:
    candidates = []
    for match in AMOUNT_RE.finditer(line):
        raw = match.group(1).replace(" ", "").replace(",", ".")
        if raw in {"", "+", "-"}:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if abs(value) >= 1:
            candidates.append(value)
    if not candidates:
        return None
    return candidates[-1]


def parse_date(date_text: str, time_text: str | None) -> str:
    normalized = date_text.replace("/", ".")
    formats = ["%d.%m.%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            date_value = datetime.strptime(normalized, fmt)
            break
        except ValueError:
            date_value = None
    if date_value is None:
        return datetime.now().isoformat(timespec="seconds")
    if time_text:
        parts = [int(part) for part in time_text.split(":")]
        date_value = date_value.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) > 2 else 0)
    return date_value.isoformat(timespec="seconds")


def cleanup_description(line: str, date_text: str, amount: float) -> str:
    text = line.replace(date_text, " ")
    text = text.replace(str(amount), " ")
    text = re.sub(r"\s+", " ", text).strip(" -—;")
    return sanitize_text(text) or "Описание не распознано"


def review_stub(profile_id: str, bank: str, source_file: str, description: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "profile_id": profile_id,
        "bank": bank,
        "source_file": source_file,
        "operation_datetime": datetime.now().isoformat(timespec="seconds"),
        "processing_date": datetime.now().date().isoformat(),
        "description": sanitize_text(description),
        "raw_description": sanitize_text(description),
        "raw_category": "",
        "bank_amount": 0.0,
        "direction": "expense",
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "confidence": 0.0,
        "classification_source": "",
        "needs_review": True,
        "rule_id": "",
        "comment": "Строка требует ручной проверки",
        "normalized_description": "",
        "merchant_anchor": "",
        "person_anchor": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
