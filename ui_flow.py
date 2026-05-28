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


def build_home_primary_action(history: pd.DataFrame, operations: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    review_count = review_count_for_operations(operations)
    if history.empty:
        return {
            "status": "Сначала загрузите выписки",
            "text": "Без истории сервис не сможет посчитать план, доходы и расходы.",
            "label": "Загрузить выписки",
            "target": "Профиль и загрузка",
            "severity": "warning",
        }
    if review_count > 0:
        return {
            "status": f"Нужно уточнить {review_count} операций",
            "text": "Расчёт предварительный: часть доходов, расходов или переводов требует проверки.",
            "label": "Перейти к очистке",
            "target": "Очистка",
            "severity": "warning",
            "review_count": review_count,
        }
    if not profile_has_plan(profile):
        return {
            "status": "Нужно принять план месяца",
            "text": "После принятия плана контроль покажет остаток по месяцу и категориям.",
            "label": "Перейти к плану",
            "target": "План",
            "severity": "warning",
        }
    return {
        "status": "Бюджет месяца готов к контролю",
        "text": "Данные очищены, план принят. Можно смотреть факт, остаток и категории.",
        "label": "Открыть контроль",
        "target": "Контроль",
        "severity": "good",
    }


def build_budget_readiness(
    history: pd.DataFrame,
    operations: pd.DataFrame,
    profile: dict[str, Any],
    profile_needs_attention: bool = False,
) -> list[dict[str, Any]]:
    review_count = review_count_for_operations(operations)
    has_plan = profile_has_plan(profile)
    loaded = not history.empty
    return [
        {
            "title": "Данные загружены",
            "status": "done" if loaded else "not_started",
            "label": "готово" if loaded else "не начато",
            "detail": f"операций в базе: {len(history)}" if loaded else "загрузите PDF-выписки",
        },
        {
            "title": "Очистка операций",
            "status": "needs_attention" if review_count else "done" if loaded else "not_started",
            "label": "требует внимания" if review_count else "готово" if loaded else "после загрузки",
            "detail": f"{review_count} операций на проверку" if review_count else "нет операций на проверку" if loaded else "появится после импорта",
        },
        {
            "title": "План принят",
            "status": "done" if has_plan else "needs_attention" if loaded and not review_count else "not_started",
            "label": "готово" if has_plan else "требует внимания" if loaded and not review_count else "далее",
            "detail": "лимиты используются в контроле" if has_plan else "примите план месяца",
        },
        {
            "title": "Контроль доступен",
            "status": "done" if loaded and has_plan else "not_started",
            "label": "готово" if loaded and has_plan else "далее",
            "detail": "можно смотреть текущий месяц" if loaded and has_plan else "после загрузки и плана",
        },
    ]


def build_home_secondary_actions(primary_action: dict[str, Any], history: pd.DataFrame, operations: pd.DataFrame, profile: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        {"title": "Загрузить новые выписки", "text": "Добавить свежую историю без обнуления старых операций.", "action_label": "Открыть загрузку", "action_target": "Профиль и загрузка"},
        {"title": "Открыть план", "text": "Посмотреть или поправить лимиты категорий.", "action_label": "Открыть план", "action_target": "План"},
        {"title": "Открыть контроль", "text": "Посмотреть план-факт, остаток и операции по категориям.", "action_label": "Открыть контроль", "action_target": "Контроль"},
        {"title": "Посмотреть правила", "text": "Изменить правила для людей, merchants и переводов.", "action_label": "Открыть правила", "action_target": "Правила"},
    ]
    primary_target = primary_action.get("target")
    actions = [action for action in candidates if action["action_target"] != primary_target]
    if history.empty:
        return [action for action in actions if action["action_target"] != "Контроль"][:2]
    if review_count_for_operations(operations) > 0:
        actions.insert(0, {"title": "Проверить план после очистки", "text": "После разметки операций рекомендации станут точнее.", "action_label": "Открыть план", "action_target": "План"})
    if not profile_has_plan(profile):
        actions = [action for action in actions if action["action_target"] != "Контроль"]
    return actions[:3]


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
