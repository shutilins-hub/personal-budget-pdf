import unittest

try:
    import pandas as pd
    from planner import get_plan_review_candidates_from_operations, prepare_planning_dataframe
except ModuleNotFoundError:
    pd = None
    get_plan_review_candidates_from_operations = None
    prepare_planning_dataframe = None


def operation(month, description, amount, suffix=""):
    return {
        "id": f"{month}-{description}-{amount}-{suffix}",
        "operation_datetime": f"{month}-10T10:00:00",
        "description": description,
        "normalized_description": description.casefold(),
        "person_anchor": description,
        "merchant_anchor": "",
        "raw_category": "Перевод СБП",
        "direction": "expense",
        "bank_amount": -abs(amount),
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
    }


class RecurringExpenseRulesTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def candidate(self, operations, anchor):
        candidates = get_plan_review_candidates_from_operations(pd.DataFrame(operations), "2026-05", 6, {"plan_rules": []})
        return candidates[candidates["anchor"] == anchor].iloc[0]

    def test_oneoff_3000_is_minor_and_not_regular(self):
        candidate = self.candidate([operation("2026-04", "Разовый 3000", 3000)], "Разовый 3000")

        self.assertEqual(candidate["expense_nature"], "oneoff_minor")
        self.assertNotEqual(candidate["importance_level"], "important")

    def test_oneoff_7000_is_large_and_not_regular(self):
        candidate = self.candidate([operation("2026-04", "Разовый 7000", 7000)], "Разовый 7000")

        self.assertEqual(candidate["expense_nature"], "oneoff_large")
        self.assertEqual(candidate["importance_level"], "oneoff_large")

    def test_three_times_in_one_month_is_recurring(self):
        operations = [operation("2026-04", "Повтор 3000", 3000, str(index)) for index in range(3)]
        candidate = self.candidate(operations, "Повтор 3000")

        self.assertEqual(candidate["expense_nature"], "recurring")
        self.assertEqual(candidate["importance_level"], "important")
        self.assertEqual(candidate["months_seen"], 1)

    def test_two_months_is_recurring(self):
        operations = [operation("2026-03", "Два месяца", 3000), operation("2026-04", "Два месяца", 3000)]
        candidate = self.candidate(operations, "Два месяца")

        self.assertEqual(candidate["expense_nature"], "recurring")
        self.assertEqual(candidate["importance_level"], "important")

    def test_manual_recurring_confirmed_rule_can_enter_plan(self):
        operations = pd.DataFrame([operation("2026-04", "Один раз, но постоянный", 7000)])
        profile = {
            "plan_rules": [
                {
                    "enabled": True,
                    "match_contains_any": ["Один раз, но постоянный"],
                    "scenario": "regular_expense",
                    "manual_recurring_confirmed": True,
                    "operation_type": "Личный расход",
                    "budget_category": "Обучение",
                    "plan_category": "Обучение",
                    "budget_amount_mode": "abs",
                    "planning_amount_mode": "abs",
                    "count_in_budget": True,
                    "count_in_plan": True,
                }
            ]
        }

        planned = prepare_planning_dataframe(operations, profile)

        self.assertTrue(bool(planned.loc[0, "count_in_plan"]))
        self.assertEqual(planned.loc[0, "planning_amount"], 7000)
        self.assertTrue(profile["plan_rules"][0]["manual_recurring_confirmed"])


if __name__ == "__main__":
    unittest.main()
