import unittest

from bank_adapters.wb import parse_wb_wallet


class WBAdapterTest(unittest.TestCase):
    def test_wallet_topup_and_purchase(self):
        ops = parse_wb_wallet(
            "01.05.2026 Зачисление перевода СБП +1 000,00\n01.05.2026 Оплата на Wildberries -700,00",
            {"profile_id": "p", "source_file": "wb.pdf"},
        )
        self.assertEqual(ops[0]["operation_type"], "wallet_topup")
        self.assertEqual(ops[1]["budget_category"], "Прочее / проверить")
        self.assertTrue(ops[1]["needs_review"])
