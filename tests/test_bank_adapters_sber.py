import unittest

from bank_adapters.sber import extract_sber_credit_metadata, parse_sber_debit_account


class SberAdapterTest(unittest.TestCase):
    def test_debit_purchase_and_internal_transfer_and_salary(self):
        text = "\n".join(
            [
                "16.05.2026",
                "13:13",
                "Супермаркеты",
                "114,69",
                "20 956,34",
                "16.05.2026",
                "961326",
                "KRASNOE&BELOE Barnaul RUS. Операция по карте ****8640",
                "16.05.2026",
                "14:00",
                "Прочие операции",
                "1 000,00",
                "19 956,34",
                "16.05.2026",
                "123456",
                "SBERBANK ONL@IN KARTA-VKLAD",
                "16.05.2026",
                "15:00",
                "Прочие операции",
                "+78 300,00",
                "98 256,34",
                "16.05.2026",
                "654321",
                "Заработная плата",
            ]
        )
        ops = parse_sber_debit_account(text, {"profile_id": "p", "source_file": "sber.pdf"})
        self.assertEqual(ops[0]["budget_category"], "Продукты / супермаркеты")
        self.assertEqual(ops[1]["operation_type"], "Внутренний перевод")
        self.assertEqual(ops[2]["operation_type"], "Личный доход")

    def test_credit_metadata(self):
        metadata = extract_sber_credit_metadata("Кредитный лимит 100 000,00\nОбщая задолженность 25 000,00")
        self.assertEqual(metadata["credit_limit"], 100000.0)
        self.assertEqual(metadata["debt_end"], 25000.0)

