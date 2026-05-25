import unittest

try:
    import pandas as pd
    from planner import build_auto_expense_plan, build_auto_income_plan
except ModuleNotFoundError:
    pd = None
    build_auto_expense_plan = None
    build_auto_income_plan = None


def row(date_text, operation_type, category, amount):
    return {
        "operation_datetime": date_text,
        "operation_type": operation_type,
        "budget_category": category,
        "personal_amount": amount,
    }


class PlannerTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_auto_plan_excludes_current_incomplete_month(self):
        operations = pd.DataFrame(
            [
                row("2026-04-10T10:00:00", "Личный расход", "Продукты / супермаркеты", 1000),
                row("2026-05-10T10:00:00", "Личный расход", "Продукты / супермаркеты", 99999),
            ]
        )

        plan = build_auto_expense_plan(operations, "2026-05", history_months=3, buffer_percent=0, round_to=100)

        self.assertEqual(plan.loc[0, "suggested_plan"], 1000)

    def test_auto_plan_excludes_fund_expenses(self):
        operations = pd.DataFrame(
            [
                row("2026-04-10T10:00:00", "Личный расход", "Здоровье / аптеки", 1000),
                row("2026-04-11T10:00:00", "Расход из фонда", "Здоровье / аптеки", 50000),
            ]
        )

        plan = build_auto_expense_plan(operations, "2026-05", history_months=3, buffer_percent=0, round_to=100)

        self.assertEqual(plan.loc[0, "suggested_plan"], 1000)

    def test_compensation_reduces_category_plan_basis(self):
        operations = pd.DataFrame(
            [
                row("2026-04-10T10:00:00", "Личный расход", "Жильё", 65000),
                row("2026-04-11T10:00:00", "Компенсация совместных расходов", "Жильё", -15000),
            ]
        )

        plan = build_auto_expense_plan(operations, "2026-05", history_months=3, buffer_percent=0, round_to=100)

        self.assertEqual(plan.loc[0, "median"], 50000)
        self.assertEqual(plan.loc[0, "suggested_plan"], 50000)

    def test_income_plan_ignores_compensation_and_loan_returns(self):
        operations = pd.DataFrame(
            [
                row("2026-04-10T10:00:00", "Личный доход", "Зарплата / аванс / премия", 100000),
                row("2026-04-11T10:00:00", "Компенсация совместных расходов", "Жильё", -15000),
                row("2026-04-12T10:00:00", "Возврат займа", "Прочее / проверить", 0),
            ]
        )

        plan = build_auto_income_plan(operations, "2026-05", history_months=3)

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan.loc[0, "income_category"], "Зарплата / аванс / премия")
        self.assertEqual(plan.loc[0, "suggested_plan"], 100000)


if __name__ == "__main__":
    unittest.main()
