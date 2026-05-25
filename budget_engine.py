from __future__ import annotations

from datetime import date

import pandas as pd


def dashboard_metrics(operations: pd.DataFrame, monthly_limit: float = 0) -> dict[str, float]:
    if operations.empty:
        return {
            "personal_income": 0.0,
            "gross_expense": 0.0,
            "fund_expense": 0.0,
            "compensation": 0.0,
            "net_expense": 0.0,
            "balance": 0.0,
            "limit": float(monthly_limit or 0),
            "limit_left": float(monthly_limit or 0),
            "review_count": 0,
        }
    amount_column = "budget_amount" if "budget_amount" in operations.columns else "personal_amount"
    personal_income = operations.loc[operations["operation_type"] == "Личный доход", amount_column].sum()
    gross_expense = operations.loc[operations["operation_type"] == "Личный расход", amount_column].sum()
    fund_expense = operations.loc[operations["operation_type"] == "Расход из фонда", amount_column].sum()
    compensation = operations.loc[
        operations["operation_type"] == "Компенсация совместных расходов", amount_column
    ].sum()
    net_expense = gross_expense + fund_expense + compensation
    balance = personal_income - net_expense
    limit = float(monthly_limit or 0)
    return {
        "personal_income": float(personal_income),
        "gross_expense": float(gross_expense),
        "fund_expense": float(fund_expense),
        "compensation": float(compensation),
        "net_expense": float(net_expense),
        "balance": float(balance),
        "limit": limit,
        "limit_left": float(limit - net_expense) if limit else 0.0,
        "review_count": int(operations["needs_review"].sum()),
    }


def plan_fact(operations: pd.DataFrame, plan: pd.DataFrame) -> pd.DataFrame:
    if operations.empty:
        fact = pd.DataFrame(columns=["budget_category", "fact"])
    else:
        fact_operations = operations[
            operations["operation_type"].isin(
                ["Личный расход", "Расход из фонда", "Компенсация совместных расходов"]
            )
        ]
        amount_column = "budget_amount" if "budget_amount" in fact_operations.columns else "personal_amount"
        fact = (
            fact_operations
            .groupby("budget_category", as_index=False)[amount_column]
            .sum()
            .rename(columns={amount_column: "fact"})
        )
    result = plan.rename(columns={"suggested_plan": "plan"}).merge(fact, how="outer", on="budget_category")
    if result.empty:
        return pd.DataFrame(columns=["budget_category", "plan", "fact", "diff"])
    result[["plan", "fact"]] = result[["plan", "fact"]].fillna(0)
    result["diff"] = result["plan"] - result["fact"]
    return result.sort_values("fact", ascending=False)


def income_plan_fact(operations: pd.DataFrame, income_plan: pd.DataFrame) -> pd.DataFrame:
    if operations.empty:
        fact = pd.DataFrame(columns=["income_category", "fact"])
    else:
        amount_column = "budget_amount" if "budget_amount" in operations.columns else "personal_amount"
        fact = (
            operations[operations["operation_type"] == "Личный доход"]
            .groupby("budget_category", as_index=False)[amount_column]
            .sum()
            .rename(columns={"budget_category": "income_category", amount_column: "fact"})
        )
    result = income_plan.rename(columns={"suggested_plan": "plan"}).merge(fact, how="outer", on="income_category")
    if result.empty:
        return pd.DataFrame(columns=["income_category", "plan", "fact", "diff"])
    result[["plan", "fact"]] = result[["plan", "fact"]].fillna(0)
    result["diff"] = result["fact"] - result["plan"]
    return result.sort_values("fact", ascending=False)


def financial_health_assessment(
    metrics: dict[str, float],
    days_elapsed: int,
    days_in_month: int,
    review_count: int,
) -> dict[str, float | str]:
    income = float(metrics.get("personal_income", 0) or 0)
    net_expense = float(metrics.get("net_expense", 0) or 0)
    balance = float(metrics.get("balance", 0) or 0)
    limit = float(metrics.get("limit", 0) or 0)
    expense_to_income_ratio = net_expense / income if income > 0 else 0.0
    savings_rate = balance / income if income > 0 else 0.0
    budget_used_ratio = net_expense / limit if limit > 0 else 0.0
    month_progress_ratio = days_elapsed / days_in_month if days_in_month > 0 else 0.0
    if review_count >= 10:
        status = "Данные требуют проверки"
        message = f"Расчёт неполный: есть {review_count} операций на проверку."
    elif income <= 0:
        status = "Данные требуют проверки"
        message = "Доходы за месяц пока не полностью отражены."
    elif expense_to_income_ratio > 1:
        status = "Плохо"
        message = "Расходы уже превышают личные доходы месяца."
    elif expense_to_income_ratio > 0.85:
        status = "Напряжённо"
        message = f"Внимание: расходы уже составляют {expense_to_income_ratio:.0%} от доходов."
    elif expense_to_income_ratio > 0.70:
        status = "Нормально"
        message = f"Месяц в норме: расходы составляют {expense_to_income_ratio:.0%} от доходов."
    else:
        status = "Хорошо"
        message = f"Месяц в норме: расходы составляют {expense_to_income_ratio:.0%} от доходов."
    if limit > 0 and budget_used_ratio > month_progress_ratio + 0.15 and status in {"Хорошо", "Нормально"}:
        status = "Напряжённо"
        message = f"Прошло {month_progress_ratio:.0%} месяца, использовано {budget_used_ratio:.0%} лимита."
    return {
        "status": status,
        "message": message,
        "expense_to_income_ratio": expense_to_income_ratio,
        "savings_rate": savings_rate,
        "budget_used_ratio": budget_used_ratio,
        "month_progress_ratio": month_progress_ratio,
    }
