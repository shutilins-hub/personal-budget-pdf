from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import storage
from budget_engine import build_budget_rows, dashboard_metrics, plan_fact


@contextmanager
def temporary_storage_db():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch.object(storage, "DATA_DIR", root / "data"):
            with patch.object(storage, "PROFILES_DIR", root / "data" / "profiles"):
                with patch.object(storage, "DB_PATH", root / "data" / "budget.sqlite3"):
                    storage.init_db()
                    yield storage.DB_PATH


def operation_row(
    *,
    operation_id: str = "op_split",
    profile_id: str = "profile_a",
    amount: float = -8000.0,
    operation_type: str = "Проверить",
    category: str = "Прочее / проверить",
) -> dict:
    budget_amount = abs(amount) if operation_type == "Личный расход" else 0.0
    return {
        "id": operation_id,
        "profile_id": profile_id,
        "bank": "Test Bank",
        "source_file": "statement.pdf",
        "account_id": "account_a",
        "operation_datetime": "2026-05-15T10:00:00",
        "description": "TRANSFER TEST",
        "raw_description": "TRANSFER TEST",
        "raw_category": "Тест",
        "bank_amount": amount,
        "direction": "expense" if amount < 0 else "income",
        "operation_type": operation_type,
        "budget_category": category,
        "personal_amount": budget_amount,
        "budget_amount": budget_amount,
        "planning_amount": budget_amount,
        "count_in_budget": operation_type == "Личный расход",
        "count_in_plan": operation_type == "Личный расход",
        "needs_review": operation_type == "Проверить",
    }


def allocation(
    amount: float,
    operation_type: str = "Личный расход",
    category: str = "Продукты",
    comment: str = "",
) -> dict:
    return {
        "amount": amount,
        "operation_type": operation_type,
        "budget_category": category,
        "comment": comment,
    }


def operations_df_for_budget() -> pd.DataFrame:
    return pd.DataFrame(
        [
            operation_row(
                operation_id="op_old",
                amount=-1000,
                operation_type="Личный расход",
                category="Продукты",
            ),
            operation_row(operation_id="op_split", amount=-8000),
        ]
    )


def allocations_df_for_budget(rows: list[dict]) -> pd.DataFrame:
    prepared = []
    for index, row in enumerate(rows, start=1):
        normalized = storage.normalize_allocation_budget_effect(row)
        normalized.update(
            {
                "id": f"alloc_{index}",
                "operation_id": "op_split",
                "profile_id": "profile_a",
                "created_at": "2026-05-15T10:01:00",
            }
        )
        prepared.append(normalized)
    return pd.DataFrame(prepared)


class OperationAllocationsStorageTest(unittest.TestCase):
    def test_operation_allocations_table_is_created(self) -> None:
        with temporary_storage_db() as db_path:
            conn = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(operation_allocations)").fetchall()}
                indexes = {row[1] for row in conn.execute("PRAGMA index_list(operation_allocations)").fetchall()}
            finally:
                conn.close()

        self.assertIn("operation_id", columns)
        self.assertIn("profile_id", columns)
        self.assertIn("idx_operation_allocations_operation_id", indexes)
        self.assertIn("idx_operation_allocations_profile_id", indexes)

    def test_save_and_fetch_allocations(self) -> None:
        with temporary_storage_db():
            storage.insert_operations_with_stats([operation_row()])
            storage.save_operation_allocations(
                "op_split",
                "profile_a",
                [
                    allocation(5000, category="Кафе и доставка"),
                    allocation(3000, category="Такси"),
                ],
            )
            rows = storage.get_operation_allocations("op_split")
            profile_rows = storage.allocations_df("profile_a")

        self.assertEqual(len(rows), 2)
        self.assertEqual(len(profile_rows), 2)
        self.assertEqual(set(rows["budget_category"]), {"Кафе и доставка", "Такси"})

    def test_validation_rejects_empty_split(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [])

        self.assertFalse(ok)
        self.assertIn("хотя бы одну", message)

    def test_validation_rejects_non_positive_amount(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [allocation(0)])

        self.assertFalse(ok)
        self.assertIn("больше нуля", message)

    def test_validation_rejects_less_than_operation_amount(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [allocation(7000)])

        self.assertFalse(ok)
        self.assertIn("не совпадает", message)

    def test_validation_rejects_more_than_operation_amount(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [allocation(9000)])

        self.assertFalse(ok)
        self.assertIn("не совпадает", message)

    def test_validation_allows_one_kopeck_tolerance(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [allocation(7999.99)])

        self.assertTrue(ok, message)

    def test_personal_expense_requires_category(self) -> None:
        ok, message = storage.validate_operation_allocations(operation_row(), [allocation(8000, category="")])

        self.assertFalse(ok)
        self.assertIn("категорию", message)

    def test_compensation_requires_category(self) -> None:
        ok, message = storage.validate_operation_allocations(
            operation_row(),
            [allocation(8000, operation_type="Компенсация совместных расходов", category="")],
        )

        self.assertFalse(ok)
        self.assertIn("категорию", message)

    def test_loan_return_may_have_no_category(self) -> None:
        ok, message = storage.validate_operation_allocations(
            operation_row(amount=8000),
            [allocation(8000, operation_type="Возврат займа", category="")],
        )

        self.assertTrue(ok, message)

    def test_source_operation_is_marked_as_split_after_save(self) -> None:
        with temporary_storage_db():
            storage.insert_operations_with_stats([operation_row()])
            storage.save_operation_allocations(
                "op_split",
                "profile_a",
                [
                    allocation(5000, category="Кафе и доставка"),
                    allocation(3000, category="Такси"),
                ],
            )
            rows = storage.operations_df("profile_a")

        source = rows.loc[rows["id"] == "op_split"].iloc[0]
        self.assertEqual(source["operation_type"], "Разделено")
        self.assertEqual(source["budget_category"], "Разделено")
        self.assertFalse(bool(source["needs_review"]))
        self.assertEqual(float(source["budget_amount"]), 0)
        self.assertEqual(float(source["planning_amount"]), 0)

    def test_split_does_not_create_rules(self) -> None:
        with temporary_storage_db():
            storage.insert_operations_with_stats([operation_row()])
            storage.save_operation_allocations("op_split", "profile_a", [allocation(8000)])
            profile_dir = storage.PROFILES_DIR / "profile_a"

        self.assertFalse(profile_dir.exists())


class OperationAllocationsBudgetEngineTest(unittest.TestCase):
    def test_operation_without_allocations_is_counted_as_before(self) -> None:
        operations = pd.DataFrame(
            [operation_row(operation_id="op_old", amount=-1000, operation_type="Личный расход", category="Продукты")]
        )
        metrics = dashboard_metrics(operations, monthly_limit=5000)

        self.assertEqual(metrics["net_expense"], 1000)
        self.assertEqual(metrics["gross_expense"], 1000)

    def test_operation_with_allocations_replaces_source_row(self) -> None:
        operations = operations_df_for_budget()
        allocs = allocations_df_for_budget(
            [
                allocation(5000, category="Кафе и доставка"),
                allocation(3000, category="Такси"),
            ]
        )
        rows = build_budget_rows(operations, allocs)

        self.assertNotIn("op_split", set(rows["id"]))
        self.assertIn("allocation_alloc_1", set(rows["id"]))
        self.assertEqual(float(rows["budget_amount"].sum()), 9000)

    def test_split_expense_goes_to_two_categories(self) -> None:
        operations = operations_df_for_budget()
        allocs = allocations_df_for_budget(
            [
                allocation(5000, category="Кафе и доставка"),
                allocation(3000, category="Такси"),
            ]
        )
        plan = pd.DataFrame(
            [
                {"budget_category": "Продукты", "suggested_plan": 1000},
                {"budget_category": "Кафе и доставка", "suggested_plan": 5000},
                {"budget_category": "Такси", "suggested_plan": 3000},
            ]
        )
        fact = plan_fact(operations, plan, allocations=allocs)
        facts = dict(zip(fact["budget_category"], fact["fact"]))

        self.assertEqual(facts["Продукты"], 1000)
        self.assertEqual(facts["Кафе и доставка"], 5000)
        self.assertEqual(facts["Такси"], 3000)

    def test_split_compensation_reduces_category_expense(self) -> None:
        operations = operations_df_for_budget()
        allocs = allocations_df_for_budget(
            [
                allocation(5000, category="Кафе и доставка"),
                allocation(3000, operation_type="Компенсация совместных расходов", category="Кафе и доставка"),
            ]
        )
        plan = pd.DataFrame([{"budget_category": "Кафе и доставка", "suggested_plan": 5000}])
        fact = plan_fact(operations, plan, allocations=allocs)
        metrics = dashboard_metrics(operations, allocations=allocs)

        row = fact.loc[fact["budget_category"] == "Кафе и доставка"].iloc[0]
        self.assertEqual(row["fact"], 2000)
        self.assertEqual(metrics["compensation"], -3000)
        self.assertEqual(metrics["net_expense"], 3000)

    def test_split_loan_return_does_not_increase_income(self) -> None:
        operations = pd.DataFrame([operation_row(operation_id="op_split", amount=8000)])
        allocs = allocations_df_for_budget([allocation(8000, operation_type="Возврат займа", category="")])
        metrics = dashboard_metrics(operations, allocations=allocs)

        self.assertEqual(metrics["personal_income"], 0)
        self.assertEqual(metrics["net_expense"], 0)

    def test_split_lent_money_does_not_increase_expense(self) -> None:
        operations = pd.DataFrame([operation_row(operation_id="op_split", amount=-8000)])
        allocs = allocations_df_for_budget([allocation(8000, operation_type="Заём выдан", category="")])
        metrics = dashboard_metrics(operations, allocations=allocs)

        self.assertEqual(metrics["gross_expense"], 0)
        self.assertEqual(metrics["net_expense"], 0)

    def test_project_turnover_is_outside_personal_budget(self) -> None:
        operations = pd.DataFrame([operation_row(operation_id="op_split", amount=-8000)])
        allocs = allocations_df_for_budget([allocation(8000, operation_type="Проектный оборот", category="")])
        metrics = dashboard_metrics(operations, allocations=allocs)

        self.assertEqual(metrics["personal_income"], 0)
        self.assertEqual(metrics["gross_expense"], 0)
        self.assertEqual(metrics["net_expense"], 0)

    def test_dashboard_metrics_uses_allocations(self) -> None:
        operations = operations_df_for_budget()
        allocs = allocations_df_for_budget(
            [
                allocation(5000, category="Кафе и доставка"),
                allocation(3000, category="Такси"),
            ]
        )
        metrics = dashboard_metrics(operations, monthly_limit=10000, allocations=allocs)

        self.assertEqual(metrics["gross_expense"], 9000)
        self.assertEqual(metrics["net_expense"], 9000)
        self.assertEqual(metrics["limit_left"], 1000)


if __name__ == "__main__":
    unittest.main()
