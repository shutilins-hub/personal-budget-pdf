import unittest

try:
    import pandas as pd
    from planner import build_layered_plan_from_operations
except ModuleNotFoundError:
    pd = None
    build_layered_plan_from_operations = None


def row(date_text, operation_type, category, amount, **extra):
    data = {
        "id": f"{date_text}-{operation_type}-{category}-{amount}",
        "operation_datetime": date_text,
        "operation_type": operation_type,
        "budget_category": category,
        "plan_category": category,
        "personal_amount": amount,
        "budget_amount": amount,
        "planning_amount": amount if operation_type in {"Личный расход", "Компенсация совместных расходов", "credit_purchase"} else 0,
        "count_in_plan": operation_type in {"Личный расход", "Компенсация совместных расходов", "credit_purchase"},
        "count_in_budget": operation_type not in {"Внутренний перевод", "Не учитывать"},
        "bank_amount": -abs(amount) if amount >= 0 else amount,
        "direction": "expense",
        "description": category,
        "source_file": "test.pdf",
    }
    data.update(extra)
    return data


class PlanLayersTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def build(self, rows, profile=None):
        return build_layered_plan_from_operations(
            pd.DataFrame(rows),
            "2026-05",
            history_months=3,
            strategy="median",
            buffer_percent=0,
            round_to=100,
            profile=profile or {},
        )

    def test_layers_basic_unresolved_and_internal(self):
        summary, _, _ = self.build(
            [
                row("2026-04-01T10:00:00", "Личный расход", "Продукты / супермаркеты", 12000),
                row("2026-04-02T10:00:00", "Личный расход", "Кафе / доставка / рестораны", 2000),
                row("2026-04-03T10:00:00", "Личный расход", "Транспорт", 1000),
                row("2026-04-04T10:00:00", "Проверить", "Неразобранные переводы / проверить", 0, bank_amount=-24000, count_in_budget=False, count_in_plan=False),
                row("2026-04-05T10:00:00", "debt_repayment", "Кредиты / проценты / комиссии", 0, bank_amount=-35000, debt_amount=35000, count_in_budget=False, count_in_plan=False),
                row("2026-04-06T10:00:00", "Внутренний перевод", "Не учитывать", 0, bank_amount=-100000, count_in_budget=False, count_in_plan=False),
            ]
        )
        self.assertEqual(summary.base_living_plan, 15000)
        self.assertEqual(summary.obligations_plan, 35000)
        self.assertEqual(summary.unresolved_plan, 24000)
        self.assertEqual(summary.recommended_total, 74000)

    def test_credit_purchase_and_repayment_not_doubled(self):
        summary, _, _ = self.build(
            [
                row("2026-04-01T10:00:00", "credit_purchase", "Дом / ремонт / бытовое", 20000, account_type="credit_card"),
                row("2026-04-02T10:00:00", "debt_repayment", "Кредиты / проценты / комиссии", 0, bank_amount=-20000, debt_amount=20000, account_type="credit_card", count_in_plan=False),
            ]
        )
        self.assertEqual(summary.base_living_plan, 20000)
        self.assertEqual(summary.obligations_plan, 0)
        self.assertEqual(summary.recommended_total, 20000)

    def test_wallet_topup_excluded_purchase_included(self):
        summary, _, _ = self.build(
            [
                row("2026-04-01T10:00:00", "wallet_topup", "Не учитывать", 0, bank_amount=10000, direction="income", account_type="wallet", count_in_plan=False),
                row("2026-04-02T10:00:00", "Личный расход", "Маркетплейсы", 9500, account_type="marketplace_wallet"),
            ]
        )
        self.assertEqual(summary.base_living_plan, 9500)
        self.assertEqual(summary.recommended_total, 9500)

    def test_owner_mismatch_warning(self):
        profile = {
            "own_identity": {"full_name": "Шутилин Семен Юрьевич"},
            "source_files": {"nikita.pdf": {"owner_name": "Шутилин Никита Юрьевич"}},
        }
        summary, _, _ = self.build([row("2026-04-01T10:00:00", "Личный расход", "Продукты / супермаркеты", 1000, source_file="nikita.pdf")], profile)
        self.assertIn("owner_mismatch_files", summary.warnings)

    def test_current_incomplete_month_excluded(self):
        summary, _, _ = self.build(
            [
                row("2026-04-01T10:00:00", "Личный расход", "Продукты / супермаркеты", 1000),
                row("2026-05-15T10:00:00", "Личный расход", "Продукты / супермаркеты", 99999),
            ]
        )
        self.assertEqual(summary.base_living_plan, 1000)
        self.assertIn("2026-05", summary.partial_months_excluded)

    def test_high_unresolved_warning(self):
        summary, _, _ = self.build(
            [
                row("2026-04-01T10:00:00", "Личный расход", "Продукты / супермаркеты", 1000),
                row("2026-04-04T10:00:00", "Проверить", "Неразобранные переводы / проверить", 0, bank_amount=-24000, count_in_budget=False, count_in_plan=False),
            ]
        )
        self.assertIn("high_unresolved_transfers", summary.warnings)


if __name__ == "__main__":
    unittest.main()
