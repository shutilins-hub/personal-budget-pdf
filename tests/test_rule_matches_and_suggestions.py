from __future__ import annotations

import unittest

from classifier import rule_matches, suggest_category_for_operation


class RuleMatchesAndSuggestionsTest(unittest.TestCase):
    def test_personal_merchant_rule_matches_operation_category(self) -> None:
        operation = {
            "direction": "expense",
            "bank_amount": -1200,
            "merchant_anchor": "TILDA",
            "description": "CP* TILDA MOSKVA RUS",
        }
        rule = {
            "enabled": True,
            "direction": "expense",
            "merchant_anchor": "TILDA",
            "budget_category": "Проектный оборот",
        }

        self.assertTrue(rule_matches(operation, rule))

    def test_expense_rule_does_not_apply_to_income_operation(self) -> None:
        operation = {
            "direction": "income",
            "bank_amount": 10000,
            "merchant_anchor": "TILDA",
            "description": "Перевод от клиента",
        }
        rule = {"enabled": True, "direction": "expense", "merchant_anchor": "TILDA"}

        self.assertFalse(rule_matches(operation, rule))

    def test_merchant_rule_does_not_apply_to_other_merchant(self) -> None:
        operation = {
            "direction": "expense",
            "bank_amount": -700,
            "merchant_anchor": "SAMOKAT",
            "description": "SBER*5411*SAMOKAT",
        }
        rule = {"enabled": True, "direction": "expense", "merchant_anchor": "TILDA"}

        self.assertFalse(rule_matches(operation, rule))

    def test_suggest_category_uses_matching_personal_rule(self) -> None:
        operation = {
            "direction": "expense",
            "bank_amount": -12000,
            "merchant_anchor": "TILDA",
            "description": "CP* TILDA MOSKVA RUS",
            "raw_category": "Прочие расходы",
        }
        profile = {
            "merchant_rules": [
                {
                    "id": "merchant_tilda_project",
                    "enabled": True,
                    "direction": "expense",
                    "merchant_anchor": "TILDA",
                    "budget_category": "Проектный оборот",
                    "confidence": 0.96,
                }
            ]
        }

        suggestion = suggest_category_for_operation(operation, profile)

        self.assertEqual(suggestion["source"], "personal_rule")
        self.assertEqual(suggestion["suggested_category"], "Проектный оборот")

    def test_rule_matches_without_anchors_does_not_crash(self) -> None:
        operation = {"direction": "expense", "bank_amount": -500, "description": "UNKNOWN"}
        rule = {"enabled": True, "direction": "expense", "contains_any": ["UNKNOWN"]}

        self.assertTrue(rule_matches(operation, rule))


if __name__ == "__main__":
    unittest.main()
