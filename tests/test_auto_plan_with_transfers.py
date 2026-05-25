import unittest

try:
    import pandas as pd
    from planner import build_auto_expense_plan, plan_coverage_score
except ModuleNotFoundError:
    pd = None
    build_auto_expense_plan = None
    plan_coverage_score = None


def operation(month, description, amount, direction, operation_type="Проверить", category="Прочее / проверить"):
    return {
        "id": f"{month}-{description[:8]}-{amount}",
        "operation_datetime": f"{month}-10T10:00:00",
        "description": description,
        "normalized_description": description.casefold(),
        "merchant_anchor": "",
        "person_anchor": "",
        "raw_category": "Перевод СБП" if "Перевод" in description else "",
        "direction": direction,
        "bank_amount": amount,
        "operation_type": operation_type,
        "budget_category": category,
        "personal_amount": abs(amount) if operation_type == "Личный расход" else 0,
    }


class AutoPlanWithTransfersTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_rent_compensation_and_project_transfers(self):
        profile = {
            "plan_rules": [
                {
                    "id": "rent_alexandra",
                    "enabled": True,
                    "match_contains_any": ["Я. АЛЕКСАНДРА ВЛАДИМИРОВНА", "Александра Владимировна"],
                    "direction": "expense",
                    "operation_type": "Личный расход",
                    "budget_category": "Жильё",
                    "plan_category": "Жильё",
                    "budget_amount_mode": "abs",
                    "planning_amount_mode": "abs",
                },
                {
                    "id": "anna_compensation",
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
                    "id": "margarita_project",
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
            ]
        }
        rows = []
        for month, grocery in [("2026-02", 30000), ("2026-03", 32000), ("2026-04", 31000)]:
            rows.extend(
                [
                    operation(month, "Продукты", -grocery, "expense", "Личный расход", "Продукты / супермаркеты"),
                    operation(month, "Перевод для Я. АЛЕКСАНДРА ВЛАДИМИРОВНА", -65000, "expense"),
                    operation(month, "Перевод от З. Анна Сергеевна", 15000, "income"),
                    operation(month, "Перевод для Маргарита проект", -35000 if month == "2026-02" else -20000, "expense"),
                    operation(month, "SBERBANK ONL@IN KARTA-VKLAD", -100000, "expense", "Внутренний перевод", "Не учитывать"),
                ]
            )
        operations = pd.DataFrame(rows)

        plan = build_auto_expense_plan(operations, "2026-05", history_months=3, buffer_percent=0, round_to=1000, profile=profile)
        plan_by_category = dict(zip(plan["budget_category"], plan["suggested_plan"]))

        self.assertEqual(plan_by_category["Продукты / супермаркеты"], 31000)
        self.assertEqual(plan_by_category["Жильё"], 50000)
        self.assertNotIn("Маргарита", " ".join(plan["budget_category"].astype(str)))
        self.assertGreaterEqual(sum(plan_by_category.values()), 81000)

    def test_low_coverage_when_regular_transfer_is_unmarked(self):
        operations = pd.DataFrame(
            [
                operation("2026-04", "Продукты", -30000, "expense", "Личный расход", "Продукты / супермаркеты"),
                operation("2026-04", "Перевод для Я. АЛЕКСАНДРА ВЛАДИМИРОВНА", -65000, "expense"),
            ]
        )

        coverage = plan_coverage_score(operations, "2026-05", history_months=3, profile={"plan_rules": []})

        self.assertLess(coverage["coverage"], 0.8)
        self.assertEqual(coverage["unknown_count"], 1)


if __name__ == "__main__":
    unittest.main()
