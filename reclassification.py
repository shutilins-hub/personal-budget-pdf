from __future__ import annotations

from typing import Any

import pandas as pd

from classifier import classify_operation
from planner import prepare_planning_dataframe
from storage import load_source_files, operations_df, load_profile, update_operation


RECLASSIFY_FIELDS = [
    "operation_type",
    "budget_category",
    "personal_amount",
    "budget_amount",
    "planning_amount",
    "count_in_budget",
    "count_in_plan",
    "plan_category",
    "plan_exclusion_reason",
    "needs_review",
    "classification_source",
    "confidence",
    "rule_id",
    "account_type",
    "account_role",
]
MANUAL_SOURCES = {"manual_review", "manual_quick_button"}
CREDIT_REPAYMENT_MARKERS = (
    "погашение кредит",
    "погашение задолж",
    "платеж по кредит",
    "платёж по кредит",
    "credit",
    "кредитн",
    "рассроч",
)


def is_manual_override(operation: dict[str, Any]) -> bool:
    return operation.get("classification_source") in MANUAL_SOURCES or str(operation.get("classification_source", "")).startswith("manual")


def normalize_for_compare(value: Any) -> Any:
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, int):
        return value
    return "" if value is None else value


def reclassify_operation(operation: dict[str, Any], profile: dict[str, Any], preserve_manual_overrides: bool = True) -> dict[str, Any]:
    original = dict(operation)
    if preserve_manual_overrides and is_manual_override(original):
        classified = original
    else:
        reset = dict(original)
        for key in [
            "operation_type",
            "budget_category",
            "personal_amount",
            "budget_amount",
            "planning_amount",
            "count_in_budget",
            "count_in_plan",
            "plan_category",
            "plan_exclusion_reason",
            "needs_review",
            "classification_source",
            "confidence",
            "rule_id",
        ]:
            reset.pop(key, None)
        classified = classify_operation(reset, profile)
        classified = apply_account_context_to_operation(classified, profile)
    planned = prepare_planning_dataframe(pd.DataFrame([classified]), profile).iloc[0].to_dict()
    return {**classified, **planned}


def is_credit_repayment_description(description: str) -> bool:
    normalized = " ".join(str(description or "").casefold().split())
    return any(marker in normalized for marker in CREDIT_REPAYMENT_MARKERS)


def apply_account_context_to_operation(operation: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    source_files = profile.get("source_files") or {}
    metadata = source_files.get(operation.get("source_file"), {})
    account_type = metadata.get("account_type") or operation.get("account_type") or "unknown"
    operation["account_type"] = account_type
    operation["account_role"] = account_type
    direction = operation.get("direction")
    description = operation.get("description", "")
    should_exclude = False
    source = ""
    if account_type in {"credit_card", "installment_card"} and direction == "income":
        should_exclude = True
        source = "account_type_repayment"
    elif account_type == "savings_account":
        operation_type = "Внутренний перевод"
        source = "account_type_savings"
        should_exclude = True
    elif account_type == "wallet" and direction == "income":
        operation_type = "Внутренний перевод"
        source = "account_type_wallet_topup"
        should_exclude = True
    elif account_type == "debit_account" and direction == "expense" and is_credit_repayment_description(description):
        should_exclude = True
        source = "account_type_repayment_transfer"
    if should_exclude:
        operation.update(
            operation_type=locals().get("operation_type", "Погашение кредита"),
            budget_category="Не учитывать",
            personal_amount=0.0,
            budget_amount=0.0,
            planning_amount=0.0,
            count_in_budget=False,
            count_in_plan=False,
            plan_category="Не учитывать",
            needs_review=False,
            confidence=0.9,
            classification_source=source,
        )
    return operation


def reclassify_profile_operations(profile_id: str, preserve_manual_overrides: bool = True) -> dict[str, int]:
    profile = load_profile(profile_id)
    profile["source_files"] = load_source_files(profile_id)
    operations = operations_df(profile_id)
    changed = 0
    processed = 0
    preserved_manual = 0
    for operation in operations.to_dict("records"):
        processed += 1
        if preserve_manual_overrides and is_manual_override(operation):
            preserved_manual += 1
        updated = reclassify_operation(operation, profile, preserve_manual_overrides)
        changes = {}
        for field in RECLASSIFY_FIELDS:
            before = normalize_for_compare(operation.get(field))
            after = normalize_for_compare(updated.get(field))
            if before != after:
                changes[field] = updated.get(field)
        if changes:
            update_operation(operation["id"], changes)
            changed += 1
    return {"processed": processed, "changed": changed, "preserved_manual": preserved_manual}
