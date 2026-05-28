from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

import storage
from financial_health import build_financial_health_report
from ui_flow import operation_display_label


def split_source_operation(amount: float = -8000.0) -> dict:
    return {
        "id": "op_split",
        "profile_id": "p1",
        "operation_datetime": "2026-05-10T10:00:00",
        "bank": "Test Bank",
        "description": "Перевод другу",
        "bank_amount": amount,
        "direction": "expense" if amount < 0 else "income",
        "operation_type": "Разделено",
        "budget_category": "Разделено",
        "plan_category": "Разделено",
        "budget_amount": 0.0,
        "personal_amount": 0.0,
        "needs_review": False,
    }


def personal_income(amount: float = 100000.0) -> dict:
    return {
        "id": "income",
        "profile_id": "p1",
        "operation_datetime": "2026-05-05T10:00:00",
        "bank": "Test Bank",
        "description": "Зарплата",
        "bank_amount": amount,
        "direction": "income",
        "operation_type": "Личный доход",
        "budget_category": "Зарплата",
        "plan_category": "Зарплата",
        "budget_amount": amount,
        "personal_amount": amount,
        "needs_review": False,
    }


def allocations(rows: list[dict]) -> pd.DataFrame:
    prepared = []
    for index, row in enumerate(rows, start=1):
        normalized = storage.normalize_allocation_budget_effect(row)
        normalized.update(
            {
                "id": f"alloc_{index}",
                "operation_id": "op_split",
                "profile_id": "p1",
                "created_at": "2026-05-10T10:01:00",
            }
        )
        prepared.append(normalized)
    return pd.DataFrame(prepared)


def plan() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"budget_category": "Кафе и доставка", "plan": 5000},
            {"budget_category": "Такси", "plan": 2000},
            {"budget_category": "Семья и подарки", "plan": 1000},
        ]
    )


class AllocationsPhase3IntegrationTest(unittest.TestCase):
    def test_financial_health_uses_split_expense_categories(self) -> None:
        report = build_financial_health_report(
            "p1",
            "2026-05",
            pd.DataFrame([split_source_operation(), personal_income()]),
            plan(),
            today=date(2026, 5, 15),
            allocations=allocations(
                [
                    {"amount": 5000, "operation_type": "Личный расход", "budget_category": "Кафе и доставка"},
                    {"amount": 2000, "operation_type": "Личный расход", "budget_category": "Такси"},
                    {"amount": 1000, "operation_type": "Личный расход", "budget_category": "Семья и подарки"},
                ]
            ),
        )

        self.assertEqual(report["key_metrics"]["clean_expenses"], 8000)
        categories = {risk["category"]: risk for risk in report["category_risks"]}
        self.assertEqual(categories["Кафе и доставка"]["fact"], 5000)
        self.assertEqual(categories["Такси"]["fact"], 2000)

    def test_financial_health_split_compensation_reduces_expense(self) -> None:
        report = build_financial_health_report(
            "p1",
            "2026-05",
            pd.DataFrame([split_source_operation(), personal_income()]),
            plan(),
            today=date(2026, 5, 15),
            allocations=allocations(
                [
                    {"amount": 5000, "operation_type": "Личный расход", "budget_category": "Кафе и доставка"},
                    {
                        "amount": 3000,
                        "operation_type": "Компенсация совместных расходов",
                        "budget_category": "Кафе и доставка",
                    },
                ]
            ),
        )

        self.assertEqual(report["key_metrics"]["clean_expenses"], 2000)
        self.assertEqual(report["key_metrics"]["compensations"], -3000)

    def test_financial_health_split_loan_return_is_not_income(self) -> None:
        report = build_financial_health_report(
            "p1",
            "2026-05",
            pd.DataFrame([split_source_operation(amount=8000)]),
            plan(),
            today=date(2026, 5, 15),
            allocations=allocations(
                [{"amount": 8000, "operation_type": "Возврат займа", "budget_category": ""}]
            ),
        )

        self.assertEqual(report["key_metrics"]["personal_income"], 0)
        self.assertEqual(report["key_metrics"]["clean_expenses"], 0)

    def test_split_display_label_is_human_readable(self) -> None:
        self.assertEqual(operation_display_label("Разделено"), "Разделено на части")


if __name__ == "__main__":
    unittest.main()
