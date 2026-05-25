import unittest

from bank_adapters.alfa import parse_alfa_credit_card, parse_alfa_current_account


class AlfaAdapterTest(unittest.TestCase):
    def test_current_internal_transfer(self):
        op = parse_alfa_current_account(
            "01.05.2026 Внутрибанковский перевод между счетами, Иванов -1 000,00",
            {"profile_id": "p", "source_file": "a.pdf"},
        )[0]
        self.assertEqual(op["operation_type"], "Внутренний перевод")

    def test_credit_events(self):
        text = "\n".join(
            [
                "01.05.2026 Предоставление транша +10 000,00",
                "02.05.2026 Погашение процентов -100,00",
                "03.05.2026 Погашение ОД -1 000,00",
            ]
        )
        ops = parse_alfa_credit_card(text, {"profile_id": "p", "source_file": "ac.pdf"})
        self.assertEqual(ops[0]["operation_type"], "credit_draw")
        self.assertEqual(ops[1]["operation_type"], "credit_interest")
        self.assertEqual(ops[2]["operation_type"], "debt_repayment")

