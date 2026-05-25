import tempfile
import unittest
from pathlib import Path

try:
    import pandas as pd

    import storage
    from classifier import classify_operations
    from planner import build_auto_expense_plan, plan_coverage_score, prepare_planning_dataframe
    from reclassification import reclassify_profile_operations
    from storage import insert_operations, operations_df, save_json, save_plan_rules
except ModuleNotFoundError:
    pd = None


def op(profile_id, month, description, amount, direction, raw_category="Перевод СБП"):
    return {
        "id": f"{month}-{abs(hash(description + str(amount))) % 100000000}",
        "profile_id": profile_id,
        "bank": "Сбер",
        "source_file": "test.pdf",
        "operation_datetime": f"{month}-10T10:00:00",
        "processing_date": f"{month}-10",
        "description": description,
        "raw_description": description,
        "raw_category": raw_category,
        "bank_amount": amount,
        "direction": direction,
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "needs_review": True,
        "rule_id": "",
        "comment": "",
    }


class ReclassificationAndPlanTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = storage.DATA_DIR
        self.old_profiles_dir = storage.PROFILES_DIR
        self.old_db_path = storage.DB_PATH
        storage.DATA_DIR = Path(self.tmp.name) / "data"
        storage.PROFILES_DIR = storage.DATA_DIR / "profiles"
        storage.DB_PATH = storage.DATA_DIR / "budget.sqlite3"
        self.profile_id = "test_profile"
        save_json(
            storage.profile_path(self.profile_id),
            {
                "id": self.profile_id,
                "name": "Test",
                "monthly_limit": 43000,
                "plan": {"Продукты / супермаркеты": 43000},
                "income_plan": {},
                "rules": [],
            },
        )

    def tearDown(self):
        storage.DATA_DIR = self.old_data_dir
        storage.PROFILES_DIR = self.old_profiles_dir
        storage.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def test_reclassification_applies_plan_rules_to_existing_operations(self):
        rows = []
        for month in ["2026-02", "2026-03", "2026-04"]:
            rows.extend(
                [
                    op(self.profile_id, month, "Заработная плата", 78300, "income", "Прочие операции"),
                    op(self.profile_id, month, "Перевод для Я. Александра Владимировна", -65000, "expense"),
                    op(self.profile_id, month, "Перевод от З. Анна Сергеевна", 15000, "income"),
                    op(self.profile_id, month, "SAMOKAT MOSCOW RUS. Операция по карте ****0000", -10000, "expense", "Прочие расходы"),
                    op(self.profile_id, month, "Перевод для Маргарита проект", -35000, "expense"),
                    op(self.profile_id, month, "SBERBANK ONL@IN KARTA-VKLAD. Операция по счету ****0000", -100000, "expense", "Прочие операции"),
                ]
            )
        classified = classify_operations(rows, {"rules": []})
        planned = prepare_planning_dataframe(pd.DataFrame(classified), {"plan_rules": []}).to_dict("records")
        insert_operations(planned)

        before = operations_df(self.profile_id)
        before_coverage = plan_coverage_score(before, "2026-05", 3, {"plan_rules": []})
        self.assertLess(before_coverage["coverage"], 0.8)

        save_plan_rules(
            self.profile_id,
            [
                {
                    "id": "rent",
                    "enabled": True,
                    "match_contains_any": ["Я. Александра Владимировна"],
                    "direction": "expense",
                    "operation_type": "Личный расход",
                    "budget_category": "Жильё",
                    "plan_category": "Жильё",
                    "budget_amount_mode": "abs",
                    "planning_amount_mode": "abs",
                },
                {
                    "id": "anna",
                    "enabled": True,
                    "match_contains_any": ["Перевод от З. Анна Сергеевна"],
                    "direction": "income",
                    "operation_type": "Компенсация совместных расходов",
                    "budget_category": "Жильё",
                    "plan_category": "Жильё",
                    "budget_amount_mode": "-abs",
                    "planning_amount_mode": "-abs",
                },
                {
                    "id": "margarita",
                    "enabled": True,
                    "match_contains_any": ["Маргарита"],
                    "operation_type": "Не учитывать",
                    "budget_category": "Не учитывать",
                    "plan_category": "Не учитывать",
                    "budget_amount_mode": "0",
                    "planning_amount_mode": "0",
                    "count_in_budget": False,
                    "count_in_plan": False,
                },
            ],
        )

        stats = reclassify_profile_operations(self.profile_id)
        after = operations_df(self.profile_id)
        plan = build_auto_expense_plan(after, "2026-05", 3, "median", 0, 1000, storage.load_profile(self.profile_id))
        plan_by_category = dict(zip(plan["budget_category"], plan["suggested_plan"]))
        housing_fact = after[after["plan_category"] == "Жильё"]["planning_amount"].sum() / 3
        margarita = after[after["description"].str.contains("Маргарита")]
        internal = after[after["description"].str.contains("KARTA-VKLAD")]

        self.assertGreater(stats["changed"], 0)
        self.assertEqual(housing_fact, 50000)
        self.assertEqual(plan_by_category["Жильё"], 50000)
        self.assertEqual(plan_by_category["Продукты / супермаркеты"], 10000)
        self.assertTrue((margarita["count_in_plan"] == False).all())
        self.assertTrue((internal["count_in_plan"] == False).all())
        self.assertGreaterEqual(sum(plan_by_category.values()), 60000)


if __name__ == "__main__":
    unittest.main()
