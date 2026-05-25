from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from privacy import sanitize_text
from storage import DB_PATH, default_profile_template


BASE_DIR = Path(__file__).resolve().parent
DEMO_DIR = BASE_DIR / "demo_dataset"


SAFE_OPERATION_FIELDS = [
    "operation_datetime",
    "bank",
    "account_type",
    "raw_category",
    "description",
    "bank_amount",
    "direction",
    "operation_type",
    "budget_category",
    "budget_amount",
    "planning_amount",
    "needs_review",
]


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def _demo_profile() -> dict[str, Any]:
    template = default_profile_template()
    return {
        "id": "demo",
        "name": "Демо профиль",
        "monthly_limit": template.get("monthly_limit", 0),
        "plan": template.get("plan", {}),
        "income_plan": template.get("income_plan", {}),
        "own_identity": {
            "full_name": "Иванов Иван Иванович",
            "name_aliases": ["Иван Иванович И.", "Иван И."],
            "phones": [],
            "account_last4": [],
            "banks": ["Сбер", "Т-Банк", "Яндекс Банк"],
        },
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _demo_operations_from_db(limit: int) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT {", ".join(SAFE_OPERATION_FIELDS)}
            FROM operations
            ORDER BY datetime(operation_datetime) DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    operations: list[dict[str, Any]] = []
    for row in rows:
        item = {key: _sanitize_value(row[key]) for key in row.keys()}
        item["profile_id"] = "demo"
        item["source_file"] = "demo_statement.pdf"
        item["source_file_name"] = "demo_statement.pdf"
        operations.append(item)
    return operations


def _fallback_operations() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "demo",
            "operation_datetime": "2026-05-05T10:00:00",
            "bank": "Сбер",
            "account_type": "debit_account",
            "raw_category": "Супермаркеты",
            "description": "DEMO SUPERMARKET",
            "bank_amount": -2450.0,
            "direction": "expense",
            "operation_type": "Личный расход",
            "budget_category": "Продукты / супермаркеты",
            "budget_amount": 2450.0,
            "planning_amount": 2450.0,
            "needs_review": False,
            "source_file": "demo_statement.pdf",
            "source_file_name": "demo_statement.pdf",
        },
        {
            "profile_id": "demo",
            "operation_datetime": "2026-05-10T12:00:00",
            "bank": "Т-Банк",
            "account_type": "debit_account",
            "raw_category": "Перевод",
            "description": "Перевод для [ФИО скрыто]",
            "bank_amount": -15000.0,
            "direction": "expense",
            "operation_type": "Проверить",
            "budget_category": "Прочее / проверить",
            "budget_amount": 0.0,
            "planning_amount": 0.0,
            "needs_review": True,
            "source_file": "demo_statement.pdf",
            "source_file_name": "demo_statement.pdf",
        },
    ]


def build_demo_dataset(limit: int = 300) -> Path:
    DEMO_DIR.mkdir(exist_ok=True)
    profile_dir = DEMO_DIR / "data" / "profiles" / "demo"
    profile_dir.mkdir(parents=True, exist_ok=True)
    operations = _demo_operations_from_db(limit) or _fallback_operations()
    (profile_dir / "profile.json").write_text(json.dumps(_demo_profile(), ensure_ascii=False, indent=2), encoding="utf-8")
    (profile_dir / "merchant_rules.json").write_text("[]\n", encoding="utf-8")
    (profile_dir / "plan_rules.json").write_text("[]\n", encoding="utf-8")
    (DEMO_DIR / "demo_operations.json").write_text(json.dumps(operations, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEMO_DIR / "README_DEMO.txt").write_text(
        "Демо-комплект обезличен: Ф.И.О., телефоны, счета и карты замаскированы. "
        "Реальные PDF, data/budget.sqlite3 и exports не включаются.\n",
        encoding="utf-8",
    )
    return DEMO_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a sanitized demo dataset for external MVP testing.")
    parser.add_argument("--limit", type=int, default=300, help="Maximum number of operations to export from local DB.")
    args = parser.parse_args()
    output = build_demo_dataset(args.limit)
    print(f"Demo dataset written to {output}")


if __name__ == "__main__":
    main()
