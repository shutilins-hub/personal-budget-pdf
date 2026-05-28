import unittest
from datetime import date

try:
    import pandas as pd
    from financial_health import build_financial_health_report
except ModuleNotFoundError:
    pd = None
    build_financial_health_report = None


def expense(
    amount,
    category="Продукты / супермаркеты",
    operation_type="Личный расход",
    needs_review=False,
    idx=0,
):
    budget_amount = abs(amount) if operation_type in {"Личный расход", "Расход из фонда"} else 0
    return {
        "id": f"expense-{idx}-{amount}-{category}-{operation_type}",
        "profile_id": "p1",
        "operation_datetime": "2026-05-10T10:00:00",
        "bank_amount": -abs(amount),
        "direction": "expense",
        "description": "synthetic expense",
        "operation_type": operation_type,
        "budget_category": category,
        "plan_category": category,
        "budget_amount": budget_amount,
        "personal_amount": budget_amount,
        "needs_review": needs_review,
    }


def income(amount, operation_type="Личный доход", needs_review=False, idx=0):
    budget_amount = abs(amount) if operation_type == "Личный доход" else 0
    category = "Зарплата / аванс / премия" if operation_type == "Личный доход" else "Проверить доход"
    return {
        "id": f"income-{idx}-{amount}-{operation_type}",
        "profile_id": "p1",
        "operation_datetime": "2026-05-12T10:00:00",
        "bank_amount": abs(amount),
        "direction": "income",
        "description": "synthetic income",
        "operation_type": operation_type,
        "budget_category": category,
        "plan_category": category,
        "budget_amount": budget_amount,
        "personal_amount": budget_amount,
        "needs_review": needs_review,
    }


def review_expense(amount, idx=0, category="Неразобранные переводы / проверить"):
    return expense(amount, category=category, operation_type="Проверить", needs_review=True, idx=idx)


def review_income(amount, idx=0):
    return income(amount, operation_type="Проверить", needs_review=True, idx=idx)


def plan(rows=None):
    return pd.DataFrame(rows or [{"budget_category": "Продукты / супермаркеты", "plan": 100000}])


class FinancialHealthConfidenceTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def report(self, operations, plan_df=None):
        return build_financial_health_report(
            "p1",
            "2026-05",
            pd.DataFrame(operations),
            plan() if plan_df is None else plan_df,
            today=date(2026, 5, 15),
        )

    def test_clean_data_has_high_confidence(self):
        report = self.report([expense(40000), income(120000)])

        self.assertGreaterEqual(report["data_quality"]["confidence_score"], 85)
        self.assertNotIn(report["month_status"], {"Расчёт предварительный", "Расчёт неполный"})
        self.assertFalse(any(item["action_target"] == "cleanup" for item in report["recommendations"]))

    def test_many_review_operations_make_assessment_incomplete(self):
        operations = [review_expense(300, idx=i) for i in range(25)] + [income(80000)]

        report = self.report(operations)

        self.assertLess(report["data_quality"]["confidence_score"], 60)
        self.assertIn(report["month_status"], {"Расчёт неполный", "Расчёт предварительный"})
        self.assertTrue(any(item["action_target"] == "cleanup" for item in report["recommendations"]))

    def test_large_unresolved_transfers_reduce_confidence(self):
        operations = [expense(10000), review_expense(50000), income(100000)]

        report = self.report(operations)

        self.assertLess(report["data_quality"]["confidence_score"], 85)
        self.assertGreater(report["data_quality"]["unresolved_transfers_amount"], 0)
        self.assertTrue(any(item["action_target"] == "cleanup" for item in report["recommendations"]))

    def test_category_with_fact_and_zero_plan_is_no_limit_risk(self):
        report = self.report(
            [expense(10000, category="Жильё"), income(90000)],
            pd.DataFrame([{"budget_category": "Жильё", "plan": 0}]),
        )

        risks = [risk for risk in report["category_risks"] if risk["category"] == "Жильё"]
        self.assertTrue(risks)
        self.assertEqual(risks[0]["status"], "no_limit")
        self.assertNotEqual(risks[0]["status"], "ok")
        self.assertTrue(any(item["action_target"] == "plan" for item in report["recommendations"]))

    def test_unknown_income_makes_income_and_balance_cautious(self):
        operations = [expense(10000), review_income(30000)]

        report = self.report(operations)

        self.assertLess(report["data_quality"]["confidence_score"], 85)
        self.assertGreater(report["data_quality"]["income_unknown_amount"], 0)
        self.assertTrue(any(item["action_target"] == "income" for item in report["recommendations"]))
        self.assertIn("доход", report["summary_text"].lower())

    def test_no_month_plan_is_reported_as_limited_assessment(self):
        empty_plan = pd.DataFrame(columns=["budget_category", "plan"])

        report = self.report([expense(12000), income(80000)], empty_plan)

        self.assertEqual(report["key_metrics"]["month_plan"], 0)
        self.assertIn("План месяца не задан", report["summary_text"])
        self.assertNotIn("Темп расходов в норме", report["summary_text"])
        self.assertTrue(any(item["action_target"] == "plan" for item in report["recommendations"]))

    def test_expenses_above_income_get_danger_recommendation(self):
        report = self.report([expense(90000), income(50000)])

        self.assertEqual(report["income_expense_ratio"]["status"], "danger")
        self.assertTrue(
            any(item["severity"] == "danger" and item["action_target"] == "income" for item in report["recommendations"])
        )


if __name__ == "__main__":
    unittest.main()
