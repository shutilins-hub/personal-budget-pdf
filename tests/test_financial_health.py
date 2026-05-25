import unittest
from datetime import date

try:
    import pandas as pd
    from financial_health import build_financial_health_report
except ModuleNotFoundError:
    pd = None
    build_financial_health_report = None


def op(amount, category="Продукты / супермаркеты", operation_type="Личный расход", needs_review=False, direction="expense"):
    budget_amount = abs(amount)
    if operation_type == "Компенсация совместных расходов":
        budget_amount = -abs(amount)
    if operation_type not in {"Личный расход", "Расход из фонда", "Компенсация совместных расходов", "Личный доход"}:
        budget_amount = 0
    return {
        "id": f"{amount}-{category}-{operation_type}",
        "profile_id": "p1",
        "operation_datetime": "2026-05-10T10:00:00",
        "bank_amount": amount if direction == "income" else -abs(amount),
        "direction": direction,
        "description": "test",
        "operation_type": operation_type,
        "budget_category": category,
        "plan_category": category,
        "budget_amount": budget_amount,
        "personal_amount": budget_amount,
        "needs_review": needs_review,
    }


def income(amount):
    return op(amount, "Зарплата / аванс / премия", "Личный доход", False, "income")


def plan(amount=100000, extra=None):
    rows = [{"budget_category": "Продукты / супермаркеты", "plan": amount}]
    if extra:
        rows.extend(extra)
    return pd.DataFrame(rows)


class FinancialHealthTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def report(self, operations, plan_df=None, today=date(2026, 5, 15)):
        return build_financial_health_report("p1", "2026-05", pd.DataFrame(operations), plan() if plan_df is None else plan_df, today=today)

    def test_normal_month(self):
        report = self.report([op(50000), income(100000)])
        self.assertEqual(report["month_status"], "В норме")

    def test_fast_spending_is_warning(self):
        report = self.report([op(85000), income(100000)])
        self.assertEqual(report["month_status"], "Напряжённо")

    def test_overspent(self):
        report = self.report([op(110000), income(140000)])
        self.assertEqual(report["month_status"], "Перерасход")

    def test_income_ratio_danger(self):
        report = self.report([op(90000), income(80000)])
        self.assertEqual(report["income_expense_ratio"]["status"], "danger")
        self.assertTrue(any(item["action_target"] == "income" for item in report["recommendations"]))

    def test_many_review_operations_make_incomplete(self):
        operations = [op(100, needs_review=True) for _ in range(50)]
        report = self.report(operations)
        self.assertLess(report["data_quality"]["confidence_score"], 60)
        self.assertEqual(report["month_status"], "Расчёт неполный")

    def test_category_without_limit(self):
        report = self.report(
            [op(10000, "Жильё")],
            plan(0, [{"budget_category": "Жильё", "plan": 0}]),
        )
        self.assertTrue(any(risk["status"] == "no_limit" for risk in report["category_risks"]))

    def test_safe_per_day(self):
        report = self.report([op(85000), income(100000)], today=date(2026, 5, 16))
        self.assertEqual(report["safe_to_spend"]["total_left"], 15000)
        self.assertEqual(report["safe_to_spend"]["per_day"], 1000)


if __name__ == "__main__":
    unittest.main()
