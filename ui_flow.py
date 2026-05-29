from __future__ import annotations

from typing import Any

import pandas as pd

from category_mapping import INCOME_CATEGORIES, map_expense_category, map_income_category


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

OPERATION_DISPLAY_LABELS = {
    "Разделено": "Разделено на части",
}

ACCOUNT_TYPE_LABELS = {
    "debit_account": "Дебетовая карта",
    "credit_card": "Кредитная карта",
    "installment_card": "Карта рассрочки",
    "loan_account": "Кредит / заём",
    "savings_account": "Вклад / накопительный счёт",
    "wallet": "Кошелёк",
    "marketplace_wallet": "Кошелёк маркетплейса",
    "unknown": "Не определён",
    "": "Не определён",
    None: "Не определён",
}

IMPORT_STATUS_LABELS = {
    "imported": "Импортировано",
    "parsed": "Разобрано",
    "skipped_irrelevant": "Пропущено",
    "error": "Ошибка",
    "": "Не определён",
    None: "Не определён",
}

PLAN_MODE_LABELS = {
    "draft_all_history": "Предварительная рекомендация",
    "verified_months": "Рекомендация по проверенной истории",
}

PLAN_MODE_DESCRIPTIONS = {
    "draft_all_history": (
        "Учитывает загруженную историю, включая операции, которые ещё требуют проверки. "
        "Подходит только как временный ориентир."
    ),
    "verified_months": (
        "Использует только очищенные месяцы. Станет доступен после 3 проверенных месяцев."
    ),
}

PLAN_ACCURACY_TITLE = "Точность рекомендации"

PLAN_STATUS_LABELS = {
    "ready": "достаточно истории",
    "low_history": "мало истории",
    "needs_review": "нужно разобрать",
    "needs_classification": "нужно разобрать",
    "manual": "ручной лимит",
    "excluded": "исключено",
    "check": "проверить",
}

UNRESOLVED_INCOME_LABELS = {
    "Неразобранные поступления / проверить",
    "Проверить доход",
    "Поступления на проверку",
}

SALARY_HINTS = (
    "зарплат",
    "аванс",
    "премия",
    "salary",
    "payroll",
    "зачисление заработной",
)


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


def account_type_label(value: str | None) -> str:
    if value is None or pd.isna(value):
        return "Не определён"
    return ACCOUNT_TYPE_LABELS.get(value, "Не определён")


def import_status_label(value: str | None) -> str:
    if value is None or pd.isna(value):
        return "Не определён"
    return IMPORT_STATUS_LABELS.get(value, "Не определён")


def plan_mode_label(mode: str) -> str:
    return PLAN_MODE_LABELS.get(mode, str(mode or ""))


def plan_mode_description(mode: str) -> str:
    return PLAN_MODE_DESCRIPTIONS.get(mode, "")


def plan_accuracy_title() -> str:
    return PLAN_ACCURACY_TITLE


def plan_status_label(value: str | None) -> str:
    if value is None or pd.isna(value):
        return ""
    value = str(value)
    return PLAN_STATUS_LABELS.get(value, value)


def canonical_plan_category(label: str | None, kind: str = "expense") -> str:
    if kind == "income":
        return map_income_category(str(label or "").strip())
    return map_expense_category(str(label or "").strip())


def is_income_plan_category(label: str | None) -> bool:
    value = str(label or "").strip()
    if not value or value in UNRESOLVED_INCOME_LABELS or "провер" in value.casefold():
        return False
    return map_income_category(value) in set(INCOME_CATEGORIES)


def month_review_metrics(operations: pd.DataFrame, report_month: str | None) -> dict[str, float | int]:
    if operations.empty or not report_month or "operation_datetime" not in operations.columns:
        return {"review_count": 0, "review_amount": 0.0, "operations_count": 0}
    df = operations.copy()
    month = pd.to_datetime(df["operation_datetime"], errors="coerce").dt.to_period("M").astype(str)
    df = df[month == report_month].copy()
    if df.empty:
        return {"review_count": 0, "review_amount": 0.0, "operations_count": 0}
    review_mask = df.get("needs_review", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    amount_col = "bank_amount" if "bank_amount" in df.columns else "budget_amount"
    amounts = pd.to_numeric(df.get(amount_col, pd.Series(0, index=df.index)), errors="coerce").fillna(0).abs()
    return {
        "review_count": int(review_mask.sum()),
        "review_amount": float(amounts[review_mask].sum()),
        "operations_count": int(len(df)),
    }


def build_plan_accuracy(
    operations: pd.DataFrame,
    report_month: str | None,
    required_months: int = 3,
) -> dict[str, object]:
    metrics = month_review_metrics(operations, report_month)
    if operations.empty or "operation_datetime" not in operations.columns:
        verified_months = 0
    else:
        df = operations.copy()
        df["month"] = pd.to_datetime(df["operation_datetime"], errors="coerce").dt.to_period("M").astype(str)
        df = df[df["month"].notna() & (df["month"] != "NaT")]
        if df.empty:
            verified_months = 0
        else:
            review = df.get("needs_review", pd.Series(False, index=df.index)).fillna(False).astype(bool)
            month_stats = df.assign(_needs_review=review).groupby("month")["_needs_review"].agg(["count", "sum"])
            verified_months = int(((month_stats["count"] > 0) & (month_stats["sum"] == 0)).sum())
    operations_count = int(metrics["operations_count"])
    review_count = int(metrics["review_count"])
    if operations_count == 0:
        current_month_status = "нет данных"
    elif review_count > 0:
        current_month_status = "требует проверки"
    else:
        current_month_status = "готов"
    if verified_months >= required_months and review_count == 0:
        recommendation_status = "точная"
    elif verified_months > 0 and review_count == 0:
        recommendation_status = "можно использовать"
    else:
        recommendation_status = "предварительная"
    return {
        "verified_months": min(verified_months, required_months),
        "actual_clean_months": verified_months,
        "required_months": required_months,
        "current_month_status": current_month_status,
        "review_count": review_count,
        "review_amount": float(metrics["review_amount"]),
        "operations_count": operations_count,
        "recommendation_status": recommendation_status,
        "has_enough_verified_months": verified_months >= required_months,
    }


def plan_primary_status(accuracy: dict[str, object]) -> tuple[str, str]:
    review_count = int(accuracy.get("review_count") or 0)
    verified_months = int(accuracy.get("verified_months") or 0)
    required_months = int(accuracy.get("required_months") or 3)
    if review_count > 0:
        return (
            "План предварительный",
            f"Есть {review_count} операций на проверку. После очистки месяца рекомендации станут точнее.",
        )
    if verified_months < required_months:
        return (
            "Недостаточно проверенной истории",
            f"Для точного плана нужно {required_months} проверенных месяца. Сейчас: {verified_months} из {required_months}.",
        )
    return ("Можно принять рекомендованный план", "История достаточно чистая для расчёта.")


def recommendation_stage(accuracy: dict[str, object]) -> str:
    if bool(accuracy.get("has_enough_verified_months")):
        return "accurate_available"
    return "preliminary"


def operation_display_label(value: str | None) -> str:
    if value is None or pd.isna(value):
        return ""
    value = str(value)
    return OPERATION_DISPLAY_LABELS.get(value, value)


def cleanup_anchor_kind(candidate_or_row: dict[str, Any] | pd.Series) -> str:
    person = str(candidate_or_row.get("person_anchor") or "").strip()
    merchant = str(candidate_or_row.get("merchant_anchor") or "").strip()
    anchor = str(candidate_or_row.get("anchor") or "").strip()
    text = " ".join([anchor, merchant, str(candidate_or_row.get("description") or "")]).casefold()
    if merchant:
        return "merchant"
    if person:
        return "person"
    merchant_hints = ("ип ", "ооо", "zao", "ooo", "shop", "store", "market", "кафе", "coffee", "tilda")
    if any(hint in text for hint in merchant_hints):
        return "merchant"
    person_hints = ("перевод от", "перевод для", " ш.", " юрьевич", "сергеевич", "александр", "анна")
    if any(hint in text for hint in person_hints):
        return "person"
    return "operation"


def cleanup_cta_label(candidate_or_row: dict[str, Any] | pd.Series, direction_kind: str = "") -> str:
    kind = cleanup_anchor_kind(candidate_or_row)
    direction = str(candidate_or_row.get("direction") or direction_kind or "")
    if direction in {"income", "incoming"} and kind == "person":
        return "Показать поступления"
    if kind == "merchant":
        return "Показать операции"
    return "Показать операции месяца"


def cleanup_group_focus_action(candidate_or_row: dict[str, Any] | pd.Series) -> dict[str, str] | None:
    anchor = str(candidate_or_row.get("anchor") or "").strip()
    if not anchor:
        return None
    return {"target": "month_rows", "anchor": anchor}


def cleanup_primary_focus(operations: pd.DataFrame, recurring_groups: pd.DataFrame | None = None) -> str:
    if not operations.empty and "needs_review" in operations.columns:
        if int(operations["needs_review"].fillna(False).astype(bool).sum()) > 0:
            return "month_rows"
    if recurring_groups is not None and not recurring_groups.empty:
        return "recurring_hints"
    return "done"


def offer_rule_before_operation() -> bool:
    return False


def cleanup_apply_options(candidate_or_row: dict[str, Any] | pd.Series, amount_rule_supported: bool = False) -> list[str]:
    kind = cleanup_anchor_kind(candidate_or_row)
    if kind == "merchant":
        return ["Только эта операция", "Всегда для этого магазина / сервиса"]
    if kind == "person":
        options = ["Только эта операция"]
        if amount_rule_supported:
            options.append("Запомнить для этого человека и похожей суммы")
        return options
    return ["Только эта операция"]


def has_mixed_amounts(candidate_or_row: dict[str, Any] | pd.Series) -> bool:
    count = int(candidate_or_row.get("count") or 0)
    months_seen = int(candidate_or_row.get("months_seen") or 0)
    total = abs(float(candidate_or_row.get("total_sum") or 0))
    median = abs(float(candidate_or_row.get("median_monthly_sum") or 0))
    if count <= 1:
        return False
    if median <= 0:
        return months_seen > 1
    return abs((total / max(count, 1)) - median) > max(500.0, median * 0.25)


def cleanup_rule_summary(
    anchor: str,
    scenario: str,
    category: str,
    apply_option: str,
    amount: float | None = None,
) -> str:
    if apply_option == "Всегда для этого магазина / сервиса":
        return f"Все будущие операции “{anchor}” будут попадать в категорию “{category}”."
    if apply_option == "Запомнить для этого человека и похожей суммы":
        amount_text = f" около {compact_money(amount)}" if amount else ""
        return (
            f"Переводы “{anchor}”{amount_text} будут учитываться как {scenario.lower()} "
            f"в категории “{category}”. Другие переводы этому человеку останутся на проверке."
        )
    if scenario in {"Не учитывать", "Не учитывать в плане"}:
        return "Операция не попадёт в доходы, расходы и план."
    return f"Только эта операция будет учтена как {scenario.lower()} в категории “{category}”."


def split_summary_text() -> str:
    return "Эта операция будет разделена на части. Постоянное правило создано не будет."


def compensation_display_amount(value: object) -> float:
    try:
        return abs(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def import_period_display(period_start: str | None, period_end: str | None) -> str:
    start = "" if period_start is None or pd.isna(period_start) else str(period_start).strip()
    end = "" if period_end is None or pd.isna(period_end) else str(period_end).strip()
    if not start and not end:
        return "не определён"
    if start and end:
        return f"{start} — {end}"
    return start or end


def looks_like_salary_text(*parts: object) -> bool:
    text = " ".join(str(part or "") for part in parts).casefold()
    return any(hint in text for hint in SALARY_HINTS)


def default_income_cleanup_scenario(candidate_or_row: dict[str, Any] | pd.Series) -> str:
    anchor = str(candidate_or_row.get("anchor") or "")
    description = str(candidate_or_row.get("description") or candidate_or_row.get("examples") or "")
    raw_category = str(candidate_or_row.get("raw_category") or "")
    if looks_like_salary_text(anchor, description, raw_category):
        return "Доход"
    transfer_from_person = "перевод от" in " ".join([anchor, description, raw_category]).casefold()
    if transfer_from_person or str(candidate_or_row.get("person_anchor") or "").strip():
        return "Компенсация"
    return "Компенсация"


def sort_cleanup_groups(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    df = candidates.copy()
    count = pd.to_numeric(df.get("count", 0), errors="coerce").fillna(0)
    months_seen = pd.to_numeric(df.get("months_seen", 0), errors="coerce").fillna(0)
    total_sum = pd.to_numeric(df.get("total_sum", 0), errors="coerce").fillna(0)
    median_monthly = pd.to_numeric(df.get("median_monthly_sum", 0), errors="coerce").fillna(0)
    nature = df.get("expense_nature", pd.Series("", index=df.index)).fillna("").astype(str)
    df["_recurring_rank"] = ((count > 1) | (months_seen >= 2) | nature.eq("recurring")).astype(int)
    df["_large_rank"] = nature.eq("oneoff_large").astype(int)
    df["_total_sort"] = total_sum
    df["_median_sort"] = median_monthly
    return df.sort_values(
        ["_recurring_rank", "_large_rank", "_median_sort", "_total_sort", "count"],
        ascending=[False, False, False, False, False],
    ).drop(columns=["_recurring_rank", "_large_rank", "_total_sort", "_median_sort"], errors="ignore")


def compact_money(value: object) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,.0f}".replace(",", " ") + " ₽"


def format_review_operation_line(row: dict[str, Any] | pd.Series) -> str:
    dt = pd.to_datetime(row.get("operation_datetime"), errors="coerce")
    date_text = dt.strftime("%d.%m") if pd.notna(dt) else "дата не указана"
    description = str(row.get("description") or row.get("normalized_description") or "").strip()
    return f"{date_text} · {compact_money(row.get('bank_amount'))} · {description}"


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
