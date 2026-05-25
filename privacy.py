import re


PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s\-()]*(?:\d[\s\-()]*){10}(?!\d)")
ACCOUNT_RE = re.compile(r"\b\d{12,20}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def mask_phone(text: str) -> str:
    return PHONE_RE.sub("[телефон скрыт]", text or "")


def mask_account(text: str) -> str:
    text = ACCOUNT_RE.sub("[счет скрыт]", text or "")
    return CARD_RE.sub("[карта скрыта]", text)


def mask_fio(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\b", "[ФИО скрыто]", text)


def sanitize_text(text: str) -> str:
    text = mask_phone(text)
    text = mask_account(text)
    return mask_fio(text)
