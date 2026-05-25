import unittest

from bank_adapters.yandex import parse_yandex_credit_contract, parse_yandex_wallet_eds


class YandexAdapterTest(unittest.TestCase):
    def test_wallet_rules(self):
        text = "\n".join(
            [
                "01.05.2026 Входящий перевод СБП, Никита Юрьевич Ш., Сбербанк +5 000,00",
                "01.05.2026 YANDEX.TAXI -500,00",
                "01.05.2026 YANDEX LAVKA -700,00",
            ]
        )
        ops = parse_yandex_wallet_eds(text, {"profile_id": "p", "source_file": "y.pdf"})
        self.assertEqual(ops[0]["operation_type"], "Внутренний перевод")
        self.assertEqual(ops[1]["budget_category"], "Такси")
        self.assertEqual(ops[2]["budget_category"], "Продукты / супермаркеты")

    def test_credit_rules(self):
        text = "\n".join(
            [
                "01.05.2026 Оплата товаров и услуг YM*dns-shop 10 000,00",
                "02.05.2026 Погашение основного долга по договору 5 000,00",
            ]
        )
        ops = parse_yandex_credit_contract(text, {"profile_id": "p", "source_file": "yc.pdf"})
        self.assertEqual(ops[0]["operation_type"], "credit_purchase")
        self.assertEqual(ops[1]["operation_type"], "debt_repayment")

