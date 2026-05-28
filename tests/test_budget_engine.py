import unittest

try:
    import pandas as pd
    from budget_engine import dashboard_metrics, financial_health_assessment, plan_fact
except ModuleNotFoundError:
    pd = None
    dashboard_metrics = None
    financial_health_assessment = None
    plan_fact = None



class BudgetEngineTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_dashboard_net_expense_with_compensation(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Личный доход", "budget_category": "Зарплата", "personal_amount": 78300, "needs_review": False},
                {"operation_type": "Личный расход", "budget_category": "Жильё", "personal_amount": 65000, "needs_review": False},
                {"operation_type": "Компенсация совместных расходов", "budget_category": "Жильё", "personal_amount": -15000, "needs_review": False},
            ]
        )

        metrics = dashboard_metrics(operations, monthly_limit=100000)

        self.assertEqual(metrics["personal_income"], 78300)
        self.assertEqual(metrics["gross_expense"], 65000)
        self.assertEqual(metrics["compensation"], -15000)
        self.assertEqual(metrics["net_expense"], 50000)
        self.assertEqual(metrics["balance"], 28300)

    def test_plan_fact_compensation_reduces_category_fact(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Личный расход", "budget_category": "Жильё", "personal_amount": 65000},
                {"operation_type": "Компенсация совместных расходов", "budget_category": "Жильё", "personal_amount": -15000},
            ]
        )
        plan = pd.DataFrame([{"budget_category": "Жильё", "suggested_plan": 65000}])

        result = plan_fact(operations, plan)

        self.assertEqual(result.loc[result["budget_category"] == "Жильё", "fact"].iloc[0], 50000)

    def test_compensation_is_not_personal_income(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Компенсация совместных расходов", "budget_category": "Жильё", "personal_amount": -15000, "needs_review": False},
            ]
        )

        metrics = dashboard_metrics(operations)

        self.assertEqual(metrics["personal_income"], 0)
        self.assertEqual(metrics["compensation"], -15000)

    def test_loan_return_is_not_personal_income(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Возврат займа", "budget_category": "Не учитывать", "personal_amount": 0, "needs_review": False},
            ]
        )

        metrics = dashboard_metrics(operations)
        plan = pd.DataFrame(columns=["budget_category", "suggested_plan"])

        self.assertEqual(metrics["personal_income"], 0)
        self.assertEqual(metrics["net_expense"], 0)
        self.assertEqual(plan_fact(operations, plan).empty, True)

    def test_lent_money_is_not_personal_expense(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Заём выдан", "budget_category": "Не учитывать", "personal_amount": 0, "needs_review": False},
            ]
        )

        metrics = dashboard_metrics(operations)

        self.assertEqual(metrics["gross_expense"], 0)
        self.assertEqual(metrics["net_expense"], 0)

    def test_project_turnover_is_outside_personal_budget(self):
        operations = pd.DataFrame(
            [
                {"operation_type": "Проектный оборот", "budget_category": "Не учитывать", "personal_amount": 0, "needs_review": False},
                {"operation_type": "Проектный приход", "budget_category": "Не учитывать", "personal_amount": 0, "needs_review": False},
                {"operation_type": "Проектный расход", "budget_category": "Не учитывать", "personal_amount": 0, "needs_review": False},
            ]
        )

        metrics = dashboard_metrics(operations)

        self.assertEqual(metrics["personal_income"], 0)
        self.assertEqual(metrics["gross_expense"], 0)
        self.assertEqual(metrics["net_expense"], 0)

    def test_financial_health_assessment_flags_review_before_status(self):
        metrics = {
            "personal_income": 100000,
            "net_expense": 50000,
            "balance": 50000,
            "limit": 90000,
        }

        health = financial_health_assessment(metrics, days_elapsed=15, days_in_month=30, review_count=12)

        self.assertEqual(health["status"], "Данные требуют проверки")
        self.assertIn("12 операций", health["message"])


if __name__ == "__main__":
    unittest.main()
