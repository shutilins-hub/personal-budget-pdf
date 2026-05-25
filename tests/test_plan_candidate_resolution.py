import unittest

try:
    import pandas as pd
    from planner import get_income_review_candidates_from_operations, get_plan_review_candidates_from_operations, prepare_planning_dataframe
except ModuleNotFoundError:
    pd = None
    get_income_review_candidates_from_operations = None
    get_plan_review_candidates_from_operations = None
    prepare_planning_dataframe = None


def operation(anchor, amount, direction="expense", operation_type="Проверить", raw_category="Перевод с карты"):
    return {
        "id": f"{anchor}-{amount}-{direction}",
        "operation_datetime": "2026-04-10T10:00:00",
        "description": f"Перевод {'от' if direction == 'income' else 'для'} {anchor}",
        "raw_description": f"Перевод {'от' if direction == 'income' else 'для'} {anchor}",
        "normalized_description": f"перевод {anchor}".casefold(),
        "person_anchor": anchor,
        "merchant_anchor": "",
        "raw_category": raw_category,
        "direction": direction,
        "bank_amount": amount,
        "operation_type": operation_type,
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "needs_review": operation_type == "Проверить",
        "classification_source": "review_fallback" if operation_type == "Проверить" else "",
        "rule_id": "",
    }


def candidate_anchors(candidates):
    return set(candidates["anchor"].tolist()) if not candidates.empty else set()


class PlanCandidateResolutionTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_ignored_anchor_disappears_from_expense_candidates(self):
        anchor = "М. Маргарита Георгиевна"
        operations = pd.DataFrame([operation(anchor, -35000)])

        before = get_plan_review_candidates_from_operations(operations, "2026-05", 6, {"plan_rules": []})
        self.assertIn(anchor, candidate_anchors(before))

        profile = {
            "plan_rules": [
                {
                    "id": "plan_margarita",
                    "enabled": True,
                    "match_contains_any": [anchor],
                    "direction": "expense",
                    "scenario": "ignore_in_plan",
                    "operation_type": "Не учитывать",
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
        self.assertEqual(planned.loc[0, "operation_type"], "Не учитывать")

        after = get_plan_review_candidates_from_operations(operations, "2026-05", 6, profile)
        self.assertNotIn(anchor, candidate_anchors(after))

    def test_internal_transfer_rule_disappears_from_expense_candidates(self):
        anchor = "Свой Т-Банк"
        operations = pd.DataFrame([operation(anchor, -100000)])
        profile = {
            "plan_rules": [
                {
                    "id": "plan_internal",
                    "enabled": True,
                    "match_contains_any": [anchor],
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

        candidates = get_plan_review_candidates_from_operations(operations, "2026-05", 6, profile)

        self.assertNotIn(anchor, candidate_anchors(candidates))

    def test_regular_expense_rule_enters_plan_but_not_candidates(self):
        anchor = "Квартира"
        operations = pd.DataFrame([operation(anchor, -65000)])
        profile = {
            "plan_rules": [
                {
                    "id": "plan_rent",
                    "enabled": True,
                    "match_contains_any": [anchor],
                    "direction": "expense",
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
        candidates = get_plan_review_candidates_from_operations(operations, "2026-05", 6, profile)

        self.assertTrue(bool(planned.loc[0, "count_in_plan"]))
        self.assertEqual(planned.loc[0, "planning_amount"], 65000)
        self.assertNotIn(anchor, candidate_anchors(candidates))

    def test_income_transfer_without_rule_is_income_candidate(self):
        anchor = "З. Анна Сергеевна"
        operations = pd.DataFrame([operation(anchor, 15000, "income", raw_category="Перевод на карту")])

        candidates = get_income_review_candidates_from_operations(operations, "2026-05", 6, {"plan_rules": []})

        self.assertIn(anchor, candidate_anchors(candidates))

    def test_income_internal_transfer_rule_is_not_income_candidate_or_income(self):
        anchor = "Свой счёт"
        operations = pd.DataFrame([operation(anchor, 100000, "income", raw_category="Прочие операции")])
        profile = {
            "plan_rules": [
                {
                    "id": "plan_income_internal",
                    "enabled": True,
                    "match_contains_any": [anchor],
                    "direction": "income",
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
        candidates = get_income_review_candidates_from_operations(operations, "2026-05", 6, profile)

        self.assertEqual(planned.loc[0, "operation_type"], "Внутренний перевод")
        self.assertEqual(planned.loc[0, "budget_amount"], 0)
        self.assertNotIn(anchor, candidate_anchors(candidates))


if __name__ == "__main__":
    unittest.main()
