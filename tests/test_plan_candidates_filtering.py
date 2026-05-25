import unittest

try:
    import pandas as pd
    from planner import (
        get_income_review_candidates_from_operations,
        get_plan_review_candidates_from_operations,
        prepare_planning_dataframe,
        recommended_plan_totals,
    )
except ModuleNotFoundError:
    pd = None
    get_income_review_candidates_from_operations = None
    get_plan_review_candidates_from_operations = None
    prepare_planning_dataframe = None
    recommended_plan_totals = None


def row(month, description, amount, direction="expense"):
    return {
        "id": f"{month}-{description}-{amount}",
        "operation_datetime": f"{month}-10T10:00:00",
        "description": description,
        "normalized_description": description.casefold(),
        "person_anchor": description,
        "merchant_anchor": "",
        "raw_category": "Перевод СБП",
        "direction": direction,
        "bank_amount": abs(amount) if direction == "income" else -abs(amount),
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
    }


class PlanCandidatesFilteringTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def candidate(self, operations, anchor):
        candidates = get_plan_review_candidates_from_operations(pd.DataFrame(operations), "2026-05", 6, {"plan_rules": []})
        return candidates[candidates["anchor"] == anchor].iloc[0]

    def income_candidate(self, operations, anchor):
        candidates = get_income_review_candidates_from_operations(pd.DataFrame(operations), "2026-05", 6, {"plan_rules": []})
        return candidates[candidates["anchor"] == anchor].iloc[0]

    def test_oneoff_2999_expense_is_minor(self):
        candidate = self.candidate([row("2026-04", "Разовый 2999", 2999)], "Разовый 2999")

        self.assertEqual(candidate["importance_level"], "minor_oneoff")

    def test_oneoff_3000_expense_is_minor(self):
        candidate = self.candidate([row("2026-04", "Разовый 3000", 3000)], "Разовый 3000")

        self.assertEqual(candidate["expense_nature"], "oneoff_minor")
        self.assertEqual(candidate["importance_level"], "minor_oneoff")

    def test_oneoff_2999_income_is_minor(self):
        candidate = self.income_candidate([row("2026-04", "Входящий 2999", 2999, "income")], "Входящий 2999")

        self.assertEqual(candidate["importance_level"], "minor_oneoff")

    def test_oneoff_3000_income_is_minor(self):
        candidate = self.income_candidate([row("2026-04", "Входящий 3000", 3000, "income")], "Входящий 3000")

        self.assertEqual(candidate["expense_nature"], "oneoff_minor")
        self.assertEqual(candidate["importance_level"], "minor_oneoff")

    def test_repeated_500_three_months_is_important(self):
        operations = [row(month, "Повтор 500", 500) for month in ["2026-02", "2026-03", "2026-04"]]
        candidate = self.candidate(operations, "Повтор 500")

        self.assertEqual(candidate["importance_level"], "important")

    def test_regular_65000_is_important(self):
        candidate = self.candidate([row("2026-04", "Квартира", 65000)], "Квартира")

        self.assertEqual(candidate["expense_nature"], "oneoff_large")
        self.assertEqual(candidate["importance_level"], "oneoff_large")

    def test_regular_expense_rule_sets_count_in_plan(self):
        operations = pd.DataFrame([row("2026-04", "Квартира", 65000)])
        profile = {
            "plan_rules": [
                {
                    "enabled": True,
                    "match_contains_any": ["Квартира"],
                    "scenario": "regular_expense",
                    "operation_type": "Личный расход",
                    "budget_category": "Жильё",
                    "plan_category": "Жильё",
                    "budget_amount_mode": "abs",
                    "planning_amount_mode": "abs",
                    "count_in_budget": True,
                    "count_in_plan": True,
                }
            ]
        }

        planned = prepare_planning_dataframe(operations, profile)

        self.assertTrue(bool(planned.loc[0, "count_in_plan"]))
        self.assertEqual(planned.loc[0, "planning_amount"], 65000)

    def test_internal_transfer_rule_zeroes_planning_amount(self):
        operations = pd.DataFrame([row("2026-04", "Свой банк", 100000)])
        profile = {
            "plan_rules": [
                {
                    "enabled": True,
                    "match_contains_any": ["Свой банк"],
                    "scenario": "internal_transfer",
                    "operation_type": "Внутренний перевод",
                    "budget_category": "Не учитывать",
                    "plan_category": "Не учитывать",
                    "budget_amount_mode": "0",
                    "planning_amount_mode": "0",
                    "count_in_budget": False,
                    "count_in_plan": False,
                }
            ]
        }

        planned = prepare_planning_dataframe(operations, profile)

        self.assertFalse(bool(planned.loc[0, "count_in_plan"]))
        self.assertEqual(planned.loc[0, "planning_amount"], 0)

    def test_compensation_rule_sets_negative_planning_amount(self):
        operation = row("2026-04", "Анна", 15000)
        operation["direction"] = "income"
        operation["bank_amount"] = 15000
        operations = pd.DataFrame([operation])
        profile = {
            "plan_rules": [
                {
                    "enabled": True,
                    "match_contains_any": ["Анна"],
                    "scenario": "compensation",
                    "operation_type": "Компенсация совместных расходов",
                    "budget_category": "Жильё",
                    "plan_category": "Жильё",
                    "budget_amount_mode": "-abs",
                    "planning_amount_mode": "-abs",
                    "count_in_budget": True,
                    "count_in_plan": True,
                }
            ]
        }

        planned = prepare_planning_dataframe(operations, profile)

        self.assertTrue(bool(planned.loc[0, "count_in_plan"]))
        self.assertEqual(planned.loc[0, "planning_amount"], -15000)

    def test_recommended_plan_totals(self):
        recommended = pd.DataFrame(
            [
                {"budget_category": "Готово", "suggested_plan": 10000, "status": "ready"},
                {"budget_category": "Разобрать", "suggested_plan": 20000, "status": "needs_classification"},
                {"budget_category": "Мало", "suggested_plan": 3000, "status": "low_history"},
            ]
        )

        totals = recommended_plan_totals(recommended)

        self.assertEqual(totals["recommended_total"], 33000)
        self.assertEqual(totals["ready_total"], 10000)
        self.assertEqual(totals["needs_classification_total"], 20000)
        self.assertEqual(totals["low_history_total"], 3000)


if __name__ == "__main__":
    unittest.main()
