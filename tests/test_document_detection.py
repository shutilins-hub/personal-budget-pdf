import unittest

from bank_adapters.detect import detect_document_type


class DocumentDetectionTest(unittest.TestCase):
    def test_known_documents(self):
        cases = [
            ("Выписка по счёту кредитной карты\nКредитный лимит", "sber_credit_card"),
            ("Выписка по платёжному счёту\nСбер", "sber_debit_account"),
            ("АО «ТБАНК»\nСправка о движении средств", "tbank_statement"),
            ("АО «Яндекс Банк»\nСчёт ЭДС", "yandex_wallet_eds"),
            ("АО «Яндекс Банк»\nПотребительский кредит", "yandex_credit_contract"),
            ("ООО «ВБ Банк»\nОплата на Wildberries", "wb_wallet"),
            ("АО «АЛЬФА-БАНК»\nТекущий счёт", "alfa_current_account"),
            ("АО «АЛЬФА-БАНК»\nСчёт кредитной карты", "alfa_credit_card"),
            ("Карта рассрочки Халва\nПРЕДОСТАВЛЕНИЕ КРЕДИТА ЗАЕМЩИКУ", "sovcombank_halva"),
            ("Application for Schengen Visa\nHarmonised application form", "irrelevant_document"),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(detect_document_type(text)["document_type"], expected)

