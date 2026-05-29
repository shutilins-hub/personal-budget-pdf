from __future__ import annotations

import unittest

from ui_flow import (
    cleanup_apply_options,
    cleanup_cta_label,
    cleanup_rule_summary,
    compensation_display_amount,
    split_summary_text,
)


class CleanupUxHelpersTest(unittest.TestCase):
    def test_cta_labels_are_contextual(self) -> None:
        self.assertEqual(
            cleanup_cta_label({"direction": "income", "person_anchor": "Анна"}, "income"),
            "Уточнить поступление",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "merchant_anchor": "ИП Кабачков"}, "expense"),
            "Запомнить категорию",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "person_anchor": "Анна", "count": 3}, "expense"),
            "Назначить правило",
        )
        self.assertEqual(
            cleanup_cta_label({"direction": "expense", "description": "Разовая операция", "count": 1}, "expense"),
            "Проверить операцию",
        )

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


if __name__ == "__main__":
    unittest.main()
