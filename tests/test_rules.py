import unittest

try:
    from classifier import classify_operation
except ModuleNotFoundError:
    classify_operation = None


def operation(raw_category, description, amount=-1000.0, direction="expense", bank="Сбер"):
    return {
        "bank": bank,
        "raw_category": raw_category,
        "description": description,
        "bank_amount": amount,
        "direction": direction,
    }


class RulesOrderTest(unittest.TestCase):
    def setUp(self):
        if classify_operation is None:
            self.skipTest("Project dependencies are not installed in this Python environment")

    def test_user_merchant_rule_applies_before_global_rule(self):
        profile = {
            "rules": [],
            "merchant_rules": [
                {
                    "merchant_anchor": "SAMOKAT",
                    "direction": "expense",
                    "operation_type": "Личный расход",
                    "budget_category": "Кафе и доставка",
                    "personal_amount_mode": "abs",
                }
            ],
        }

        result = classify_operation(operation("Прочие расходы", "SAMOKAT MOSCOW"), profile)

        self.assertEqual(result["budget_category"], "Кафе и доставка")

    def test_person_rule_overrides_everything(self):
        profile = {
            "rules": [
                {
                    "person_anchor": "З. Анна Сергеевна",
                    "direction": "income",
                    "operation_type": "Компенсация совместных расходов",
                    "budget_category": "Жильё",
                    "personal_amount_mode": "-abs",
                    "confidence": 0.95,
                }
            ],
            "merchant_rules": [],
        }

        result = classify_operation(
            operation("Перевод на карту", "Перевод от З. Анна Сергеевна. Операция по счету ****1897", 15000.0, "income"),
            profile,
        )

        self.assertEqual(result["operation_type"], "Компенсация совместных расходов")
        self.assertEqual(result["budget_category"], "Жильё")
        self.assertEqual(result["personal_amount"], -15000.0)
        self.assertFalse(result["needs_review"])

    def test_global_rule_applies_before_bank_category(self):
        result = classify_operation(operation("Супермаркеты", "COFFEE POINT MOSCOW"), {"rules": []})

        self.assertEqual(result["budget_category"], "Кафе и доставка")
        self.assertEqual(result["operation_type"], "Личный расход")

    def test_unknown_operation_goes_to_review(self):
        result = classify_operation(operation("", "UNMATCHED MERCHANT XYZ", bank="Неизвестно"), {"rules": []})

        self.assertEqual(result["operation_type"], "Проверить")
        self.assertEqual(result["budget_category"], "Прочее / проверить")
        self.assertEqual(result["personal_amount"], 0.0)
        self.assertTrue(result["needs_review"])


if __name__ == "__main__":
    unittest.main()
