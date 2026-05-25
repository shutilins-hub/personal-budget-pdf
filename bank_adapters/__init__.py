from __future__ import annotations

from .detect import detect_document_type
from .models import link_internal_transfers, is_probable_own_transfer
from .sber import parse_sber_credit_card, parse_sber_debit_account
from .tbank import parse_tbank_statement
from .yandex import parse_yandex_credit_contract, parse_yandex_wallet_eds
from .wb import parse_wb_wallet
from .alfa import parse_alfa_credit_card, parse_alfa_current_account
from .sovcombank import parse_sovcombank_halva


def parse_by_document_type(text: str, metadata: dict) -> list[dict]:
    document_type = metadata.get("document_type") or metadata.get("detected_document_type") or "unknown_document"
    if document_type == "sber_debit_account":
        return parse_sber_debit_account(text, metadata)
    if document_type == "sber_credit_card":
        return parse_sber_credit_card(text, metadata)
    if document_type in {"tbank_statement", "tbank_card_statement", "tbank_main_contract"}:
        return parse_tbank_statement(text, metadata)
    if document_type == "yandex_wallet_eds":
        return parse_yandex_wallet_eds(text, metadata)
    if document_type == "yandex_credit_contract":
        return parse_yandex_credit_contract(text, metadata)
    if document_type == "wb_wallet":
        return parse_wb_wallet(text, metadata)
    if document_type == "alfa_current_account":
        return parse_alfa_current_account(text, metadata)
    if document_type == "alfa_credit_card":
        return parse_alfa_credit_card(text, metadata)
    if document_type == "sovcombank_halva":
        return parse_sovcombank_halva(text, metadata)
    return []
