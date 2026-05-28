from __future__ import annotations

from typing import Any

import pandas as pd


TECHNICAL_OPERATION_COLUMNS = {
    "account_id",
    "account_role",
    "cashflow_amount",
    "planning_amount",
    "debt_amount",
    "debt_type",
    "count_in_plan",
    "plan_exclusion_reason",
    "confidence",
    "classification_source",
    "duplicate_key",
    "linked_operation_id",
    "rule_id",
    "import_batch_id",
    "source_file_name",
    "raw_description",
    "normalized_description",
    "raw_block",
}


DISPLAY_OPERATION_COLUMNS = {
    "operation_datetime": "дата",
    "bank": "банк",
    "description": "описание",
    "bank_amount": "сумма",
    "operation_type": "тип",
    "budget_category": "категория",
    "needs_review": "проверить",
}


TECHNICAL_DISPLAY_OPERATION_COLUMNS = {
    "document_type": "тип документа",
    "account_type": "тип счёта",
    "account_role": "роль счёта",
    "account_id": "account id",
    "raw_category": "категория банка",
    "merchant_anchor": "merchant",
    "person_anchor": "человек",
    "direction": "направление",
    "cashflow_amount": "движение по счёту",
    "personal_amount": "личная сумма",
    "budget_amount": "сумма факта",
    "planning_amount": "сумма для плана",
    "debt_amount": "сумма долга",
    "debt_type": "тип долга",
    "count_in_plan": "в плане",
    "plan_category": "категория плана",
    "plan_exclusion_reason": "почему не в плане",
    "confidence": "уверенность",
    "classification_source": "источник",
    "duplicate_key": "ключ дубля",
    "linked_operation_id": "связана с",
    "rule_id": "id правила",
    "import_batch_id": "id загрузки",
    "source_file_name": "файл",
}


def review_count_for_operations(operations: pd.DataFrame) -> int:
    if operations.empty or "needs_review" not in operations.columns:
        return 0
    return int(operations["needs_review"].fillna(False).astype(bool).sum())


def profile_has_plan(profile: dict[str, Any]) -> bool:
    return bool(profile.get("auto_plan_accepted") or profile.get("plan_source"))


def determine_user_next_step(history: pd.DataFrame, operations: pd.DataFrame, profile: dict[str, Any]) -> str:
    if history.empty:
        return "Профиль и загрузка"
    if review_count_for_operations(operations) > 0:
        return "Очистка операций"
    if not profile_has_plan(profile):
        return "План месяца"
    return "Контроль бюджета"


def build_user_journey_steps(
    history: pd.DataFrame,
    operations: pd.DataFrame,
    profile: dict[str, Any],
    active_step: str,
    profile_needs_attention: bool = False,
) -> list[dict[str, Any]]:
    months_count = 0
    if not history.empty and "operation_datetime" in history.columns:
        months_count = history["operation_datetime"].astype(str).str[:7].nunique()
    review_count = review_count_for_operations(operations)
    has_plan = profile_has_plan(profile)
    loaded = not history.empty
    steps = [
        {
            "title": "Профиль и загрузка",
            "tab": "Профиль и загрузка",
            "done": loaded and months_count >= 1,
            "needs_attention": not loaded or profile_needs_attention,
            "hint": "Заполните профиль и загрузите PDF-выписки.",
        },
        {
            "title": "Очистка операций",
            "tab": "Очистка",
            "done": loaded and review_count == 0,
            "needs_attention": loaded and review_count > 0,
            "hint": "Разберите операции, которые сервис не распознал уверенно.",
        },
        {
            "title": "План месяца",
            "tab": "План",
            "done": has_plan,
            "needs_attention": loaded and review_count == 0 and not has_plan,
            "hint": "Примите рекомендованный план или задайте лимиты вручную.",
        },
        {
            "title": "Контроль бюджета",
            "tab": "Контроль",
            "done": loaded and has_plan,
            "needs_attention": loaded and has_plan and review_count > 0,
            "hint": "Смотрите план, факт, остаток и категории месяца.",
        },
    ]
    for step in steps:
        if step["title"] == active_step:
            step["status"] = "active"
            step["label"] = "активен"
        elif step["done"]:
            step["status"] = "done"
            step["label"] = "готово"
        elif step["needs_attention"]:
            step["status"] = "needs_attention"
            step["label"] = "требует внимания"
        else:
            step["status"] = "not_started"
            step["label"] = "далее"
    return steps


def visible_operation_columns(include_technical: bool = False) -> dict[str, str]:
    if include_technical:
        return {**DISPLAY_OPERATION_COLUMNS, **TECHNICAL_DISPLAY_OPERATION_COLUMNS}
    return dict(DISPLAY_OPERATION_COLUMNS)
