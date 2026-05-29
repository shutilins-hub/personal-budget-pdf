from __future__ import annotations

import unittest

from operation_labels import (
    build_split_allocation_from_ui,
    default_split_labels_for_direction,
    split_label_category_kind,
    split_label_requires_category,
    split_total_state,
)


class SplitUiHelpersTest(unittest.TestCase):
    def test_build_split_allocation_maps_expense(self) -> None:
        allocation = build_split_allocation_from_ui("Расход", 5000, "Кафе и доставка", "ужин")

        self.assertEqual(allocation["operation_type"], "Личный расход")
        self.assertEqual(allocation["budget_category"], "Кафе и доставка")
        self.assertEqual(allocation["amount"], 5000)
        self.assertEqual(allocation["comment"], "ужин")

    def test_build_split_allocation_maps_compensation(self) -> None:
        allocation = build_split_allocation_from_ui("Компенсация", 3000, "Такси")

        self.assertEqual(allocation["operation_type"], "Компенсация совместных расходов")
        self.assertEqual(allocation["budget_category"], "Такси")

    def test_build_split_allocation_maps_service_types_without_category(self) -> None:
        cases = {
            "Вернули долг": "Возврат займа",
            "Перевод себе": "Внутренний перевод",
            "Оборотные средства для проекта / работы": "Проектный оборот",
            "Не учитывать": "Не учитывать",
        }

        for label, operation_type in cases.items():
            with self.subTest(label=label):
                allocation = build_split_allocation_from_ui(label, 1000, "Продукты")
                self.assertEqual(allocation["operation_type"], operation_type)
                self.assertEqual(allocation["budget_category"], "")

    def test_split_category_kind(self) -> None:
        self.assertEqual(split_label_category_kind("Расход"), "expense")
        self.assertEqual(split_label_category_kind("Компенсация"), "expense")
        self.assertEqual(split_label_category_kind("Доход"), "income")
        self.assertEqual(split_label_category_kind("Вернули долг"), "none")
        self.assertTrue(split_label_requires_category("Компенсация"))
        self.assertFalse(split_label_requires_category("Перевод себе"))

    def test_split_total_state_complete_and_incomplete(self) -> None:
        complete = split_total_state(
            -8000,
            [
                {"amount": 5000},
                {"amount": 2000},
                {"amount": 1000},
            ],
        )
        incomplete = split_total_state(-8000, [{"amount": 5000}, {"amount": 2000}])

        self.assertTrue(complete["is_complete"])
        self.assertEqual(complete["remaining"], 0)
        self.assertFalse(incomplete["is_complete"])
        self.assertEqual(incomplete["remaining"], 1000)

    def test_income_split_defaults_do_not_start_with_income(self) -> None:
        self.assertEqual(default_split_labels_for_direction("income")[0], "Компенсация")
        self.assertNotEqual(default_split_labels_for_direction("income")[0], "Доход")


if __name__ == "__main__":
    unittest.main()
