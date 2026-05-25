import unittest

try:
    import pandas as pd
    from planner import build_auto_expense_plan, build_raw_auto_plan_from_operations, plan_coverage_score
except ModuleNotFoundError:
    pd = None
    build_auto_expense_plan = None
    build_raw_auto_plan_from_operations = None
    plan_coverage_score = None


def operation(month, description, amount, raw_category, operation_type="Проверить", category="Прочее / проверить"):
    personal_amount = abs(amount) if operation_type == "Личный расход" else 0
    return {
        "id": f"{month}-{description[:12]}-{amount}",
        "operation_datetime": f"{month}-10T10:00:00",
        "description": description,
        "raw_description": description,
        "normalized_description": description.casefold(),
        "merchant_anchor": "",
        "person_anchor": "",
        "raw_category": raw_category,
        "direction": "expense",
        "bank_amount": amount,
        "operation_type": operation_type,
        "budget_category": category,
        "personal_amount": personal_amount,
    }


class RawAutoPlanTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_raw_plan_includes_unknown_transfers_and_excludes_internal(self):
        rows = []
        for month in ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]:
            rows.extend(
                [
                    operation(month, "Покупки в супермаркете", -14000, "Супермаркеты", "Личный расход", "Продукты / супермаркеты"),
                    operation(month, "Кафе рядом с домом", -3000, "Рестораны и кафе", "Личный расход", "Кафе / доставка / рестораны"),
                    operation(month, "Автомобильные расходы", -6000, "Автомобиль", "Личный расход", "Авто / каршеринг"),
                    operation(month, "Городской транспорт", -1500, "Транспорт", "Личный расход", "Транспорт"),
                    operation(month, "Перевод для регулярного получателя", -60000, "Перевод СБП"),
                    operation(month, "Перевод между своими счетами", -100000, "Прочие операции", "Внутренний перевод", "Не учитывать"),
                    operation(month, "SBERBANK ONL@IN KARTA-VKLAD", -50000, "Прочие операции"),
                ]
            )
        operations = pd.DataFrame(rows)

        raw_plan = build_raw_auto_plan_from_operations(
            operations,
            "2026-05",
            history_months=6,
            strategy="median",
            buffer_percent=0,
            round_to=500,
            profile={"plan_rules": []},
        )
        raw_by_category = dict(zip(raw_plan["budget_category"], raw_plan["suggested_plan"]))

        self.assertEqual(raw_by_category["Продукты / супермаркеты"], 14000)
        self.assertEqual(raw_by_category["Кафе / доставка / рестораны"], 3000)
        self.assertEqual(raw_by_category["Авто / каршеринг"], 6000)
        self.assertEqual(raw_by_category["Транспорт"], 1500)
        self.assertEqual(raw_by_category["Неразобранные переводы / проверить"], 60000)
        self.assertNotIn("Не учитывать", raw_by_category)
        self.assertEqual(sum(raw_by_category.values()), 84500)

        transfer_row = raw_plan[raw_plan["budget_category"] == "Неразобранные переводы / проверить"].iloc[0]
        self.assertEqual(transfer_row["status"], "needs_classification")

        clean_plan = build_auto_expense_plan(
            operations,
            "2026-05",
            history_months=6,
            strategy="median",
            buffer_percent=0,
            round_to=500,
            profile={"plan_rules": []},
        )
        self.assertLess(clean_plan["suggested_plan"].sum(), raw_plan["suggested_plan"].sum())
        coverage = plan_coverage_score(operations, "2026-05", 6, {"plan_rules": []})
        self.assertLess(coverage["coverage"], 0.8)


if __name__ == "__main__":
    unittest.main()
