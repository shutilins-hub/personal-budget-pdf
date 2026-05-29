from __future__ import annotations

import unittest

import pandas as pd

from ui_flow import (
    cleanup_apply_options,
    cleanup_cta_label,
    cleanup_group_focus_action,
    cleanup_primary_focus,
    cleanup_rule_summary,
    compensation_display_amount,
    default_income_cleanup_scenario,
    offer_rule_before_operation,
    split_summary_text,
)


class CleanupUxHelpersTest(unittest.TestCase):
    def test_cta_labels_are_contextual(self) -> None:
        self.assertEqual(
            cleanup_cta_label({"direction": "income", "person_anchor": "Анна"}, "income"),
            "Показать поступления",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "merchant_anchor": "ИП Кабачков"}, "expense"),
            "Показать операции",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "person_anchor": "Анна", "count": 3}, "expense"),
            "Показать операции месяца",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "description": "Разовая операция", "count": 1}, "expense"),
            "Показать операции месяца",
        )

    def test_cleanup_primary_focus_prefers_month_rows(self) -> None:
        operations = pd.DataFrame([{"needs_review": True}, {"needs_review": False}])
        groups = pd.DataFrame([{"anchor": "Анна"}])

        self.assertEqual(cleanup_primary_focus(operations, groups), "month_rows")
        self.assertEqual(cleanup_primary_focus(pd.DataFrame([{"needs_review": False}]), groups), "recurring_hints")
        self.assertEqual(cleanup_primary_focus(pd.DataFrame([{"needs_review": False}]), pd.DataFrame()), "done")

    def test_group_cta_has_real_focus_action_or_is_hidden(self) -> None:
        action = cleanup_group_focus_action({"anchor": "ИП Кабачков"})

        self.assertEqual(action, {"target": "month_rows", "anchor": "ИП Кабачков"})
        self.assertIsNone(cleanup_group_focus_action({"anchor": ""}))

    def test_rules_are_not_offered_before_operation_decision(self) -> None:
        self.assertFalse(offer_rule_before_operation())

    def test_apply_options_do_not_include_current_month_similar(self) -> None:
        person_options = cleanup_apply_options({"person_anchor": "Анна"})
        merchant_options = cleanup_apply_options({"merchant_anchor": "ИП Кабачков"})

        self.assertEqual(person_options, ["Только эта операция"])
        self.assertEqual(merchant_options, ["Только эта операция", "Всегда для этого магазина / сервиса"])
        self.assertNotIn("Похожие операции этого месяца", person_options + merchant_options)

    def test_amount_rule_option_is_explicit_when_supported(self) -> None:
        options = cleanup_apply_options({"person_anchor": "Анна"}, amount_rule_supported=True)

        self.assertEqual(options, ["Только эта операция", "Запомнить для этого человека и похожей суммы"])

    def test_summary_texts_are_human_readable(self) -> None:
        self.assertIn(
            "Все будущие операции",
            cleanup_rule_summary("ИП Кабачков", "Расход", "Продукты", "Всегда для этого магазина / сервиса"),
        )
        self.assertIn(
            "Другие переводы этому человеку останутся на проверке",
            cleanup_rule_summary("Анна", "Компенсация", "Жильё", "Запомнить для этого человека и похожей суммы", 15000),
        )
        self.assertEqual(split_summary_text(), "Эта операция будет разделена на части. Постоянное правило создано не будет.")
        self.assertEqual(
            cleanup_rule_summary("TILDA", "Не учитывать", "Не учитывать", "Только эта операция"),
            "Операция не попадёт в доходы, расходы и план.",
        )

    def test_compensation_display_amount_is_positive(self) -> None:
        self.assertEqual(compensation_display_amount(-10000), 10000)
        self.assertEqual(compensation_display_amount(10000), 10000)

    def test_income_person_default_is_not_income(self) -> None:
        self.assertNotEqual(
            default_income_cleanup_scenario({"person_anchor": "Анна", "description": "Перевод от Анна"}),
            "Доход",
        )


if __name__ == "__main__":
    unittest.main()
