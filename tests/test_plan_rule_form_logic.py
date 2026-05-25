import unittest

try:
    import pandas as pd
    from planner import (
        default_plan_behavior_for_candidate,
        default_rule_scope_for_candidate,
        get_plan_review_candidates_from_operations,
        plan_rule_matches,
        prepare_planning_dataframe,
    )
except ModuleNotFoundError:
    pd = None
    default_plan_behavior_for_candidate = None
    default_rule_scope_for_candidate = None
    get_plan_review_candidates_from_operations = None
    plan_rule_matches = None
    prepare_planning_dataframe = None


def op(op_id, month, description, amount, direction="expense"):
    return {
        "id": op_id,
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


class PlanRuleFormLogicTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def candidates(self, operations):
        return get_plan_review_candidates_from_operations(pd.DataFrame(operations), "2026-05", 6, {"plan_rules": []})

    def test_single_7000_defaults_to_single_operation(self):
        candidate = self.candidates([op("one", "2026-04", "Разовый перевод", 7000)]).iloc[0]

        self.assertEqual(candidate["expense_nature"], "oneoff_large")
        self.assertEqual(default_rule_scope_for_candidate(candidate), "single_operation")
        self.assertEqual(default_plan_behavior_for_candidate(candidate), "Учитывать только в этом месяце")

    def test_three_months_can_be_recurring_rule(self):
        candidate = self.candidates(
            [
                op("m1", "2026-02", "Постоянный", 3000),
                op("m2", "2026-03", "Постоянный", 3000),
                op("m3", "2026-04", "Постоянный", 3000),
            ]
        ).iloc[0]

        self.assertEqual(candidate["expense_nature"], "recurring")
        self.assertEqual(default_rule_scope_for_candidate(candidate), "recurring_rule")
        self.assertEqual(default_plan_behavior_for_candidate(candidate), "Учитывать как постоянную статью")

    def test_single_operation_rule_matches_only_operation_id(self):
        rule = {
            "enabled": True,
            "match_contains_any": ["Анна"],
            "direction": "income",
            "rule_scope": "single_operation",
            "operation_id": "anna-one",
        }
        first = pd.Series(op("anna-one", "2026-04", "Анна", 8000, "income"))
        second = pd.Series(op("anna-two", "2026-04", "Анна", 8000, "income"))

        self.assertTrue(plan_rule_matches(first, rule))
        self.assertFalse(plan_rule_matches(second, rule))

    def test_internal_transfer_rule_zeroes_budget_and_plan(self):
        operations = pd.DataFrame([op("self", "2026-04", "Свой счет", 10000)])
        profile = {
            "plan_rules": [
                {
                    "enabled": True,
                    "match_contains_any": ["Свой счет"],
                    "direction": "expense",
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

        self.assertEqual(planned.loc[0, "budget_amount"], 0)
        self.assertEqual(planned.loc[0, "planning_amount"], 0)
        self.assertFalse(bool(planned.loc[0, "count_in_budget"]))
        self.assertFalse(bool(planned.loc[0, "count_in_plan"]))

    def test_technical_form_is_conceptually_hidden_by_default(self):
        self.assertEqual(default_rule_scope_for_candidate({"count": 1, "months_seen": 1}), "single_operation")


if __name__ == "__main__":
    unittest.main()
