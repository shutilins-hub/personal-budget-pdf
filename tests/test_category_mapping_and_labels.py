from __future__ import annotations

import json
import unittest
from pathlib import Path

from category_mapping import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    map_expense_category,
    map_income_category,
)
from classifier import classify_operation
from operation_labels import operation_type_for_label
from ui_flow import default_income_cleanup_scenario


class CategoryMappingAndLabelsTest(unittest.TestCase):
    def test_base_expense_categories_are_new_short_list(self) -> None:
        self.assertEqual(
            EXPENSE_CATEGORIES,
            [
                "Жильё",
                "Продукты",
                "Кафе и доставка",
                "Транспорт",
                "Такси",
                "Авто",
                "Связь и подписки",
                "Здоровье",
                "Дом и быт",
                "Одежда",
                "Красота и уход",
                "Семья и подарки",
                "Обучение",
                "Отдых и развлечения",
                "Путешествия",
                "Документы и обязательные платежи",
                "Прочее / проверить",
            ],
        )
        self.assertIn("Такси", EXPENSE_CATEGORIES)
        self.assertNotIn("Маркетплейсы", EXPENSE_CATEGORIES)
        self.assertNotIn("Крупная медицина / стоматология", EXPENSE_CATEGORIES)
        self.assertNotIn("Документы / визы", EXPENSE_CATEGORIES)

    def test_base_income_categories_are_new_short_list(self) -> None:
        self.assertEqual(
            INCOME_CATEGORIES,
            [
                "Зарплата",
                "Доход от бизнеса / проектов",
                "Разовые поступления",
                "Социальные выплаты",
                "Кешбэк и проценты",
                "Прочий доход",
            ],
        )
        self.assertNotIn("Компенсация расходов", INCOME_CATEGORIES)
        self.assertNotIn("Возврат долга", INCOME_CATEGORIES)

    def test_old_expense_categories_map_to_new_labels(self) -> None:
        self.assertEqual(map_expense_category("Продукты / супермаркеты"), "Продукты")
        self.assertEqual(map_expense_category("Кафе / доставка / рестораны"), "Кафе и доставка")
        self.assertEqual(map_expense_category("Такси"), "Такси")
        self.assertEqual(map_expense_category("Авто / каршеринг"), "Авто")
        self.assertEqual(map_expense_category("Маркетплейсы"), "Прочее / проверить")
        self.assertEqual(map_expense_category("Документы / визы"), "Документы и обязательные платежи")

    def test_old_income_categories_map_to_new_labels(self) -> None:
        self.assertEqual(map_income_category("Зарплата / аванс / премия"), "Зарплата")
        self.assertEqual(map_income_category("Доп. доход / проекты"), "Доход от бизнеса / проектов")
        self.assertEqual(map_income_category("Продажа сайтов"), "Доход от бизнеса / проектов")
        self.assertEqual(map_income_category("Возврат налога / кешбэк"), "Разовые поступления")
        self.assertEqual(map_income_category("Прочий личный доход"), "Прочий доход")

    def test_operation_labels_map_to_internal_types(self) -> None:
        self.assertEqual(operation_type_for_label("Деньги в долг"), "Заём выдан")
        self.assertEqual(operation_type_for_label("Вернули долг"), "Возврат займа")
        self.assertEqual(operation_type_for_label("Оборотные средства для проекта / работы"), "Проектный оборот")
        self.assertEqual(operation_type_for_label("Перевод себе"), "Внутренний перевод")

    def test_person_income_default_is_not_salary(self) -> None:
        scenario = default_income_cleanup_scenario(
            {
                "anchor": "Перевод от Анна",
                "description": "Перевод от Анна",
                "person_anchor": "Анна",
            }
        )
        self.assertNotEqual(scenario, "Доход")

    def test_taxi_and_carsharing_rules_use_separate_categories(self) -> None:
        self.assertEqual(
            classify_operation(
                {
                    "bank": "Сбер",
                    "raw_category": "",
                    "description": "YANDEX*4121*GO MOSCOW RUS",
                    "bank_amount": -900,
                    "direction": "expense",
                },
                {"rules": []},
            )["budget_category"],
            "Такси",
        )
        self.assertEqual(
            classify_operation(
                {
                    "bank": "Сбер",
                    "raw_category": "",
                    "description": "VORON MOSCOW RUS",
                    "bank_amount": -1200,
                    "direction": "expense",
                },
                {"rules": []},
            )["budget_category"],
            "Авто",
        )

    def test_marketplace_rule_no_longer_uses_marketplace_category(self) -> None:
        result = classify_operation(
            {
                "bank": "Сбер",
                "raw_category": "",
                "description": "WILDBERRIES MOSCOW RUS",
                "bank_amount": -2500,
                "direction": "expense",
            },
            {"rules": []},
        )
        self.assertEqual(result["budget_category"], "Прочее / проверить")
        self.assertTrue(result["needs_review"])

    def test_categories_config_does_not_contain_marketplaces(self) -> None:
        config = json.loads(Path("config/categories.json").read_text(encoding="utf-8"))
        expense_labels = [row["label"] for row in config["expense"]]
        income_labels = [row["label"] for row in config["income"]]
        self.assertNotIn("Маркетплейсы", expense_labels)
        self.assertNotIn("Компенсация расходов", income_labels)


if __name__ == "__main__":
    unittest.main()
