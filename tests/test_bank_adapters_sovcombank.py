import unittest

from bank_adapters.sovcombank import parse_sovcombank_halva


class SovcombankAdapterTest(unittest.TestCase):
    def test_halva_rules(self):
        text = "\n".join(
            [
                "ПРЕДОСТАВЛЕНИЕ КРЕДИТА ЗАЕМЩИКУ ПУТЕМ ЗАЧИСЛЕНИЯ НА ДЕПОЗИТНЫЙ СЧЕТ 10 000,00",
                "01.05.2026 Платеж АВТОРИЗАЦИЯ №123 MCC 5411 LENTA 1 000,00",
                "02.05.2026 ПОГАШЕНИЕ КРЕДИТА 1 000,00",
                "03.05.2026 Комиссия за услуги Подписки 199,00",
            ]
        )
        ops = parse_sovcombank_halva(text, {"profile_id": "p", "source_file": "h.pdf"})
        self.assertEqual(len(ops), 3)
        self.assertEqual(ops[0]["budget_category"], "Продукты")
        self.assertEqual(ops[1]["operation_type"], "debt_repayment")
        self.assertEqual(ops[2]["budget_category"], "Кредиты / проценты / комиссии")
