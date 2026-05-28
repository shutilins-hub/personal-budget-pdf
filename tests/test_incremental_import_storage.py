from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import storage


@contextmanager
def temporary_storage_db():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch.object(storage, "DATA_DIR", root / "data"):
            with patch.object(storage, "PROFILES_DIR", root / "data" / "profiles"):
                with patch.object(storage, "DB_PATH", root / "data" / "budget.sqlite3"):
                    storage.init_db()
                    yield storage.DB_PATH


def synthetic_operation(
    *,
    profile_id: str = "profile_a",
    account_id: str = "account_a",
    day: int = 1,
    amount: float = -100.0,
    description: str = "TEST MERCHANT",
    auth_code: str = "",
    card_last4: str = "",
    operation_id: str = "",
) -> dict:
    return {
        "id": operation_id or f"{profile_id}_{account_id}_{day}_{abs(int(amount))}_{auth_code}_{card_last4}",
        "profile_id": profile_id,
        "bank": "Test Bank",
        "source_file": "statement.pdf",
        "account_id": account_id,
        "operation_datetime": f"2026-05-{day:02d}T10:00:00",
        "description": description,
        "raw_description": description,
        "raw_category": "Тест",
        "bank_amount": amount,
        "direction": "expense" if amount < 0 else "income",
        "operation_type": "Личный расход",
        "budget_category": "Прочее / проверить",
        "personal_amount": abs(amount),
        "budget_amount": abs(amount),
        "planning_amount": abs(amount),
        "count_in_budget": True,
        "count_in_plan": True,
        "auth_code": auth_code,
        "card_last4": card_last4,
    }


class IncrementalImportStorageTest(unittest.TestCase):
    def test_single_operation_inserted_once(self) -> None:
        with temporary_storage_db():
            stats = storage.insert_operations_with_stats([synthetic_operation()])
            rows = storage.operations_df("profile_a")

        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(len(rows), 1)

    def test_same_operation_second_insert_is_duplicate(self) -> None:
        with temporary_storage_db():
            first = synthetic_operation()
            second = dict(first, id="same_operation_new_id")
            first_stats = storage.insert_operations_with_stats([first])
            second_stats = storage.insert_operations_with_stats([second])
            rows = storage.operations_df("profile_a")

        self.assertEqual(first_stats["inserted"], 1)
        self.assertEqual(second_stats["inserted"], 0)
        self.assertEqual(second_stats["duplicates"], 1)
        self.assertEqual(len(rows), 1)

    def test_same_operation_in_another_profile_is_not_duplicate(self) -> None:
        with temporary_storage_db():
            op_a = synthetic_operation(profile_id="profile_a")
            op_b = synthetic_operation(profile_id="profile_b", day=1)
            stats = storage.insert_operations_with_stats([op_a, op_b])

        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["duplicates"], 0)

    def test_same_operation_in_another_account_is_not_duplicate(self) -> None:
        with temporary_storage_db():
            op_a = synthetic_operation(account_id="account_a")
            op_b = synthetic_operation(account_id="account_b")
            stats = storage.insert_operations_with_stats([op_a, op_b])
            rows = storage.operations_df("profile_a")

        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(len(rows), 2)

    def test_auth_code_or_card_last4_keep_similar_operations_separate(self) -> None:
        with temporary_storage_db():
            op_a = synthetic_operation(day=3, amount=-500, description="SAME DESCRIPTION", auth_code="111111", card_last4="1234")
            op_b = synthetic_operation(day=3, amount=-500, description="SAME DESCRIPTION", auth_code="222222", card_last4="5678")
            stats = storage.insert_operations_with_stats([op_a, op_b])
            rows = storage.operations_df("profile_a")

        self.assertNotEqual(storage.build_duplicate_key(op_a), storage.build_duplicate_key(op_b))
        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(len(rows), 2)

    def test_import_batch_created_and_updated(self) -> None:
        with temporary_storage_db():
            batch_id = storage.create_import_batch(
                "profile_a",
                "statement.pdf",
                {
                    "bank": "Test Bank",
                    "document_type": "test_statement",
                    "account_id": "account_a",
                    "account_type": "debit_account",
                    "period_start": "2026-05-01",
                    "period_end": "2026-05-31",
                },
                operations_found=10,
                status="parsed",
            )
            storage.update_import_batch(
                batch_id,
                {
                    "operations_found": 10,
                    "operations_inserted": 7,
                    "duplicates_skipped": 3,
                    "status": "imported",
                    "warning": "Период частично уже был загружен",
                },
            )
            batches = storage.import_batches_df("profile_a")

        self.assertEqual(len(batches), 1)
        row = batches.iloc[0]
        self.assertEqual(row["operations_found"], 10)
        self.assertEqual(row["operations_inserted"], 7)
        self.assertEqual(row["duplicates_skipped"], 3)
        self.assertEqual(row["status"], "imported")
        self.assertEqual(row["warning"], "Период частично уже был загружен")

    def test_overlapping_period_import_appends_new_operations_only(self) -> None:
        with temporary_storage_db():
            first_period = [synthetic_operation(day=day, amount=-float(day)) for day in range(1, 11)]
            second_period = [synthetic_operation(day=day, amount=-float(day), operation_id=f"second_{day}") for day in range(8, 16)]
            first_stats = storage.insert_operations_with_stats(first_period)
            second_stats = storage.insert_operations_with_stats(second_period)
            all_rows = storage.operations_df("profile_a")
            overlap_rows = storage.operations_df("profile_a", "2026-05-08", "2026-05-10")
            new_rows = storage.operations_df("profile_a", "2026-05-11", "2026-05-15")

        self.assertEqual(first_stats["inserted"], 10)
        self.assertEqual(second_stats["inserted"], 5)
        self.assertEqual(second_stats["duplicates"], 3)
        self.assertEqual(len(all_rows), 15)
        self.assertEqual(len(overlap_rows), 3)
        self.assertEqual(len(new_rows), 5)

    def test_sqlite_uses_unique_duplicate_key_index(self) -> None:
        with temporary_storage_db() as db_path:
            conn = sqlite3.connect(db_path)
            try:
                indexes = {row[1]: row[2] for row in conn.execute("PRAGMA index_list(operations)").fetchall()}
            finally:
                conn.close()

        self.assertIn("idx_operations_duplicate_key", indexes)
        self.assertEqual(indexes["idx_operations_duplicate_key"], 1)


if __name__ == "__main__":
    unittest.main()
