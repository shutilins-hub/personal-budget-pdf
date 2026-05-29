import unittest

import pandas as pd

from ui_flow import (
    build_plan_accuracy,
    canonical_plan_category,
    is_income_plan_category,
    plan_accuracy_title,
    plan_mode_label,
    plan_status_label,
    recommendation_stage,
)


class PlanUxHelpersTest(unittest.TestCase):
    def test_plan_mode_labels_are_human(self):
        self.assertEqual(plan_mode_label("draft_all_history"), "Предварительная рекомендация")
        self.assertEqual(plan_mode_label("verified_months"), "Рекомендация по проверенной истории")

    def test_plan_accuracy_title_is_recommendation_not_plan(self):
        self.assertEqual(plan_accuracy_title(), "Точность рекомендации")
        self.assertNotEqual(plan_accuracy_title(), "Точность плана")

    def test_verified_progress_counts_clean_months(self):
        operations = pd.DataFrame(
            [
                {"operation_datetime": "2026-01-10", "needs_review": False, "bank_amount": -1000},
                {"operation_datetime": "2026-02-10", "needs_review": False, "bank_amount": -1000},
                {"operation_datetime": "2026-03-10", "needs_review": False, "bank_amount": -1000},
            ]
        )
        accuracy = build_plan_accuracy(operations, "2026-03")
        self.assertEqual(accuracy["verified_months"], 3)
        self.assertEqual(accuracy["current_month_status"], "готов")
        self.assertEqual(accuracy["recommendation_status"], "точная")
        self.assertEqual(recommendation_stage(accuracy), "accurate_available")

    def test_verified_progress_reports_current_month_review(self):
        operations = pd.DataFrame(
            [
                {"operation_datetime": "2026-04-10", "needs_review": False, "bank_amount": -1000},
                {"operation_datetime": "2026-05-10", "needs_review": True, "bank_amount": -2500},
            ]
        )
        accuracy = build_plan_accuracy(operations, "2026-05")
        self.assertEqual(accuracy["current_month_status"], "требует проверки")
        self.assertEqual(accuracy["review_count"], 1)
        self.assertEqual(accuracy["review_amount"], 2500)
        self.assertEqual(accuracy["recommendation_status"], "предварительная")
        self.assertEqual(recommendation_stage(accuracy), "preliminary")

    def test_zero_verified_months_means_preliminary_recommendation(self):
        operations = pd.DataFrame(
            [
                {"operation_datetime": "2026-05-10", "needs_review": True, "bank_amount": -1000},
            ]
        )
        accuracy = build_plan_accuracy(operations, "2026-05")
        self.assertEqual(accuracy["verified_months"], 0)
        self.assertEqual(accuracy["recommendation_status"], "предварительная")
        self.assertEqual(recommendation_stage(accuracy), "preliminary")

    def test_canonical_plan_categories_map_old_expense_labels(self):
        self.assertEqual(canonical_plan_category("Продукты / супермаркеты"), "Продукты")
        self.assertEqual(canonical_plan_category("Кафе / доставка / рестораны"), "Кафе и доставка")
        self.assertEqual(canonical_plan_category("Психолог / терапия"), "Здоровье")
        self.assertEqual(canonical_plan_category("Дом / одежда / бытовое"), "Дом и быт")
        self.assertEqual(canonical_plan_category("Связь / интернет / подписки"), "Связь и подписки")
        self.assertEqual(canonical_plan_category("Кредиты / проценты / комиссии"), "Документы и обязательные платежи")

    def test_canonical_plan_categories_map_old_income_labels(self):
        self.assertEqual(canonical_plan_category("Зарплата / аванс / премия", "income"), "Зарплата")
        self.assertEqual(canonical_plan_category("Доп. доход / проекты", "income"), "Доход от бизнеса / проектов")
        self.assertEqual(canonical_plan_category("Возврат налога / кешбэк", "income"), "Разовые поступления")

    def test_plan_status_labels_are_human(self):
        self.assertEqual(plan_status_label("ready"), "достаточно истории")
        self.assertEqual(plan_status_label("low_history"), "мало истории")
        self.assertEqual(plan_status_label("needs_review"), "нужно разобрать")
        self.assertEqual(plan_status_label("needs_classification"), "нужно разобрать")

    def test_unresolved_income_is_not_plan_category(self):
        self.assertFalse(is_income_plan_category("Неразобранные поступления / проверить"))
        self.assertFalse(is_income_plan_category("Проверить доход"))
        self.assertTrue(is_income_plan_category("Зарплата / аванс / премия"))


if __name__ == "__main__":
    unittest.main()
