from __future__ import annotations


EXPENSE_OPERATION_LABELS = [
    "Расход",
    "Перевод себе",
    "Деньги в долг",
    "Оборотные средства для проекта / работы",
    "Не учитывать",
]

INCOME_OPERATION_LABELS = [
    "Доход",
    "Компенсация",
    "Вернули долг",
    "Перевод себе",
    "Оборотные средства для проекта / работы",
    "Не учитывать",
]

OPERATION_LABEL_TO_TYPE = {
    "Расход": "Личный расход",
    "Доход": "Личный доход",
    "Компенсация": "Компенсация совместных расходов",
    "Перевод себе": "Внутренний перевод",
    "Деньги в долг": "Заём выдан",
    "Вернули долг": "Возврат займа",
    "Оборотные средства для проекта / работы": "Проектный оборот",
    "Не учитывать": "Не учитывать",
}

SPLIT_OPERATION_LABELS = [
    "Расход",
    "Доход",
    "Компенсация",
    "Перевод себе",
    "Деньги в долг",
    "Вернули долг",
    "Оборотные средства для проекта / работы",
    "Не учитывать",
]

SPLIT_LABELS_REQUIRING_CATEGORY = {"Расход", "Доход", "Компенсация"}


def operation_type_for_label(label: str) -> str:
    return OPERATION_LABEL_TO_TYPE.get(str(label or "").strip(), str(label or "").strip())


def split_label_requires_category(label: str) -> bool:
    return str(label or "").strip() in SPLIT_LABELS_REQUIRING_CATEGORY


def split_label_category_kind(label: str) -> str:
    normalized = str(label or "").strip()
    if normalized in {"Расход", "Компенсация"}:
        return "expense"
    if normalized == "Доход":
        return "income"
    return "none"


def build_split_allocation_from_ui(
    label: str,
    amount: float,
    category: str = "",
    comment: str = "",
) -> dict:
    operation_type = operation_type_for_label(label)
    category_value = str(category or "").strip() if split_label_requires_category(label) else ""
    return {
        "amount": abs(float(amount or 0)),
        "operation_type": operation_type,
        "budget_category": category_value,
        "comment": str(comment or "").strip(),
    }


def default_split_labels_for_direction(direction: str) -> list[str]:
    if str(direction or "").strip() == "income":
        return ["Компенсация", "Вернули долг"]
    return ["Расход", "Расход"]


def split_total_state(operation_amount: float, allocations: list[dict], tolerance: float = 0.01) -> dict:
    expected = abs(float(operation_amount or 0))
    distributed = sum(abs(float(row.get("amount") or 0)) for row in allocations)
    remaining = expected - distributed
    return {
        "operation_total": expected,
        "distributed": distributed,
        "remaining": remaining,
        "is_complete": round(abs(remaining), 2) <= tolerance,
    }
