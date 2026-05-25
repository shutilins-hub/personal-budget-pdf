import tempfile
import unittest
from pathlib import Path

try:
    import pandas as pd

    import storage
    from planner import (
        build_auto_income_plan,
        build_raw_income_plan_from_operations,
        get_income_review_candidates_from_operations,
        get_plan_review_candidates_from_operations,
        prepare_planning_dataframe,
    )
    from storage import load_json, save_json, upsert_plan_rule
except ModuleNotFoundError:
    pd = None


def op(anchor, amount, direction="expense"):
    prefix = "Перевод от" if direction == "income" else "Перевод для"
    return {
        "id": f"{anchor}-{amount}-{direction}",
        "operation_datetime": "2026-04-10T10:00:00",
        "description": f"{prefix} {anchor}",
        "raw_description": f"{prefix} {anchor}",
        "normalized_description": f"{prefix} {anchor}".casefold(),
        "person_anchor": anchor,
        "merchant_anchor": "",
        "raw_category": "Перевод на карту" if direction == "income" else "Перевод с карты",
        "direction": direction,
        "bank_amount": amount,
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "needs_review": True,
        "classification_source": "review_fallback",
        "rule_id": "",
    }


def anchors(df):
    return set(df["anchor"].tolist()) if not df.empty else set()


class PlanUiLogicTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_one_expense_rule_hides_only_selected_anchor(self):
        operations = pd.DataFrame(
            [
                op("М. Маргарита Георгиевна", -35000),
                op("Я. Александра Владимировна", -65000),
                op("З. Анна Сергеевна", 15000, "income"),
            ]
        )
        profile = {
            "plan_rules": [
                {
                    "id": "plan_margarita",
                    "enabled": True,
                    "match_contains_any": ["М. Маргарита Георгиевна"],
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

        expense_candidates = get_plan_review_candidates_from_operations(operations, "2026-05", 6, profile)
        income_candidates = get_income_review_candidates_from_operations(operations, "2026-05", 6, profile)

        self.assertNotIn("М. Маргарита Георгиевна", anchors(expense_candidates))
        self.assertIn("Я. Александра Владимировна", anchors(expense_candidates))
        self.assertIn("З. Анна Сергеевна", anchors(income_candidates))

    def test_transfer_from_anchor_forces_income_direction_in_saved_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_data_dir = storage.DATA_DIR
            old_profiles_dir = storage.PROFILES_DIR
            old_db_path = storage.DB_PATH
            storage.DATA_DIR = Path(tmp) / "data"
            storage.PROFILES_DIR = storage.DATA_DIR / "profiles"
            storage.DB_PATH = storage.DATA_DIR / "budget.sqlite3"
            profile_id = "test_profile"
            save_json(storage.profile_path(profile_id), {"id": profile_id, "name": "Test", "plan": {}, "income_plan": {}, "rules": []})
            try:
                upsert_plan_rule(
                    profile_id,
                    {
                        "id": "plan_wrong_direction",
                        "enabled": True,
                        "match_contains_any": ["Перевод от Ш. Семен Юрьевич"],
                        "direction": "expense",
                        "scenario": "regular_expense",
                        "operation_type": "Личный расход",
                        "budget_category": "Жильё",
                        "plan_category": "Жильё",
                        "budget_amount_mode": "abs",
                        "planning_amount_mode": "abs",
                    },
                )
                rules = load_json(storage.plan_rules_path(profile_id), [])
            finally:
                storage.DATA_DIR = old_data_dir
                storage.PROFILES_DIR = old_profiles_dir
                storage.DB_PATH = old_db_path

        self.assertEqual(rules[0]["direction"], "income")

    def test_income_compensation_rule_sets_negative_amounts_and_not_income(self):
        operations = pd.DataFrame([op("З. Анна Сергеевна", 15000, "income")])
        profile = {
            "plan_rules": [
                {
                    "id": "plan_anna_compensation",
                    "enabled": True,
                    "match_contains_any": ["З. Анна Сергеевна"],
                    "direction": "income",
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
        income_plan = build_auto_income_plan(planned, "2026-05", 6)

        self.assertEqual(planned.loc[0, "operation_type"], "Компенсация совместных расходов")
        self.assertEqual(planned.loc[0, "budget_amount"], -15000)
        self.assertEqual(planned.loc[0, "planning_amount"], -15000)
        self.assertTrue(income_plan.empty)

    def test_excluded_operations_are_not_plan_review_candidates(self):
        operations = pd.DataFrame([op("Свой счёт", -100000)])
        profile = {
            "plan_rules": [
                {
                    "id": "plan_internal",
                    "enabled": True,
                    "match_contains_any": ["Свой счёт"],
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

        self.assertTrue(candidates.empty)

    def test_raw_income_plan_keeps_unresolved_incoming_but_clean_income_does_not(self):
        operations = pd.DataFrame(
            [
                op("Неизвестный отправитель", 12000, "income"),
                {
                    **op("Работодатель", 78300, "income"),
                    "operation_type": "Личный доход",
                    "budget_category": "Зарплата / аванс / премия",
                    "personal_amount": 78300,
                    "needs_review": False,
                },
            ]
        )

        raw_income = build_raw_income_plan_from_operations(operations, "2026-05", 6, "median", 0, 100, {"plan_rules": []})
        clean_income = build_auto_income_plan(operations, "2026-05", 6)

        self.assertIn("Неразобранные поступления / проверить", set(raw_income["income_category"]))
        self.assertIn("Зарплата / аванс / премия", set(clean_income["income_category"]))
        self.assertNotIn("Неразобранные поступления / проверить", set(clean_income["income_category"]))


if __name__ == "__main__":
    unittest.main()
