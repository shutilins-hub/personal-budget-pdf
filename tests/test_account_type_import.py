import tempfile
import unittest
from pathlib import Path

try:
    import pandas as pd

    import storage
    from app import apply_account_context
    from reclassification import reclassify_operation
except ModuleNotFoundError:
    pd = None


def operation(description, amount, direction, operation_type="Проверить"):
    return {
        "id": description,
        "source_file": "statement.pdf",
        "description": description,
        "raw_description": description,
        "raw_category": "Прочие операции",
        "bank_amount": amount,
        "direction": direction,
        "operation_type": operation_type,
        "budget_category": "Прочее / проверить",
        "personal_amount": 0.0,
        "needs_review": True,
    }


class AccountTypeImportTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_credit_card_income_is_repayment_not_income_or_expense(self):
        rows = apply_account_context(
            [operation("Пополнение кредитной карты", 10000, "income")],
            {"account_type": "credit_card"},
        )

        self.assertEqual(rows[0]["account_type"], "credit_card")
        self.assertEqual(rows[0]["operation_type"], "Погашение кредита")
        self.assertEqual(rows[0]["budget_amount"], 0)
        self.assertFalse(rows[0]["count_in_budget"])

    def test_savings_account_operations_are_internal(self):
        rows = apply_account_context(
            [operation("Пополнение вклада", -50000, "expense")],
            {"account_type": "savings_account"},
        )

        self.assertEqual(rows[0]["operation_type"], "Внутренний перевод")
        self.assertEqual(rows[0]["budget_amount"], 0)
        self.assertFalse(rows[0]["count_in_plan"])

    def test_reclassification_preserves_account_context(self):
        op = operation("Пополнение кредитной карты", 10000, "income")
        op["account_type"] = "credit_card"
        profile = {"rules": [], "plan_rules": [], "source_files": {"statement.pdf": {"account_type": "credit_card"}}}

        updated = reclassify_operation(op, profile, preserve_manual_overrides=False)

        self.assertEqual(updated["operation_type"], "Погашение кредита")
        self.assertEqual(updated["budget_amount"], 0)


if __name__ == "__main__":
    unittest.main()
