from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import pandas as pd


PLAN_COLUMNS = ["budget_category", "months_count", "mean", "median", "p75", "suggested_plan", "comment"]
RAW_PLAN_COLUMNS = ["budget_category", "months_count", "mean", "median", "p75", "suggested_plan", "status", "comment"]
INCOME_PLAN_COLUMNS = ["income_category", "history_fact", "suggested_plan", "manual_plan"]
RAW_INCOME_PLAN_COLUMNS = ["income_category", "months_count", "mean", "median", "p75", "suggested_plan", "status", "comment"]
LAYERED_PLAN_COLUMNS = ["budget_category", "layer", "months_count", "mean", "median", "p75", "suggested_plan", "status", "comment"]
MINOR_OPERATION_THRESHOLD = 5000
LARGE_ONEOFF_THRESHOLD = 5000
EXCLUDED_PLAN_TYPES = {
    "Расход из фонда",
    "Внутренний перевод",
    "Погашение кредита",
    "Проектный расход",
    "Проектный приход",
    "Проектный налог",
    "Не учитывать",
    "Проверить",
    "cash_withdrawal",
    "Наличные / проверить",
    "Заём выдан",
    "Возврат займа",
}
RAW_INTERNAL_TEXT_MARKERS = {
    "sberbank onl@in karta-vklad",
    "sberbank onl@in vklad-karta",
    "mapp_sberbank_onl@in_pay",
    "пополнение кубышки",
    "перевод средств из кубышки",
    "внутренний перевод на договор",
    "внутрибанковский перевод с договора",
}
RAW_EXCLUDED_OPERATION_TYPES = {
    "Внутренний перевод",
    "Погашение кредита",
    "Проектный оборот",
    "Проектный расход",
    "Проектный приход",
    "Проектный налог",
    "Не учитывать",
}
RAW_REVIEW_CATEGORIES = {
    "Неразобранные переводы / проверить",
    "Наличные / проверить",
    "Прочее / проверить",
}
RAW_CATEGORY_MAP = {
    "Супермаркеты": "Продукты",
    "Рестораны и кафе": "Кафе и доставка",
    "Транспорт": "Транспорт",
    "Автомобиль": "Авто",
    "Здоровье и красота": "Здоровье",
    "Одежда и аксессуары": "Дом и быт",
    "Отдых и развлечения": "Отдых и развлечения",
}
RAW_MERCHANT_CATEGORY_RULES = [
    (("SAMOKAT", "LAVKA", "САМОКАТ", "ЛАВКА"), "Продукты"),
    (("YANDEX*4121*GO", "FASTEN", "TAXI"), "Такси"),
    (("YANDEX*5814*EDA",), "Кафе и доставка"),
    (("CITYDRIVE", "CARSHARING"), "Авто"),
    (("WHOOSH",), "Транспорт"),
    (("SBERPRIME", "BEELINE", "БИЛАЙН"), "Связь и подписки"),
    (("APTEKA", "APTECHNOE", "36,6", "АПТЕКА"), "Здоровье"),
    (("WILDBERRIES", "OZON"), "Прочее / проверить"),
]

BASE_LIVING_CATEGORIES = {
    "Жильё",
    "Продукты",
    "Продукты / супермаркеты",
    "Кафе и доставка",
    "Кафе / доставка / рестораны",
    "Транспорт",
    "Такси",
    "Авто",
    "Авто / каршеринг",
    "Связь и подписки",
    "Связь / интернет / подписки",
    "Здоровье",
    "Здоровье / аптеки",
    "Психолог / терапия",
    "Красота и уход",
    "Красота / уход",
    "Дом и быт",
    "Маркетплейсы",
    "Дом / ремонт / бытовое",
    "Дом / одежда / бытовое",
    "Одежда",
    "Обучение",
    "Отдых и развлечения",
    "Развлечения",
    "Семья и подарки",
    "Подарки / семья",
    "Путешествия",
    "Документы и обязательные платежи",
    "Документы / визы",
    "Крупная медицина / стоматология",
    "Прочее / проверить",
}
OBLIGATION_TYPES = {"debt_repayment", "Погашение кредита", "credit_interest", "bank_fee"}
OBLIGATION_CATEGORIES = {"Кредиты / проценты / комиссии", "Документы и обязательные платежи"}
UNRESOLVED_CATEGORIES = {"Неразобранные переводы / проверить", "Наличные / проверить"}


@dataclass
class PlanSummary:
    base_living_plan: float = 0.0
    obligations_plan: float = 0.0
    unresolved_plan: float = 0.0
    minor_oneoff_total: float = 0.0
    excluded_total: float = 0.0
    recommended_total: float = 0.0
    clean_total: float = 0.0
    raw_total: float = 0.0
    warnings: list[str] = field(default_factory=list)
    months_used: list[str] = field(default_factory=list)
    partial_months_excluded: list[str] = field(default_factory=list)
    owner_mismatch_files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_living_plan": self.base_living_plan,
            "obligations_plan": self.obligations_plan,
            "unresolved_plan": self.unresolved_plan,
            "minor_oneoff_total": self.minor_oneoff_total,
            "excluded_total": self.excluded_total,
            "recommended_total": self.recommended_total,
            "clean_total": self.clean_total,
            "raw_total": self.raw_total,
            "warnings": self.warnings,
            "months_used": self.months_used,
            "partial_months_excluded": self.partial_months_excluded,
            "owner_mismatch_files": self.owner_mismatch_files,
        }


def round_up(value: float, step: int = 500) -> float:
    if step <= 0:
        return float(value)
    return float(math.ceil(value / step) * step)


def previous_full_months(report_month: str, months_count: int) -> list[str]:
    current = pd.Period(report_month, freq="M")
    return [(current - index).strftime("%Y-%m") for index in range(months_count, 0, -1)]


def normalize_text(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def infer_anchor_direction(anchor: str) -> str | None:
    normalized = normalize_text(anchor)
    if "перевод от" in normalized:
        return "income"
    if "перевод для" in normalized:
        return "expense"
    return None


def uppercase_text(text: Any) -> str:
    return " ".join(str(text or "").upper().split())


def amount_by_mode(bank_amount: float, mode: str | None, fallback: float = 0.0) -> float:
    if mode == "0":
        return 0.0
    if mode == "-abs":
        return -abs(bank_amount)
    if mode in {"abs", "bank_abs"}:
        return abs(bank_amount)
    if mode == "signed":
        return bank_amount
    return float(fallback or 0)


def plan_rule_matches(row: pd.Series, rule: dict[str, Any]) -> bool:
    if rule.get("enabled") is False:
        return False
    scope = rule.get("rule_scope")
    if scope == "single_operation" or rule.get("operation_id"):
        if str(rule.get("operation_id") or "") != str(row.get("id") or ""):
            return False
    if scope == "current_month_similar" and rule.get("rule_month"):
        operation_month = str(row.get("operation_datetime") or "")[:7]
        if operation_month != str(rule.get("rule_month") or ""):
            return False
    text = normalize_text(
        " ".join(
            str(row.get(key, "") or "")
            for key in ["description", "normalized_description", "merchant_anchor", "person_anchor"]
        )
    )
    if rule.get("direction") and rule["direction"] != row.get("direction"):
        return False
    contains_any = [normalize_text(item) for item in rule.get("match_contains_any", []) if item]
    contains_all = [normalize_text(item) for item in rule.get("match_contains_all", []) if item]
    if not contains_any and not contains_all:
        return False
    if contains_any and not any(item in text for item in contains_any):
        return False
    if contains_all and not all(item in text for item in contains_all):
        return False
    return True


def default_rule_scope_for_candidate(row: pd.Series | dict[str, Any]) -> str:
    count = int(row.get("count") or 0)
    months_seen = int(row.get("months_seen") or 0)
    if count > 1 or months_seen >= 2:
        return "recurring_rule"
    return "single_operation"


def default_plan_behavior_for_candidate(row: pd.Series | dict[str, Any], scenario: str = "") -> str:
    if scenario in {"Подарок", "Я дал в долг", "Я вернул долг", "Мне вернули долг", "Я занял деньги", "Перевод между своими счетами", "Проектный оборот", "Не учитывать"}:
        return "Не учитывать в плане"
    if int(row.get("months_seen") or 0) >= 2:
        return "Учитывать как постоянную статью"
    return "Учитывать только в этом месяце"


def active_plan_rule_for_row(row: pd.Series, profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for rule in (profile or {}).get("plan_rules", []):
        if plan_rule_matches(row, rule):
            return rule
    return None


def is_resolved_for_plan(row: pd.Series) -> bool:
    operation_type = row.get("operation_type")
    source = str(row.get("classification_source") or "")
    rule_id = str(row.get("rule_id") or "")
    reason = str(row.get("plan_exclusion_reason") or "")

    if operation_type in {
        "Не учитывать",
        "Внутренний перевод",
        "Погашение кредита",
        "Проектный оборот",
        "Проектный расход",
        "Проектный приход",
        "Заём выдан",
        "Возврат займа",
    }:
        return True

    if operation_type in {"Личный расход", "Компенсация совместных расходов"} and bool(row.get("count_in_plan")):
        return True

    if operation_type == "Личный доход" and bool(row.get("count_in_budget")):
        return True

    if source.startswith("plan_") or rule_id.startswith("plan_"):
        return True

    if reason and operation_type != "Проверить":
        return True

    return False


def needs_plan_review(row: pd.Series) -> bool:
    source = str(row.get("classification_source") or "")
    operation_type = row.get("operation_type")
    if is_resolved_for_plan(row):
        return False
    return (
        operation_type == "Проверить"
        or bool(row.get("needs_review"))
        or source in {"", "review_fallback", "system_transfer_review"}
    )


def base_planning_values(row: pd.Series) -> dict[str, Any]:
    operation_type = row.get("operation_type") or "Проверить"
    bank_amount = float(row.get("bank_amount") or 0)
    personal_amount = float(row.get("personal_amount") or 0)
    category = row.get("budget_category") or "Прочее / проверить"
    values = {
        "budget_amount": personal_amount,
        "planning_amount": 0.0,
        "count_in_budget": personal_amount != 0,
        "count_in_plan": False,
        "plan_category": category,
        "plan_exclusion_reason": "",
    }
    if operation_type == "Личный расход":
        amount = personal_amount if personal_amount else abs(bank_amount)
        values.update(
            budget_amount=amount,
            planning_amount=amount,
            count_in_budget=True,
            count_in_plan=True,
            plan_category=category,
        )
    elif operation_type == "Компенсация совместных расходов":
        amount = personal_amount if personal_amount else -abs(bank_amount)
        values.update(
            budget_amount=amount,
            planning_amount=amount,
            count_in_budget=True,
            count_in_plan=True,
            plan_category=category,
        )
    elif operation_type == "Личный доход":
        values.update(budget_amount=personal_amount if personal_amount else abs(bank_amount), count_in_budget=True)
    elif operation_type in EXCLUDED_PLAN_TYPES:
        reason = "Нужно разобрать для плана" if operation_type == "Проверить" and row.get("direction") == "expense" else "Исключено из базового плана"
        values.update(
            budget_amount=0.0 if operation_type in {"Проверить", "Внутренний перевод", "Не учитывать", "cash_withdrawal"} else personal_amount,
            planning_amount=0.0,
            count_in_budget=False if operation_type in {"Проверить", "Внутренний перевод", "Не учитывать", "cash_withdrawal"} else personal_amount != 0,
            count_in_plan=False,
            plan_exclusion_reason=reason,
        )
    return values


def apply_plan_rule(row: pd.Series, rule: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    bank_amount = float(row.get("bank_amount") or 0)
    budget_amount = amount_by_mode(bank_amount, rule.get("budget_amount_mode"), values.get("budget_amount", 0))
    planning_amount = amount_by_mode(bank_amount, rule.get("planning_amount_mode"), values.get("planning_amount", 0))
    count_in_budget = bool(rule.get("count_in_budget", budget_amount != 0))
    count_in_plan = bool(rule.get("count_in_plan", planning_amount != 0))
    values.update(
        operation_type=rule.get("operation_type") or row.get("operation_type"),
        budget_category=rule.get("budget_category") or row.get("budget_category"),
        personal_amount=budget_amount,
        budget_amount=budget_amount,
        planning_amount=planning_amount,
        count_in_budget=count_in_budget,
        count_in_plan=count_in_plan,
        plan_category=rule.get("plan_category") or rule.get("budget_category") or row.get("budget_category"),
        plan_exclusion_reason="" if count_in_plan else rule.get("comment", "Исключено правилом планирования"),
        needs_review=bool(rule.get("needs_review", False)),
        confidence=float(rule.get("confidence", 0.95)),
        classification_source=rule.get("id", "plan_rule"),
        rule_id=rule.get("id", ""),
        expense_nature=rule.get("expense_nature") or row.get("expense_nature", ""),
    )
    return values


def prepare_planning_dataframe(operations: pd.DataFrame, profile: dict[str, Any] | None = None) -> pd.DataFrame:
    if operations.empty:
        return operations.copy()
    profile = profile or {}
    rules = profile.get("plan_rules", [])
    df = operations.copy()
    for column in ["description", "normalized_description", "merchant_anchor", "person_anchor", "budget_category"]:
        if column not in df.columns:
            df[column] = ""
    rows = []
    for _, row in df.iterrows():
        values = base_planning_values(row)
        for rule in rules:
            if plan_rule_matches(row, rule):
                values = apply_plan_rule(row, rule, values)
                break
        rows.append(values)
    planning = pd.DataFrame(rows, index=df.index)
    for column in planning.columns:
        if column in df.columns:
            df[column] = planning[column].where(planning[column].notna(), df[column])
        else:
            df[column] = planning[column]
    return df


def build_auto_plan(
    operations: pd.DataFrame,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
) -> pd.DataFrame:
    report_month = pd.Timestamp.today().to_period("M").strftime("%Y-%m")
    result = build_auto_expense_plan(operations, report_month, 6, strategy, buffer_percent, round_to)
    if result.empty:
        return pd.DataFrame(columns=["budget_category", "suggested_plan"])
    return result.rename(columns={"recommended_limit": "suggested_plan"})[["budget_category", "suggested_plan"]]


def build_auto_expense_plan(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if operations.empty:
        return pd.DataFrame(columns=PLAN_COLUMNS)
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    for column, default in [("classification_source", ""), ("rule_id", ""), ("needs_review", False), ("plan_exclusion_reason", "")]:
        if column not in df.columns:
            df[column] = default
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months) & (df["count_in_plan"] == True) & df["operation_datetime"].notna()]
    if df.empty:
        return pd.DataFrame(columns=PLAN_COLUMNS)
    monthly = df.groupby(["plan_category", "month"], as_index=False)["planning_amount"].sum()
    rows = []
    for category, group in monthly.groupby("plan_category"):
        values = group["planning_amount"]
        mean = float(values.mean())
        median = float(values.median())
        p75 = float(values.quantile(0.75))
        base = p75 if strategy == "p75" else median
        suggested = round_up(max(0, base) * (1 + buffer_percent / 100), round_to)
        rows.append(
            {
                "budget_category": category or "Прочее / проверить",
                "months_count": int(group["month"].nunique()),
                "mean": mean,
                "median": median,
                "p75": p75,
                "suggested_plan": suggested,
                "comment": f"По {group['month'].nunique()} полн. мес.",
            }
        )
    return pd.DataFrame(rows, columns=PLAN_COLUMNS).sort_values("suggested_plan", ascending=False)


def raw_text_blob(row: pd.Series) -> str:
    return normalize_text(
        " ".join(
            str(row.get(key, "") or "")
            for key in ["description", "raw_description", "normalized_description", "merchant_anchor", "person_anchor", "raw_category"]
        )
    )


def is_raw_internal_or_excluded(row: pd.Series) -> bool:
    operation_type = row.get("operation_type")
    if operation_type in RAW_EXCLUDED_OPERATION_TYPES:
        return True
    text = raw_text_blob(row)
    return any(marker in text for marker in RAW_INTERNAL_TEXT_MARKERS)


def raw_category_from_merchant(row: pd.Series) -> str | None:
    text = uppercase_text(
        " ".join(
            str(row.get(key, "") or "")
            for key in ["merchant_anchor", "description", "raw_description", "normalized_description"]
        )
    )
    for markers, category in RAW_MERCHANT_CATEGORY_RULES:
        if any(marker in text for marker in markers):
            return category
    return None


def infer_raw_plan_category(row: pd.Series) -> tuple[str, str, str]:
    if bool(row.get("count_in_plan")):
        category = row.get("plan_category") or row.get("budget_category") or "Прочее / проверить"
        return str(category), "ready", "Уже учтено правилами планирования."

    merchant_category = raw_category_from_merchant(row)
    if merchant_category:
        return merchant_category, "ready", "Категория определена по описанию операции."

    raw_category = str(row.get("raw_category") or "").strip()
    if raw_category in RAW_CATEGORY_MAP:
        return RAW_CATEGORY_MAP[raw_category], "ready", "Категория определена по категории банка."
    raw_lower = raw_category.casefold()
    if "выдача наличных" in raw_lower or "налич" in raw_lower:
        return "Наличные / проверить", "needs_classification", "Наличные включены в черновой план. Уточните, считать ли их расходом."
    if "перевод" in raw_lower:
        return "Неразобранные переводы / проверить", "needs_classification", "Эти переводы учтены в черновом плане, но требуют разметки."
    if raw_category in {"Прочие операции", "Прочие расходы"}:
        return "Прочее / проверить", "needs_classification", "Прочие исходящие операции включены в черновой план."
    return "Прочее / проверить", "needs_classification", "Операция включена в черновой план, категорию нужно уточнить."


def raw_plan_amount(row: pd.Series) -> float:
    if bool(row.get("count_in_plan")):
        amount = float(row.get("planning_amount") or 0)
        if amount:
            return amount
    return abs(float(row.get("bank_amount") or 0))


def build_raw_auto_plan_from_operations(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if operations.empty:
        return pd.DataFrame(columns=RAW_PLAN_COLUMNS)
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    for column, default in [("classification_source", ""), ("rule_id", ""), ("needs_review", False), ("plan_exclusion_reason", "")]:
        if column not in df.columns:
            df[column] = default
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months) & df["operation_datetime"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_PLAN_COLUMNS)
    df = df[df["direction"].isin(["expense", "outgoing"]) | (df["count_in_plan"] == True)].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_PLAN_COLUMNS)
    excluded_mask = df.apply(is_raw_internal_or_excluded, axis=1)
    df = df[~excluded_mask].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_PLAN_COLUMNS)

    inferred = df.apply(infer_raw_plan_category, axis=1, result_type="expand")
    inferred.columns = ["raw_auto_plan_category", "raw_status", "raw_comment"]
    df = pd.concat([df, inferred], axis=1)
    df["raw_auto_plan_amount"] = df.apply(raw_plan_amount, axis=1)
    df = df[df["raw_auto_plan_amount"] != 0].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_PLAN_COLUMNS)

    monthly = df.groupby(["raw_auto_plan_category", "month"], as_index=False)["raw_auto_plan_amount"].sum()
    meta = (
        df.groupby("raw_auto_plan_category")
        .agg(status=("raw_status", lambda values: "needs_classification" if "needs_classification" in set(values) else "ready"),
             comment=("raw_comment", "first"))
        .reset_index()
    )
    rows = []
    for category, group in monthly.groupby("raw_auto_plan_category"):
        values = group["raw_auto_plan_amount"]
        mean = float(values.mean())
        median = float(values.median())
        p75 = float(values.quantile(0.75))
        base = p75 if strategy == "p75" else median
        suggested = round_up(max(0, base) * (1 + buffer_percent / 100), round_to)
        months_count = int(group["month"].nunique())
        status = str(meta.loc[meta["raw_auto_plan_category"] == category, "status"].iloc[0])
        comment = str(meta.loc[meta["raw_auto_plan_category"] == category, "comment"].iloc[0])
        if months_count < 3 and status == "ready":
            status = "low_history"
            comment = "Мало полных месяцев истории, проверьте лимит вручную."
        rows.append(
            {
                "budget_category": category or "Прочее / проверить",
                "months_count": months_count,
                "mean": mean,
                "median": median,
                "p75": p75,
                "suggested_plan": suggested,
                "status": status,
                "comment": comment,
            }
        )
    return pd.DataFrame(rows, columns=RAW_PLAN_COLUMNS).sort_values("suggested_plan", ascending=False)


def build_raw_auto_plan(
    profile_id: str,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
) -> pd.DataFrame:
    from storage import load_profile, operations_df

    profile = load_profile(profile_id)
    return build_raw_auto_plan_from_operations(
        operations_df(profile_id),
        report_month,
        history_months,
        strategy,
        buffer_percent,
        round_to,
        profile,
    )


def plan_layer_for_row(row: pd.Series) -> tuple[str, str, str]:
    operation_type = str(row.get("operation_type") or "")
    category = str(row.get("plan_category") or row.get("budget_category") or "Прочее / проверить")
    account_type = str(row.get("account_type") or "")
    text = raw_text_blob(row)
    if operation_type in {"Внутренний перевод", "Проектный оборот", "Проектный расход", "Проектный приход", "Не учитывать", "Заём выдан", "Возврат займа", "credit_draw", "wallet_topup"}:
        return "Исключено", "excluded", "Не входит в личный план."
    if operation_type in OBLIGATION_TYPES or category in OBLIGATION_CATEGORIES or "комисси" in text or "процент" in text:
        return "Обязательства", "ready", "Кредиты, проценты, комиссии или обязательные платежи."
    if category in UNRESOLVED_CATEGORIES or operation_type in {"Проверить", "unknown_transfer"}:
        return "Разобрать", "needs_classification", "Операция включена отдельно, чтобы план не был занижен."
    if operation_type in {"Личный расход", "Компенсация совместных расходов", "credit_purchase"} or bool(row.get("count_in_plan")):
        if category in BASE_LIVING_CATEGORIES or operation_type == "credit_purchase" or account_type in {"credit_card", "installment_card", "wallet", "marketplace_wallet"}:
            return "База", "ready", "Обычные расходы жизни."
    if row.get("direction") in {"expense", "outgoing"}:
        return "Разобрать", "needs_classification", "Крупная исходящая операция без понятной категории."
    return "Исключено", "excluded", "Не влияет на расходный план."


def layered_plan_amount(row: pd.Series) -> float:
    operation_type = str(row.get("operation_type") or "")
    bank_amount = abs(float(row.get("bank_amount") or 0))
    if operation_type in {"debt_repayment", "Погашение кредита", "credit_interest", "bank_fee"}:
        debt_amount = abs(float(row.get("debt_amount") or 0))
        return debt_amount or bank_amount
    if operation_type in {"credit_draw", "wallet_topup", "Внутренний перевод", "Проектный оборот", "Проектный расход", "Проектный приход", "Не учитывать", "Заём выдан", "Возврат займа"}:
        return 0.0
    if bool(row.get("count_in_plan")):
        return float(row.get("planning_amount") or row.get("budget_amount") or 0)
    budget_amount = float(row.get("budget_amount") or row.get("personal_amount") or 0)
    if budget_amount:
        return budget_amount
    if row.get("direction") in {"expense", "outgoing"}:
        return bank_amount
    return 0.0


def classify_minor_oneoff_rows(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    key = df.apply(
        lambda row: str(row.get("person_anchor") or row.get("merchant_anchor") or row.get("normalized_description") or row.get("description") or ""),
        axis=1,
    )
    temp = df.copy()
    temp["_anchor"] = key
    grouped = temp.groupby("_anchor").agg(
        count=("operation_datetime", "count"),
        months_seen=("month", "nunique"),
        total_sum=("layer_amount", lambda values: float(values.abs().sum())),
    )
    return temp["_anchor"].map(
        lambda anchor: bool(
            grouped.loc[anchor, "count"] == 1
            and grouped.loc[anchor, "months_seen"] == 1
            and grouped.loc[anchor, "total_sum"] < MINOR_OPERATION_THRESHOLD
        )
    )


def adjust_debt_repayment_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for month, group in df.groupby("month"):
        credit_purchase_total = float(group.loc[group["operation_type"] == "credit_purchase", "layer_amount"].abs().sum())
        debt_mask = (df["month"] == month) & (df["operation_type"].isin(["debt_repayment", "Погашение кредита"]))
        debt_total = float(df.loc[debt_mask, "layer_amount"].abs().sum())
        if credit_purchase_total and debt_total and debt_total <= credit_purchase_total * 1.05:
            df.loc[debt_mask, "layer"] = "Исключено"
            df.loc[debt_mask, "status"] = "excluded"
            df.loc[debt_mask, "comment"] = "Погашение не дублирует покупки по кредитке."
            df.loc[debt_mask, "layer_amount"] = 0.0
    return df


def owner_match_status(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    profile = profile or {}
    owner = normalize_text((profile.get("own_identity") or {}).get("full_name", ""))
    result = []
    for source_file, metadata in (profile.get("source_files") or {}).items():
        file_owner = normalize_text(metadata.get("owner_name", ""))
        if owner and file_owner and owner != file_owner:
            result.append(
                {
                    "source_file": source_file,
                    "owner_name": metadata.get("owner_name", ""),
                    "profile_owner_name": (profile.get("own_identity") or {}).get("full_name", ""),
                    "owner_match": False,
                    "action": "warning",
                }
            )
    return result


def build_layered_plan_from_operations(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
    profile: dict[str, Any] | None = None,
) -> tuple[PlanSummary, pd.DataFrame, dict[str, pd.DataFrame]]:
    if operations.empty:
        summary = PlanSummary(warnings=["too_few_complete_months"])
        return summary, pd.DataFrame(columns=LAYERED_PLAN_COLUMNS), {}
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    for column, default in [
        ("classification_source", ""),
        ("rule_id", ""),
        ("needs_review", False),
        ("plan_exclusion_reason", ""),
        ("account_type", ""),
        ("account_role", ""),
        ("debt_amount", 0.0),
        ("source_file", ""),
    ]:
        if column not in df.columns:
            df[column] = default
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    available_months = sorted(month for month in df["month"].dropna().unique() if month != "NaT")
    used_months = [month for month in months if month in set(available_months)]
    partial_months_excluded = [month for month in available_months if month not in used_months and month <= report_month]
    df = df[df["month"].isin(used_months) & df["operation_datetime"].notna()].copy()
    summary = PlanSummary(months_used=used_months, partial_months_excluded=partial_months_excluded)
    summary.owner_mismatch_files = owner_match_status(profile)
    if summary.owner_mismatch_files:
        summary.warnings.append("owner_mismatch_files")
    if len(used_months) < 3:
        summary.warnings.append("too_few_complete_months")
    if df.empty:
        return summary, pd.DataFrame(columns=LAYERED_PLAN_COLUMNS), {"monthly_plan_totals": pd.DataFrame(), "excluded_by_reason": pd.DataFrame()}

    layer_data = df.apply(plan_layer_for_row, axis=1, result_type="expand")
    layer_data.columns = ["layer", "status", "comment"]
    df = pd.concat([df, layer_data], axis=1)
    df["layer_amount"] = df.apply(layered_plan_amount, axis=1)
    df = adjust_debt_repayment_duplicates(df)
    minor_mask = classify_minor_oneoff_rows(df[(df["layer"] == "Разобрать") & (df["layer_amount"].abs() > 0)])
    if not minor_mask.empty:
        minor_indexes = minor_mask[minor_mask].index
        df.loc[minor_indexes, "layer"] = "Мелкие"
        df.loc[minor_indexes, "status"] = "Проверить"
        df.loc[minor_indexes, "comment"] = "Мелкая разовая операция скрыта из основного плана."

    plan_df = df[df["layer_amount"] != 0].copy()
    monthly = (
        plan_df.groupby(["month", "budget_category", "layer"], as_index=False)
        .agg(
            net_amount=("layer_amount", "sum"),
            operations_count=("id", "count"),
            source_accounts=("source_file", lambda values: ", ".join(sorted(set(str(value) for value in values if value)))[:300]),
            source_operation_types=("operation_type", lambda values: ", ".join(sorted(set(str(value) for value in values if value)))[:300]),
        )
    )
    rows = []
    for (category, layer), group in monthly.groupby(["budget_category", "layer"]):
        values = group["net_amount"]
        mean = float(values.mean())
        median = float(values.median())
        p75 = float(values.quantile(0.75))
        base = p75 if strategy == "p75" else median
        suggested = round_up(max(0, base) * (1 + buffer_percent / 100), round_to)
        statuses = plan_df[(plan_df["budget_category"] == category) & (plan_df["layer"] == layer)]["status"]
        comments = plan_df[(plan_df["budget_category"] == category) & (plan_df["layer"] == layer)]["comment"]
        status = "needs_classification" if layer == "Разобрать" else "ready"
        if layer == "Мелкие":
            status = "check"
        if layer == "Исключено":
            status = "excluded"
        if group["month"].nunique() < 3 and status == "ready":
            status = "low_history"
        rows.append(
            {
                "budget_category": category or "Прочее / проверить",
                "layer": layer,
                "months_count": int(group["month"].nunique()),
                "mean": mean,
                "median": median,
                "p75": p75,
                "suggested_plan": suggested,
                "status": status,
                "comment": str(comments.iloc[0]) if not comments.empty else "",
                "source_operation_types": str(group["source_operation_types"].iloc[0]) if "source_operation_types" in group else "",
            }
        )
    recommended = pd.DataFrame(rows).sort_values(["layer", "suggested_plan"], ascending=[True, False])
    if recommended.empty:
        recommended = pd.DataFrame(columns=[*LAYERED_PLAN_COLUMNS, "source_operation_types"])

    summary.base_living_plan = float(recommended.loc[recommended["layer"] == "База", "suggested_plan"].sum())
    summary.obligations_plan = float(recommended.loc[recommended["layer"] == "Обязательства", "suggested_plan"].sum())
    summary.unresolved_plan = float(recommended.loc[recommended["layer"] == "Разобрать", "suggested_plan"].sum())
    summary.minor_oneoff_total = float(recommended.loc[recommended["layer"] == "Мелкие", "suggested_plan"].sum())
    summary.excluded_total = float(plan_df.loc[plan_df["layer"] == "Исключено", "layer_amount"].abs().sum())
    summary.recommended_total = summary.base_living_plan + summary.obligations_plan + summary.unresolved_plan
    summary.clean_total = summary.base_living_plan + summary.obligations_plan
    summary.raw_total = summary.recommended_total + summary.minor_oneoff_total

    outgoing = df[
        (df["direction"].isin(["expense", "outgoing"]))
        & (~df["operation_type"].isin(["Внутренний перевод", "Не учитывать", "Проектный оборот", "credit_draw", "wallet_topup"]))
    ]
    if not outgoing.empty:
        monthly_outgoing = outgoing.groupby("month")["bank_amount"].apply(lambda values: float(values.abs().sum()))
        median_real_outgoing = float(monthly_outgoing.median()) if not monthly_outgoing.empty else 0.0
        if median_real_outgoing and summary.base_living_plan < median_real_outgoing * 0.7:
            summary.warnings.append("plan_may_be_understated")
    if summary.recommended_total and summary.unresolved_plan > summary.recommended_total * 0.2:
        summary.warnings.append("high_unresolved_transfers")
    credit_accounts = set(str(value) for value in df["account_type"].dropna().unique()) & {"credit_card", "installment_card", "loan_account"}
    if credit_accounts and summary.obligations_plan == 0:
        summary.warnings.append("credit_accounts_without_debt_plan")
    if summary.base_living_plan and not (recommended["budget_category"] == "Жильё").any():
        summary.warnings.append("no_housing_detected")
    if (recommended["budget_category"] == "Наличные / проверить").any():
        summary.warnings.append("cash_withdrawals_not_configured")
    if (df["account_type"].isin(["wallet", "marketplace_wallet"]) & (df["layer"] == "Разобрать")).any():
        summary.warnings.append("incomplete_wallet_parsing")

    monthly_debug = monthly.rename(columns={"net_amount": "net_amount"}).copy()
    if not monthly_debug.empty:
        monthly_debug["gross_expense"] = monthly_debug["net_amount"].clip(lower=0)
        monthly_debug["compensation"] = monthly_debug["net_amount"].clip(upper=0)
        monthly_debug["status"] = monthly_debug["layer"].map({"База": "ready", "Обязательства": "ready", "Разобрать": "needs_classification", "Мелкие": "check", "Исключено": "excluded"}).fillna("")
    excluded = df[df["layer"] == "Исключено"].copy()
    excluded_debug = pd.DataFrame(columns=["reason", "amount", "count", "examples"])
    if not excluded.empty:
        excluded["reason"] = excluded["plan_exclusion_reason"].replace("", "Исключено из плана")
        excluded_debug = (
            excluded.groupby("reason")
            .agg(
                amount=("bank_amount", lambda values: float(values.abs().sum())),
                count=("id", "count"),
                examples=("description", lambda values: " | ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            )
            .reset_index()
        )
    source_debug = source_files_plan_debug(profile, summary.owner_mismatch_files)
    debug = {
        "plan_source_files": source_debug,
        "monthly_plan_totals": monthly_debug,
        "excluded_by_reason": excluded_debug,
        "recommended_plan": recommended,
    }
    return summary, recommended, debug


def source_files_plan_debug(profile: dict[str, Any] | None, owner_mismatches: list[dict[str, Any]]) -> pd.DataFrame:
    profile = profile or {}
    owner = (profile.get("own_identity") or {}).get("full_name", "")
    mismatch_map = {item["source_file"]: item for item in owner_mismatches}
    rows = []
    for source_file, metadata in (profile.get("source_files") or {}).items():
        rows.append(
            {
                "source_file": source_file,
                "owner_name": metadata.get("owner_name", ""),
                "profile_owner_name": owner,
                "owner_match": source_file not in mismatch_map,
                "document_type": metadata.get("document_type") or metadata.get("detected_document_type", ""),
                "account_type": metadata.get("account_type", ""),
                "account_role": metadata.get("account_role", ""),
                "period_start": metadata.get("period_start", ""),
                "period_end": metadata.get("period_end", ""),
                "included_in_plan": source_file not in mismatch_map,
                "reason": "owner_mismatch" if source_file in mismatch_map else "ok",
            }
        )
    return pd.DataFrame(rows)


def build_plan_layers(
    profile_id: str,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 10,
    round_to: int = 500,
) -> tuple[PlanSummary, pd.DataFrame, dict[str, pd.DataFrame]]:
    from storage import load_profile, operations_df

    profile = load_profile(profile_id)
    return build_layered_plan_from_operations(
        operations_df(profile_id),
        report_month,
        history_months,
        strategy,
        buffer_percent,
        round_to,
        profile,
    )


def build_auto_income_plan(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
) -> pd.DataFrame:
    if operations.empty:
        return pd.DataFrame(columns=INCOME_PLAN_COLUMNS)
    months = previous_full_months(report_month, history_months)
    df = operations.copy()
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[
        df["month"].isin(months)
        & (df["operation_type"] == "Личный доход")
        & df["operation_datetime"].notna()
    ]
    if df.empty:
        return pd.DataFrame(columns=INCOME_PLAN_COLUMNS)
    monthly = df.groupby(["budget_category", "month"], as_index=False)["personal_amount"].sum()
    rows = []
    for category, group in monthly.groupby("budget_category"):
        values = group["personal_amount"]
        suggested = float(values.iloc[-1] if category in {"Зарплата", "Зарплата / аванс / премия", "Зарплата / аванс"} else values.median())
        if strategy == "p75":
            suggested = float(values.quantile(0.75))
        rows.append(
            {
                "income_category": category or "Прочий доход",
                "history_fact": float(values.sum()),
                "suggested_plan": suggested,
                "manual_plan": suggested,
            }
        )
    return pd.DataFrame(rows, columns=INCOME_PLAN_COLUMNS).sort_values("suggested_plan", ascending=False)


def infer_raw_income_category(row: pd.Series) -> tuple[str, str, str]:
    operation_type = row.get("operation_type")
    if operation_type == "Личный доход":
        return str(row.get("budget_category") or "Прочий доход"), "ready", "Личный доход уже распознан."
    if operation_type == "Компенсация совместных расходов":
        return "Компенсации / проверить", "excluded", "Компенсации не считаются доходом, они уменьшают расходы."
    if operation_type == "Возврат займа":
        return "Возвраты долгов / проверить", "excluded", "Возвраты долгов не входят в личный доход."
    if operation_type in {"Внутренний перевод", "Проектный оборот", "Проектный приход", "Не учитывать"}:
        return "Проектные поступления / проверить", "excluded", "Операция исключена из личного доходного плана."
    text = normalize_text(" ".join(str(row.get(key, "") or "") for key in ["description", "raw_category", "budget_category"]))
    if "заработная плата" in text or "аванс" in text or "премия" in text:
        return "Зарплата", "needs_classification", "Похоже на доход, проверьте и создайте правило."
    if "социаль" in text:
        return "Прочие выплаты", "needs_classification", "Похоже на выплату, проверьте источник."
    return "Неразобранные поступления / проверить", "needs_classification", "Входящие операции учтены в черновике, но требуют разметки."


def build_raw_income_plan_from_operations(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int = 6,
    strategy: str = "median",
    buffer_percent: float = 0,
    round_to: int = 500,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if operations.empty:
        return pd.DataFrame(columns=RAW_INCOME_PLAN_COLUMNS)
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months) & df["direction"].isin(["income", "incoming"]) & df["operation_datetime"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_INCOME_PLAN_COLUMNS)

    inferred = df.apply(infer_raw_income_category, axis=1, result_type="expand")
    inferred.columns = ["raw_income_category", "raw_status", "raw_comment"]
    df = pd.concat([df, inferred], axis=1)
    df = df[df["raw_status"] != "excluded"].copy()
    if df.empty:
        return pd.DataFrame(columns=RAW_INCOME_PLAN_COLUMNS)
    df["raw_income_amount"] = df["bank_amount"].abs()
    monthly = df.groupby(["raw_income_category", "month"], as_index=False)["raw_income_amount"].sum()
    meta = (
        df.groupby("raw_income_category")
        .agg(status=("raw_status", lambda values: "needs_classification" if "needs_classification" in set(values) else "ready"),
             comment=("raw_comment", "first"))
        .reset_index()
    )
    rows = []
    for category, group in monthly.groupby("raw_income_category"):
        values = group["raw_income_amount"]
        mean = float(values.mean())
        median = float(values.median())
        p75 = float(values.quantile(0.75))
        base = p75 if strategy == "p75" else median
        suggested = round_up(max(0, base) * (1 + buffer_percent / 100), round_to)
        rows.append(
            {
                "income_category": category,
                "months_count": int(group["month"].nunique()),
                "mean": mean,
                "median": median,
                "p75": p75,
                "suggested_plan": suggested,
                "status": str(meta.loc[meta["raw_income_category"] == category, "status"].iloc[0]),
                "comment": str(meta.loc[meta["raw_income_category"] == category, "comment"].iloc[0]),
            }
        )
    return pd.DataFrame(rows, columns=RAW_INCOME_PLAN_COLUMNS).sort_values("suggested_plan", ascending=False)


def planning_attention_summary(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    columns = [
        "anchor",
        "direction",
        "count",
        "total_sum",
        "median_monthly_sum",
        "months_seen",
        "examples",
        "has_active_rule",
        "matched_rule_id",
        "operation_type_after_reclassify",
        "classification_source",
        "needs_plan_review",
        "reason",
        "expense_nature",
        "operation_ids",
        "first_operation_id",
        "first_operation_datetime",
    ]
    if operations.empty:
        return pd.DataFrame(columns=columns)
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    for column, default in [("classification_source", ""), ("rule_id", ""), ("needs_review", False), ("plan_exclusion_reason", "")]:
        if column not in df.columns:
            df[column] = default
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months) & df["direction"].isin(["expense", "outgoing"])]
    if df.empty:
        return pd.DataFrame(columns=columns)
    matched_rules = df.apply(lambda row: active_plan_rule_for_row(row, profile), axis=1)
    df["has_active_rule"] = matched_rules.apply(lambda rule: bool(rule))
    df["matched_rule_id"] = matched_rules.apply(lambda rule: rule.get("id", "") if rule else "")
    df["operation_type_after_reclassify"] = df["operation_type"]
    df["needs_plan_review"] = df.apply(needs_plan_review, axis=1)
    df["reason"] = df.apply(
        lambda row: "уже обработано правилом" if row["has_active_rule"] or is_resolved_for_plan(row) else "нужно разобрать",
        axis=1,
    )
    df = df[df["needs_plan_review"] == True]
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["abs_amount"] = df["bank_amount"].abs()
    df["anchor"] = df["person_anchor"].fillna("")
    empty_anchor = df["anchor"] == ""
    df.loc[empty_anchor, "anchor"] = df.loc[empty_anchor, "merchant_anchor"].fillna("")
    empty_anchor = df["anchor"] == ""
    df.loc[empty_anchor, "anchor"] = df.loc[empty_anchor, "normalized_description"].fillna(df.loc[empty_anchor, "description"])
    spending_like = df[
        df["operation_type"].isin(["Проверить", "cash_withdrawal", "Наличные / проверить"])
        | df["raw_category"].fillna("").str.contains("Перевод|налич", case=False, regex=True)
    ]
    if spending_like.empty:
        return pd.DataFrame(columns=columns)
    monthly = spending_like.groupby(["anchor", "month"], as_index=False)["abs_amount"].sum()
    grouped = (
        spending_like.groupby("anchor")
        .agg(
            direction=("direction", "first"),
            count=("id", "count"),
            total_sum=("abs_amount", "sum"),
            months_seen=("month", "nunique"),
            examples=("description", lambda values: " | ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            has_active_rule=("has_active_rule", "max"),
            matched_rule_id=("matched_rule_id", lambda values: next((value for value in values if value), "")),
            operation_type_after_reclassify=("operation_type_after_reclassify", lambda values: " / ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            classification_source=("classification_source", lambda values: " / ".join(list(dict.fromkeys(values.fillna("").astype(str)))[:3])),
            needs_plan_review=("needs_plan_review", "max"),
            reason=("reason", lambda values: " / ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            operation_ids=("id", lambda values: list(values.dropna().astype(str))),
            first_operation_id=("id", "first"),
            first_operation_datetime=("operation_datetime", "first"),
        )
        .reset_index()
    )
    medians = monthly.groupby("anchor")["abs_amount"].median().rename("median_monthly_sum")
    grouped = grouped.merge(medians, on="anchor", how="left")
    grouped["expense_nature"] = grouped.apply(classify_expense_nature, axis=1)
    return grouped.reindex(columns=columns).sort_values(["months_seen", "total_sum"], ascending=[False, False])


def classify_expense_nature(row: pd.Series) -> str:
    total_sum = float(row.get("total_sum") or 0)
    months_seen = int(row.get("months_seen") or 0)
    count = int(row.get("count") or 0)
    if count > 1 or months_seen >= 2:
        return "recurring"
    if count == 1 and months_seen == 1 and total_sum >= LARGE_ONEOFF_THRESHOLD:
        return "oneoff_large"
    if count == 1 and months_seen == 1 and total_sum < MINOR_OPERATION_THRESHOLD:
        return "oneoff_minor"
    return "unknown"


def classify_candidate_importance(row: pd.Series) -> str:
    nature = str(row.get("expense_nature") or classify_expense_nature(row))
    total_sum = float(row.get("total_sum") or 0)
    median_monthly_sum = float(row.get("median_monthly_sum") or 0)
    months_seen = int(row.get("months_seen") or 0)
    count = int(row.get("count") or 0)
    if nature == "oneoff_minor":
        return "minor_oneoff"
    if nature == "oneoff_large":
        return "oneoff_large"
    if nature == "recurring":
        return "important"
    if total_sum >= 3000 or median_monthly_sum >= 1500 or months_seen >= 2 or count >= 3:
        return "important"
    return "minor"


def get_plan_review_candidates_from_operations(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    candidates = planning_attention_summary(operations, report_month, history_months, profile)
    if candidates.empty:
        return candidates.assign(importance_level=pd.Series(dtype=str))
    candidates = candidates.copy()
    candidates["importance_level"] = candidates.apply(classify_candidate_importance, axis=1)
    return candidates.sort_values(["median_monthly_sum", "total_sum", "count"], ascending=[False, False, False])


def income_attention_summary(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    columns = [
        "anchor",
        "direction",
        "count",
        "total_sum",
        "median_monthly_sum",
        "months_seen",
        "examples",
        "has_active_rule",
        "matched_rule_id",
        "operation_type_after_reclassify",
        "classification_source",
        "needs_plan_review",
        "reason",
        "importance_level",
        "expense_nature",
        "operation_ids",
        "first_operation_id",
        "first_operation_datetime",
    ]
    if operations.empty:
        return pd.DataFrame(columns=columns)
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    for column, default in [("classification_source", ""), ("rule_id", ""), ("needs_review", False), ("plan_exclusion_reason", "")]:
        if column not in df.columns:
            df[column] = default
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months) & df["direction"].isin(["income", "incoming"])]
    if df.empty:
        return pd.DataFrame(columns=columns)
    matched_rules = df.apply(lambda row: active_plan_rule_for_row(row, profile), axis=1)
    df["has_active_rule"] = matched_rules.apply(lambda rule: bool(rule))
    df["matched_rule_id"] = matched_rules.apply(lambda rule: rule.get("id", "") if rule else "")
    df["operation_type_after_reclassify"] = df["operation_type"]
    df["needs_plan_review"] = df.apply(needs_plan_review, axis=1)
    df["reason"] = df.apply(
        lambda row: "уже обработано правилом" if row["has_active_rule"] or is_resolved_for_plan(row) else "нужно разобрать",
        axis=1,
    )
    df = df[df["needs_plan_review"] == True].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["abs_amount"] = df["bank_amount"].abs()
    df["anchor"] = df["person_anchor"].fillna("")
    empty_anchor = df["anchor"] == ""
    df.loc[empty_anchor, "anchor"] = df.loc[empty_anchor, "merchant_anchor"].fillna("")
    empty_anchor = df["anchor"] == ""
    df.loc[empty_anchor, "anchor"] = df.loc[empty_anchor, "normalized_description"].fillna(df.loc[empty_anchor, "description"])
    monthly = df.groupby(["anchor", "month"], as_index=False)["abs_amount"].sum()
    grouped = (
        df.groupby("anchor")
        .agg(
            direction=("direction", "first"),
            count=("id", "count"),
            total_sum=("abs_amount", "sum"),
            months_seen=("month", "nunique"),
            examples=("description", lambda values: " | ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            has_active_rule=("has_active_rule", "max"),
            matched_rule_id=("matched_rule_id", lambda values: next((value for value in values if value), "")),
            operation_type_after_reclassify=("operation_type_after_reclassify", lambda values: " / ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            classification_source=("classification_source", lambda values: " / ".join(list(dict.fromkeys(values.fillna("").astype(str)))[:3])),
            needs_plan_review=("needs_plan_review", "max"),
            reason=("reason", lambda values: " / ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
            operation_ids=("id", lambda values: list(values.dropna().astype(str))),
            first_operation_id=("id", "first"),
            first_operation_datetime=("operation_datetime", "first"),
        )
        .reset_index()
    )
    medians = monthly.groupby("anchor")["abs_amount"].median().rename("median_monthly_sum")
    grouped = grouped.merge(medians, on="anchor", how="left")
    grouped["expense_nature"] = grouped.apply(classify_expense_nature, axis=1)
    grouped["importance_level"] = grouped.apply(classify_candidate_importance, axis=1)
    return grouped.reindex(columns=columns).sort_values(["median_monthly_sum", "total_sum", "count"], ascending=[False, False, False])


def get_income_review_candidates_from_operations(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int,
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    return income_attention_summary(operations, report_month, history_months, profile)


def get_plan_review_candidates(profile_id: str, history_months: int, report_month: str | None = None) -> pd.DataFrame:
    from storage import latest_month_with_operations, load_profile, operations_df

    profile = load_profile(profile_id)
    report_month = report_month or latest_month_with_operations(profile_id)
    if not report_month:
        return pd.DataFrame(columns=["anchor", "direction", "count", "total_sum", "median_monthly_sum", "months_seen", "examples", "importance_level"])
    return get_plan_review_candidates_from_operations(operations_df(profile_id), report_month, history_months, profile)


def plan_coverage_score(
    operations: pd.DataFrame,
    report_month: str,
    history_months: int,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    months = previous_full_months(report_month, history_months)
    df = prepare_planning_dataframe(operations, profile)
    if df.empty:
        return {"coverage": 0.0, "total_spending_like_amount": 0.0, "classified_plan_amount": 0.0, "unknown_count": 0}
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    df["month"] = df["operation_datetime"].dt.to_period("M").astype(str)
    df = df[df["month"].isin(months)]
    if df.empty:
        return {"coverage": 0.0, "total_spending_like_amount": 0.0, "classified_plan_amount": 0.0, "unknown_count": 0}
    personal_expenses = df[(df["count_in_plan"] == True) & (df["planning_amount"] > 0)]["planning_amount"].sum()
    unknown_outgoing = df[
        (df["count_in_plan"] == False)
        & (df["direction"] == "expense")
        & (
            df["operation_type"].isin(["Проверить", "cash_withdrawal", "Наличные / проверить"])
            | df["raw_category"].fillna("").str.contains("Перевод|налич", case=False, regex=True)
        )
    ]["bank_amount"].abs().sum()
    attention = planning_attention_summary(operations, report_month, history_months, profile)
    minor_unknown = 0.0
    if not attention.empty:
        attention = attention.copy()
        attention["importance_level"] = attention.apply(classify_candidate_importance, axis=1)
        minor_unknown = float(attention.loc[attention["importance_level"] == "minor_oneoff", "total_sum"].sum())
    unknown_for_coverage = max(0.0, float(unknown_outgoing) - minor_unknown)
    total = float(personal_expenses + unknown_for_coverage)
    classified = float(df[df["count_in_plan"] == True]["planning_amount"].clip(lower=0).sum())
    coverage = classified / total if total else 1.0
    return {
        "coverage": float(coverage),
        "total_spending_like_amount": total,
        "classified_plan_amount": classified,
        "excluded_known_amount": float(
            df[
                (df["count_in_plan"] == False)
                & (df["operation_type"].isin(["Внутренний перевод", "Проектный расход", "Проектный приход", "Не учитывать"]))
            ]["bank_amount"].abs().sum()
        ),
        "unknown_outgoing_amount": float(unknown_for_coverage),
        "unknown_count": int(len(attention)),
    }


def recommended_plan_totals(recommended: pd.DataFrame) -> dict[str, float]:
    if recommended.empty or "suggested_plan" not in recommended.columns:
        return {
            "recommended_total": 0.0,
            "ready_total": 0.0,
            "needs_classification_total": 0.0,
            "low_history_total": 0.0,
        }
    df = recommended.copy()
    if "status" not in df.columns:
        df["status"] = "ready"
    return {
        "recommended_total": float(df["suggested_plan"].sum()),
        "ready_total": float(df.loc[df["status"] == "ready", "suggested_plan"].sum()),
        "needs_classification_total": float(df.loc[df["status"] == "needs_classification", "suggested_plan"].sum()),
        "low_history_total": float(df.loc[df["status"] == "low_history", "suggested_plan"].sum()),
    }


def calculate_plan_coverage(
    operations_or_profile_id: pd.DataFrame | str,
    report_month: str | int | None = None,
    history_months: int = 6,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(operations_or_profile_id, str):
        from storage import latest_month_with_operations, load_profile, operations_df

        profile_id = operations_or_profile_id
        if isinstance(report_month, int):
            history_months = report_month
            report_month = None
        profile = load_profile(profile_id)
        report_month = report_month or latest_month_with_operations(profile_id)
        if not report_month:
            return {"coverage": 0.0, "total_spending_like_amount": 0.0, "classified_plan_amount": 0.0, "excluded_known_amount": 0.0, "unknown_outgoing_amount": 0.0, "unknown_count": 0}
        return plan_coverage_score(operations_df(profile_id), str(report_month), history_months, profile)
    return plan_coverage_score(operations_or_profile_id, str(report_month), history_months, profile)
