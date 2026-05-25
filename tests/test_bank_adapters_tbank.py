import unittest

from bank_adapters.tbank import parse_tbank_statement


class TBankAdapterTest(unittest.TestCase):
    def parse_one(self, description):
        return parse_tbank_statement(f"01.05.2026 10:00 {description} -1 000,00", {"profile_id": "p", "source_file": "t.pdf"})[0]

    def test_purchase_food(self):
        op = self.parse_one("Оплата в MARIYA-RA Barnaul RUS")
        self.assertEqual(op["budget_category"], "Продукты / супермаркеты")

    def test_internal_transfers(self):
        for description in ["Внутренний перевод на договор", "Пополнение Кубышки"]:
            with self.subTest(description=description):
                self.assertEqual(self.parse_one(description)["operation_type"], "Внутренний перевод")

    def test_ip_and_external_transfer_need_review(self):
        for description in ["Пополнение. ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ Иванов", "Внешний перевод по номеру телефона +79001112233"]:
            with self.subTest(description=description):
                op = self.parse_one(description)
                self.assertTrue(op["needs_review"])
                self.assertEqual(op["operation_type"], "unknown_transfer")

