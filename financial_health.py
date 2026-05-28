from __future__ import annotations

import calendar
from datetime import date
from typing import Any

import pandas as pd

from budget_engine import dashboard_metrics, plan_fact
from debug_exports import write_debug_json


def _money_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _month_bounds(report_month: str) -> tuple[date, date]:
    year, month = [int(part) for part in report_month.split("-")[:2]]
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _plan_limit(plan: pd.DataFrame) -> float:
    if plan is None or plan.empty:
        return 0.0
    if "plan" in plan.columns:
        return float(pd.to_numeric(plan["plan"], errors="coerce").fillna(0).sum())
    if "suggested_plan" in plan.columns:
        return float(pd.to_numeric(plan["suggested_plan"], errors="coerce").fillna(0).sum())
    return 0.0


def _status_label_for_data_quality(score: float) -> str:
    if score >= 85:
        return "данные достаточно чистые"
    if score >= 60:
        return "есть что уточнить"
    return "расчёт предварительный"


def _recommendation(title: str, text: str, severity: str, action_label: str, action_target: str, **extra: Any) -> dict[str, Any]:
    return {
        "title": title,
        "text": text,
        "severity": severity,
        "action_label": action_label,
        "action_target": action_target,
        **extra,
    }


def _sort_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"danger": 0, "warning": 1, "info": 2}
    return sorted(recommendations, key=lambda item: order.get(item.get("severity", "info"), 3))


def _category_risks(operations: pd.DataFrame, plan: pd.DataFrame) -> tuple[list[dict[str, Any]], float]:
    risks: list[dict[str, Any]] = []
    categories_without_limit_amount = 0.0
    pf = plan_fact(operations, plan)
    if pf.empty:
        return risks, categories_without_limit_amount
    for _, row in pf.iterrows():
        category = str(row.get("budget_category") or "")
        fact = _money_value(row.get("fact"))
        limit = _money_value(row.get("plan"))
        if fact <= 0 and limit <= 0:
            continue
        if limit <= 0 and fact > 0:
            status = "no_limit"
            categories_without_limit_amount += fact
            message = f"В категории есть расходы на {fact:,.0f} ₽, но лимит не задан.".replace(",", " ")
        else:
            usage = fact / limit if limit else 0.0
            remaining = limit - fact
            if usage > 1:
                status = "overspent"
                message = f"Категория превышена на {abs(remaining):,.0f} ₽.".replace(",", " ")
            elif usage >= 0.85:
                status = "near_limit"
                message = f"Категория почти исчерпана: осталось {remaining:,.0f} ₽.".replace(",", " ")
            else:
                status = "ok"
                message = "Категория в норме."
        is_review_category = category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}
        if status in {"overspent", "near_limit"} or (status == "no_limit" and fact > 3000) or is_review_category:
            risk_status = status
            risk_message = message
            if is_review_category and status != "no_limit":
                risk_status = "needs_review"
                risk_message = "В категории есть операции, которые лучше уточнить."
            risks.append(
                {
                    "category": category,
                    "fact": fact,
                    "plan": limit,
                    "usage_percent": fact / limit if limit else None,
                    "remaining": limit - fact,
                    "status": risk_status,
                    "message": risk_message,
                }
            )
    risk_order = {"overspent": 0, "needs_review": 1, "near_limit": 2, "no_limit": 3, "ok": 4}
    risks.sort(key=lambda item: (risk_order.get(item["status"], 5), -item["fact"]))
    return risks, categories_without_limit_amount


def build_financial_health_report(
    profile_id: str,
    report_month: str,
    operations: pd.DataFrame,
    plan: pd.DataFrame,
    income_plan: pd.DataFrame | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    start_date, end_date = _month_bounds(report_month)
    days_in_month = (end_date - start_date).days + 1
    if today < start_date:
        days_passed = 0
    elif today > end_date:
        days_passed = days_in_month
    else:
        days_passed = (today - start_date).days + 1
    days_left = max(0, days_in_month - days_passed)
    month_progress = days_passed / days_in_month if days_in_month else 0.0

    month_plan = _plan_limit(plan)
    metrics = dashboard_metrics(operations, month_plan)
    clean_expenses = _money_value(metrics.get("net_expense"))
    personal_income = _money_value(metrics.get("personal_income"))
    gross_expenses = _money_value(metrics.get("gross_expense"))
    compensations = _money_value(metrics.get("compensation"))
    balance = personal_income - clean_expenses
    remaining_plan = month_plan - clean_expenses
    plan_used_percent = clean_expenses / month_plan if month_plan > 0 else None
    income_used_percent = clean_expenses / personal_income if personal_income > 0 else None

    expected_spend_by_today = month_plan * month_progress
    pace_delta = clean_expenses - expected_spend_by_today
    if month_plan <= 0:
        pace_status = "план не задан"
    elif clean_expenses > month_plan:
        pace_status = "план почти исчерпан" if days_left else "план превышен"
    elif pace_delta > month_plan * 0.15:
        pace_status = "расходы идут быстрее плана"
    else:
        pace_status = "темп расходов в норме"

    safe_total_left = max(remaining_plan, 0.0)
    safe_per_day = safe_total_left / days_left if days_left > 0 else 0.0
    average_daily_plan = month_plan / days_in_month if days_in_month and month_plan else 0.0
    if remaining_plan < 0:
        safe_status = "overspent"
    elif average_daily_plan and safe_per_day > average_daily_plan * 0.8:
        safe_status = "ok"
    elif average_daily_plan and safe_per_day >= average_daily_plan * 0.4:
        safe_status = "tight"
    else:
        safe_status = "danger" if month_plan else "tight"

    if income_used_percent is None:
        ratio_status = "unknown"
        ratio_text = "Доходы месяца не определены или требуют разметки."
    elif income_used_percent < 0.6:
        ratio_status = "good"
        ratio_text = f"Расходы занимают {income_used_percent:.0%} личных доходов. Есть пространство для накоплений."
    elif income_used_percent < 0.85:
        ratio_status = "ok"
        ratio_text = f"Расходы занимают {income_used_percent:.0%} личных доходов."
    elif income_used_percent <= 1:
        ratio_status = "warning"
        ratio_text = f"Расходы уже составляют {income_used_percent:.0%} доходов. Месяц напряжённый."
    else:
        ratio_status = "danger"
        ratio_text = "Расходы превышают личные доходы месяца. Нужна проверка доходов или сокращение трат."

    category_risks, categories_without_limit_amount = _category_risks(operations, plan)

    if operations is None or operations.empty:
        review_count = 0
        review_amount = 0.0
        unresolved_transfers_amount = 0.0
        income_unknown_amount = 0.0
        outgoing_cashflow_like_amount = 0.0
    else:
        review_mask = operations.get("needs_review", pd.Series(False, index=operations.index)).fillna(False).astype(bool)
        review_count = int(review_mask.sum())
        review_amount = float(operations.loc[review_mask, "bank_amount"].abs().sum()) if "bank_amount" in operations.columns else 0.0
        direction = operations.get("direction", pd.Series("", index=operations.index)).fillna("")
        budget_category = operations.get("budget_category", pd.Series("", index=operations.index)).fillna("")
        operation_type = operations.get("operation_type", pd.Series("", index=operations.index)).fillna("")
        amount_abs = operations.get("bank_amount", pd.Series(0, index=operations.index)).abs()
        unresolved_mask = direction.isin(["expense", "outgoing"]) & (
            budget_category.isin(["Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"])
            | operation_type.eq("Проверить")
            | review_mask
        )
        unresolved_transfers_amount = float(amount_abs[unresolved_mask].sum())
        income_unknown_mask = direction.isin(["income", "incoming"]) & (operation_type.eq("Проверить") | review_mask)
        income_unknown_amount = float(amount_abs[income_unknown_mask].sum())
        excluded_types = {"Внутренний перевод", "Проектный оборот", "Не учитывать"}
        outgoing_cashflow_like_amount = float(amount_abs[direction.isin(["expense", "outgoing"]) & ~operation_type.isin(excluded_types)].sum())

    confidence_score = 100
    quality_basis = max(clean_expenses, gross_expenses, outgoing_cashflow_like_amount, review_amount, 1.0)
    if month_plan <= 0:
        confidence_score -= 25
    if personal_income <= 0:
        confidence_score -= 10
    if review_count > 0:
        confidence_score -= 10
    if review_amount > quality_basis * 0.2:
        confidence_score -= 20
    if review_amount > quality_basis * 0.5:
        confidence_score -= 15
    if unresolved_transfers_amount > quality_basis * 0.2:
        confidence_score -= 20
    if review_count > 20:
        confidence_score -= 45
    if income_unknown_amount > 0:
        confidence_score -= 20
    if categories_without_limit_amount > 0:
        confidence_score -= 10
    if clean_expenses and categories_without_limit_amount > clean_expenses * 0.2:
        confidence_score -= 10
    owner_mismatch_files_count = 0
    confidence_score = max(0, min(100, confidence_score))

    data_quality = {
        "operations_need_review_count": review_count,
        "operations_need_review_amount": review_amount,
        "unresolved_transfers_amount": unresolved_transfers_amount,
        "income_unknown_amount": income_unknown_amount,
        "categories_without_limit_amount": categories_without_limit_amount,
        "outgoing_cashflow_like_amount": outgoing_cashflow_like_amount,
        "owner_mismatch_files_count": owner_mismatch_files_count,
        "duplicate_skipped_count": 0,
        "confidence_score": confidence_score,
        "status": _status_label_for_data_quality(confidence_score),
    }

    recommendations: list[dict[str, Any]] = []
    if review_count:
        recommendations.append(
            _recommendation(
                "Разберите операции на проверку",
                f"Есть {review_count} операций, которые могут искажать расчёт.",
                "warning" if review_count <= 20 else "danger",
                "Перейти к очистке",
                "cleanup",
            )
        )
    if unresolved_transfers_amount > max(clean_expenses, gross_expenses, 1.0) * 0.2:
        recommendations.append(
            _recommendation(
                "Разберите неясные списания",
                f"На проверке исходящие операции примерно на {unresolved_transfers_amount:,.0f} ₽. Они могут менять план и факт месяца.".replace(",", " "),
                "warning",
                "Перейти к очистке",
                "cleanup",
            )
        )
    if income_unknown_amount > 0:
        recommendations.append(
            _recommendation(
                "Проверьте поступления",
                f"Есть входящие операции на {income_unknown_amount:,.0f} ₽, которые неясно учитывать как доход или перевод.".replace(",", " "),
                "warning",
                "Проверить доходы",
                "income",
            )
        )
    if month_plan <= 0:
        recommendations.append(
            _recommendation(
                "Задайте план месяца",
                "Без плана сервис не может честно оценить темп расходов и остаток до конца месяца.",
                "warning",
                "Перейти к плану",
                "plan",
            )
        )
    if personal_income <= 0 and income_unknown_amount <= 0:
        recommendations.append(
            _recommendation(
                "Проверьте доходы месяца",
                "Личные доходы пока не определены, поэтому баланс месяца может быть неполным.",
                "info",
                "Проверить доходы",
                "income",
            )
        )
    for risk in category_risks:
        if risk["status"] == "no_limit":
            recommendations.append(
                _recommendation(
                    "Есть расходы без лимита",
                    f"В категории {risk['category']} есть расходы, но лимит не задан.",
                    "warning",
                    "Назначить лимит",
                    "plan",
                    category=risk["category"],
                )
            )
            break
    for risk in category_risks[:3]:
        if risk["status"] == "overspent":
            recommendations.append(
                _recommendation(
                    f"Перерасход в категории {risk['category']}",
                    risk["message"],
                    "danger",
                    "Открыть категорию",
                    "category",
                    category=risk["category"],
                )
            )
    if income_used_percent is not None and income_used_percent > 1:
        recommendations.append(
            _recommendation(
                "Расходы выше доходов",
                f"Чистые расходы превышают личные доходы месяца на {balance * -1:,.0f} ₽.".replace(",", " "),
                "danger",
                "Проверить доходы",
                "income",
            )
        )
    if month_plan and remaining_plan < month_plan * 0.1:
        recommendations.append(
            _recommendation(
                "План почти исчерпан",
                f"До конца месяца осталось {days_left} дней, доступно {safe_total_left:,.0f} ₽.".replace(",", " "),
                "warning" if remaining_plan >= 0 else "danger",
                "Посмотреть категории",
                "category",
            )
        )
    recommendations = _sort_recommendations(recommendations)[:5]

    if confidence_score < 60:
        month_status = "Расчёт неполный"
        severity = "incomplete"
    elif confidence_score < 85:
        month_status = "Расчёт предварительный"
        severity = "warning"
    elif month_plan and clean_expenses > month_plan:
        month_status = "Перерасход"
        severity = "danger"
    elif month_plan and plan_used_percent is not None and plan_used_percent > month_progress + 0.2:
        month_status = "Напряжённо"
        severity = "warning"
    elif income_used_percent is not None and income_used_percent > 0.9:
        month_status = "Напряжённо"
        severity = "warning"
    else:
        month_status = "В норме"
        severity = "good"
    if month_plan <= 0:
        summary_text = "План месяца не задан, темп расходов оценивается ограниченно."
    elif confidence_score < 60:
        if income_unknown_amount > 0:
            summary_text = "Расчёт предварительный: доходы месяца требуют проверки, поэтому баланс может быть неточным."
        else:
            summary_text = "Расчёт предварительный: сначала разберите операции на проверку."
    elif confidence_score < 85:
        if income_unknown_amount > 0:
            summary_text = "Расчёт предварительный: доходы месяца требуют проверки, поэтому баланс может быть неточным."
        elif categories_without_limit_amount > 0:
            summary_text = "Расчёт предварительный: есть расходы без лимита, план месяца может быть занижен."
        elif review_count > 0:
            summary_text = "Расчёт предварительный: часть операций ещё нужно уточнить."
        else:
            summary_text = "Расчёт предварительный: качество данных пока не идеальное."
    else:
        summary_text = (
            f"Прошло {month_progress:.0%} месяца, использовано "
            f"{plan_used_percent:.0%} плана. {pace_status.capitalize()}."
            if plan_used_percent is not None
            else "План месяца не задан, оценка ограничена."
        )

    report = {
        "profile_id": profile_id,
        "report_month": report_month,
        "month_status": month_status,
        "severity": severity,
        "summary_text": summary_text,
        "key_metrics": {
            "month_plan": month_plan,
            "clean_expenses": clean_expenses,
            "gross_expenses": gross_expenses,
            "compensations": compensations,
            "personal_income": personal_income,
            "balance": balance,
            "remaining_plan": remaining_plan,
            "days_passed": days_passed,
            "days_left": days_left,
            "month_progress_percent": month_progress,
            "plan_used_percent": plan_used_percent,
            "income_used_percent": income_used_percent,
        },
        "spending_pace": {
            "expected_spend_by_today": expected_spend_by_today,
            "pace_delta": pace_delta,
            "status": pace_status,
        },
        "income_expense_ratio": {
            "ratio": income_used_percent,
            "status": ratio_status,
            "text": ratio_text,
        },
        "category_risks": category_risks,
        "data_quality": data_quality,
        "recommendations": recommendations,
        "safe_to_spend": {
            "total_left": safe_total_left,
            "per_day": safe_per_day,
            "status": safe_status,
        },
    }
    write_financial_health_debug(report)
    return report


def write_financial_health_debug(report: dict[str, Any]) -> None:
    debug = {
        key: report.get(key)
        for key in [
            "key_metrics",
            "spending_pace",
            "income_expense_ratio",
            "category_risks",
            "data_quality",
            "recommendations",
            "month_status",
        ]
    }
    write_debug_json("financial_health_debug.json", debug)
