import unittest

try:
    from classifier import classify_operation, extract_merchant_anchor, extract_person_anchor
except ModuleNotFoundError:
    classify_operation = None


def operation(raw_category, description, amount, direction="expense"):
    return {
        "bank": "Сбер",
        "raw_category": raw_category,
        "description": description,
        "bank_amount": amount,
        "direction": direction,
    }


class ClassifierTest(unittest.TestCase):
    def setUp(self):
        if classify_operation is None:
            self.skipTest("Project dependencies are not installed in this Python environment")

    def test_sber_raw_category_expense(self):
        result = classify_operation(operation("Супермаркеты", "VKUSVILL", -1200.0), {"rules": []})

        self.assertEqual(result["operation_type"], "Личный расход")
        self.assertEqual(result["budget_category"], "Продукты")
        self.assertEqual(result["personal_amount"], 1200.0)
        self.assertFalse(result["needs_review"])

    def test_global_merchant_rule_before_raw_category(self):
        result = classify_operation(operation("Прочие расходы", "YANDEX*4121*GO", -800.0), {"rules": []})

        self.assertEqual(result["operation_type"], "Личный расход")
        self.assertEqual(result["budget_category"], "Такси")
        self.assertEqual(result["personal_amount"], 800.0)
        self.assertFalse(result["needs_review"])

    def test_transfers_stay_review(self):
        result = classify_operation(operation("Перевод с карты", "Перевод для Анны", -2000.0), {"rules": []})

        self.assertEqual(result["operation_type"], "Проверить")
        self.assertEqual(result["budget_category"], "Прочее / проверить")
        self.assertEqual(result["personal_amount"], 0.0)
        self.assertTrue(result["needs_review"])

    def test_salary_income(self):
        result = classify_operation(
            operation("Прочие зачисления", "Аванс по заработной плате", 100000.0, "income"),
            {"rules": []},
        )

        self.assertEqual(result["operation_type"], "Личный доход")
        self.assertEqual(result["budget_category"], "Зарплата")
        self.assertEqual(result["personal_amount"], 100000.0)
        self.assertFalse(result["needs_review"])

    def test_internal_vklad_transfer(self):
        result = classify_operation(
            operation("Прочие операции", "SBERBANK ONL@IN VKLAD-KARTA", -5000.0),
            {"rules": []},
        )

        self.assertEqual(result["operation_type"], "Внутренний перевод")
        self.assertEqual(result["personal_amount"], 0.0)
        self.assertFalse(result["needs_review"])

    def test_extract_sber_merchant_and_person_anchors(self):
        self.assertEqual(
            extract_merchant_anchor("YANDEX*4121*GO MOSCOW RUS. Операция по карте ****8363", "Сбер", ""),
            "YANDEX*4121*GO",
        )
        self.assertEqual(
            extract_merchant_anchor("SUPERMARKET AZBUKA VKUSA MOSCOW RUS. Операция по карте ****8363", "Сбер", ""),
            "SUPERMARKET AZBUKA VKUSA",
        )
        self.assertEqual(
            extract_person_anchor("Перевод от З. Анна Сергеевна. Операция по счету ****1897"),
            "З. Анна Сергеевна",
        )

    def test_sber_samokat_from_other_expenses(self):
        result = classify_operation(
            operation("Прочие расходы", "SBER*5411*SAMOKAT SANKT-PETERBU RUS. Операция по карте ****0653", -1200.0),
            {"rules": []},
        )

        self.assertEqual(result["budget_category"], "Продукты")
        self.assertFalse(result["needs_review"])

    def test_sber_yasno_goes_to_therapy(self):
        result = classify_operation(operation("Все для дома", "YM*YASNO MOSCOW RUS. Операция по карте ****0653", -3000.0), {"rules": []})

        self.assertEqual(result["operation_type"], "Личный расход")
        self.assertEqual(result["budget_category"], "Здоровье")

    def test_sber_voron_goes_to_carsharing(self):
        result = classify_operation(operation("Отдых и развлечения", "VORON MOSCOW RUS. Операция по карте ****0653", -3000.0), {"rules": []})

        self.assertEqual(result["operation_type"], "Личный расход")
        self.assertEqual(result["budget_category"], "Авто")

    def test_getcourse_goes_to_education(self):
        result = classify_operation(operation("Прочие расходы", "GETCOURSE MOSCOW RUS. Операция по карте ****0653", -5000.0), {"rules": []})

        self.assertEqual(result["budget_category"], "Обучение")

    def test_sber_whoosh_and_cyrillic_burger_are_card_expenses(self):
        whoosh = classify_operation(operation("Отдых и развлечения", "WHOOSH MOSCOW RUS. Операция по карте ****8640", -93.95), {"rules": []})
        burger = classify_operation(operation("Оплата по QR–коду СБП", "ООО БУРГЕР РУС. Операция по карте ****8640", -59.98), {"rules": []})

        self.assertEqual(whoosh["operation_type"], "Личный расход")
        self.assertEqual(whoosh["budget_category"], "Отдых и развлечения")
        self.assertFalse(whoosh["needs_review"])
        self.assertEqual(burger["operation_type"], "Личный расход")
        self.assertEqual(burger["budget_category"], "Кафе и доставка")
        self.assertFalse(burger["needs_review"])

    def test_sber_cash_withdrawal_is_separate_zero_budget_type(self):
        result = classify_operation(operation("Выдача наличных", "ATM 60019617 BARNAUL RUS. Операция по карте ****8640", -500.0), {"rules": []})

        self.assertEqual(result["operation_type"], "cash_withdrawal")
        self.assertEqual(result["personal_amount"], 0.0)
        self.assertFalse(result["needs_review"])

    def test_tbank_internal_jar_transfers_are_ignored(self):
        for description in ["Пополнение Кубышки", "Перевод средств из Кубышки"]:
            result = classify_operation(
                {
                    "bank": "Т-Банк",
                    "raw_category": "",
                    "description": description,
                    "bank_amount": 1000.0,
                    "direction": "income",
                },
                {"rules": []},
            )

            self.assertEqual(result["operation_type"], "Внутренний перевод")
            self.assertEqual(result["personal_amount"], 0.0)
            self.assertFalse(result["needs_review"])

    def test_tbank_merchants_by_description(self):
        grocery = classify_operation(
            {
                "bank": "Т-Банк",
                "raw_category": "",
                "description": "Оплата в MARIYA-RA Barnaul RUS",
                "bank_amount": -1000.0,
                "direction": "outgoing",
            },
            {"rules": []},
        )
        transport = classify_operation(
            {
                "bank": "Т-Банк",
                "raw_category": "",
                "description": "Оплата в TRANSPORT BARNAUL_TPP Barnaul RUS",
                "bank_amount": -100.0,
                "direction": "expense",
            },
            {"rules": []},
        )

        self.assertEqual(grocery["merchant_anchor"], "MARIYA-RA")
        self.assertEqual(grocery["budget_category"], "Продукты")
        self.assertEqual(transport["merchant_anchor"], "TRANSPORT BARNAUL_TPP")
        self.assertEqual(transport["budget_category"], "Транспорт")

    def test_unknown_transfer_to_person_goes_to_review(self):
        result = classify_operation(operation("Перевод СБП", "Перевод для Ш. Семен Юрьевич. Операция по счету ****1897", -2000.0), {"rules": []})

        self.assertEqual(result["personal_amount"], 0.0)
        self.assertTrue(result["needs_review"])


if __name__ == "__main__":
    unittest.main()
