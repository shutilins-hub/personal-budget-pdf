from __future__ import annotations

from pathlib import Path
import json

import pandas as pd


EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


def export_operations_csv(operations: pd.DataFrame, profile_id: str) -> Path:
    EXPORTS_DIR.mkdir(exist_ok=True)
    path = EXPORTS_DIR / f"operations_{profile_id}.csv"
    operations.to_csv(path, index=False)
    return path


def write_import_debug(
    extracted_text: str,
    parsed_operations: list[dict],
    import_summary: dict,
) -> None:
    EXPORTS_DIR.mkdir(exist_ok=True)
    operations_df = pd.DataFrame(parsed_operations)
    (EXPORTS_DIR / "extracted_text_debug.txt").write_text(extracted_text, encoding="utf-8")
    operations_df.reindex(
        columns=[
            "source_file",
            "document_type",
            "bank",
            "account_type",
            "account_role",
            "account_id",
            "owner_name",
            "operation_datetime",
            "raw_category",
            "raw_description",
            "description",
            "normalized_description",
            "merchant_anchor",
            "person_anchor",
            "phone_anchor",
            "card_last4",
            "auth_code",
            "bank_amount",
            "direction",
            "cashflow_amount",
            "operation_type",
            "budget_category",
            "personal_amount",
            "budget_amount",
            "planning_amount",
            "debt_amount",
            "count_in_budget",
            "count_in_plan",
            "count_in_cashflow",
            "plan_category",
            "plan_exclusion_reason",
            "confidence",
            "classification_source",
            "needs_review",
            "duplicate_key",
            "linked_operation_id",
        ]
    ).to_csv(EXPORTS_DIR / "parsed_operations_debug.tsv", sep="\t", index=False)
    raw_category_summary(operations_df).to_csv(EXPORTS_DIR / "raw_category_summary.tsv", sep="\t", index=False)
    unrecognized_summary(operations_df).to_csv(EXPORTS_DIR / "unrecognized_summary.tsv", sep="\t", index=False)
    recurring_operations_summary(operations_df).to_csv(EXPORTS_DIR / "recurring_operations_summary.tsv", sep="\t", index=False)
    sber_blocks_debug(operations_df).to_csv(EXPORTS_DIR / "sber_operations_debug.tsv", sep="\t", index=False)
    (EXPORTS_DIR / "import_summary.json").write_text(
        json.dumps(import_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (EXPORTS_DIR / "document_detection_debug.json").write_text(
        json.dumps(import_summary.get("document_detection", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (EXPORTS_DIR / "account_metadata_debug.json").write_text(
        json.dumps(import_summary.get("account_metadata", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    operations_df.reindex(columns=["source_file", "duplicate_key", "operation_datetime", "bank_amount", "description"]).to_csv(
        EXPORTS_DIR / "dedup_debug.tsv",
        sep="\t",
        index=False,
    )
    operations_df.reindex(columns=["id", "linked_operation_id", "source_file", "operation_datetime", "bank_amount", "description"]).to_csv(
        EXPORTS_DIR / "internal_transfer_links_debug.tsv",
        sep="\t",
        index=False,
    )


def write_plan_debug(profile: dict, history_months_used: list[str] | None = None, warnings: list[str] | None = None) -> dict:
    EXPORTS_DIR.mkdir(exist_ok=True)
    plan = profile.get("plan", {}) or {}
    plan_sum = sum(float(value or 0) for value in plan.values())
    source = profile.get("plan_source")
    if not source:
        source = "stale_saved_plan" if plan else "default"
    debug = {
        "profile_id": profile.get("id"),
        "monthly_limit": float(profile.get("monthly_limit") or 0),
        "plan_source": source,
        "plan_updated_at": profile.get("plan_updated_at", ""),
        "history_months_used": history_months_used or profile.get("plan_history_months_used", []),
        "categories": plan,
        "category_count": len(plan),
        "category_sum": plan_sum,
        "auto_plan_accepted": bool(profile.get("auto_plan_accepted", False)),
        "warnings": warnings or [],
    }
    if debug["monthly_limit"] != plan_sum:
        debug["warnings"].append("monthly_limit не равен сумме категорий плана")
    (EXPORTS_DIR / "plan_debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    return debug


def write_layered_plan_debug(debug_tables: dict[str, pd.DataFrame]) -> None:
    EXPORTS_DIR.mkdir(exist_ok=True)
    mapping = {
        "plan_source_files": "plan_source_files_debug.tsv",
        "monthly_plan_totals": "monthly_plan_totals_debug.tsv",
        "excluded_by_reason": "excluded_by_reason_debug.tsv",
        "recommended_plan": "recommended_plan_debug.tsv",
    }
    for key, filename in mapping.items():
        table = debug_tables.get(key, pd.DataFrame())
        table.to_csv(EXPORTS_DIR / filename, sep="\t", index=False)


def raw_category_summary(operations: pd.DataFrame) -> pd.DataFrame:
    if operations.empty or "raw_category" not in operations:
        return pd.DataFrame(columns=["raw_category", "count", "total_abs_amount", "examples"])
    df = operations.copy()
    df["raw_category"] = df["raw_category"].fillna("").replace("", "Без категории")
    df["abs_amount"] = df["bank_amount"].abs()
    grouped = (
        df.groupby("raw_category")
        .agg(
            count=("id", "count"),
            total_abs_amount=("abs_amount", "sum"),
            examples=("description", lambda values: " | ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
        )
        .reset_index()
    )
    return grouped.sort_values(["count", "total_abs_amount"], ascending=[False, False])


def unrecognized_summary(operations: pd.DataFrame) -> pd.DataFrame:
    if operations.empty or "needs_review" not in operations:
        return pd.DataFrame(columns=["raw_category", "count", "total_abs_amount", "examples"])
    df = operations[operations["needs_review"] == True].copy()
    if df.empty:
        return pd.DataFrame(columns=["raw_category", "count", "total_abs_amount", "examples"])
    return raw_category_summary(df).rename(columns={"total_abs_amount": "sum"})


def normalize_merchant(description: str) -> str:
    text = " ".join((description or "").upper().split())
    for marker in [". ОПЕРАЦИЯ", " ОПЕРАЦИЯ ПО", ". OPERATION"]:
        if marker in text:
            text = text.split(marker)[0]
    return text[:80]


def recurring_operations_summary(operations: pd.DataFrame) -> pd.DataFrame:
    if operations.empty or "description" not in operations:
        return pd.DataFrame(columns=["merchant", "count", "sum", "suggested_category"])
    df = operations.copy()
    if "merchant_anchor" in df.columns:
        df["merchant"] = df["merchant_anchor"].fillna("")
        empty = df["merchant"] == ""
        df.loc[empty, "merchant"] = df.loc[empty, "description"].fillna("").map(normalize_merchant)
    else:
        df["merchant"] = df["description"].fillna("").map(normalize_merchant)
    df = df[df["merchant"] != ""]
    if df.empty:
        return pd.DataFrame(columns=["merchant", "count", "sum", "suggested_category"])
    grouped = (
        df.groupby("merchant")
        .agg(
            count=("id", "count"),
            sum=("personal_amount", "sum"),
            suggested_category=("budget_category", lambda values: values.mode().iloc[0] if not values.mode().empty else ""),
        )
        .reset_index()
    )
    grouped = grouped[grouped["count"] > 1]
    return grouped.sort_values(["count", "sum"], ascending=[False, False])


def recurring_people_summary(operations: pd.DataFrame) -> pd.DataFrame:
    if operations.empty or "person_anchor" not in operations:
        return pd.DataFrame(columns=["person", "count", "sum", "examples"])
    df = operations.copy()
    df["person"] = df["person_anchor"].fillna("")
    df = df[df["person"] != ""]
    if df.empty:
        return pd.DataFrame(columns=["person", "count", "sum", "examples"])
    grouped = (
        df.groupby("person")
        .agg(
            count=("id", "count"),
            sum=("bank_amount", "sum"),
            examples=("description", lambda values: " | ".join(list(dict.fromkeys(values.dropna().astype(str)))[:3])),
        )
        .reset_index()
    )
    return grouped[grouped["count"] > 1].sort_values(["count", "sum"], ascending=[False, False])


def sber_blocks_debug(operations: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "raw_block",
        "operation_date",
        "operation_time",
        "category",
        "amount",
        "balance",
        "processing_date",
        "auth_code",
        "description",
        "direction",
        "operation_type",
        "budget_amount",
        "needs_review",
    ]
    if operations.empty:
        return pd.DataFrame(columns=columns)
    df = operations[operations.get("bank", "") == "Сбер"].copy() if "bank" in operations else pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(
        {
            "raw_block": df.get("raw_block", ""),
            "operation_date": df.get("operation_date", ""),
            "operation_time": df.get("operation_time", ""),
            "category": df.get("raw_category", ""),
            "amount": df.get("amount_text", df.get("bank_amount", "")),
            "balance": df.get("balance_text", ""),
            "processing_date": df.get("processing_date", ""),
            "auth_code": df.get("auth_code", ""),
            "description": df.get("description", ""),
            "direction": df.get("direction", ""),
            "operation_type": df.get("operation_type", ""),
            "budget_amount": df.get("personal_amount", ""),
            "needs_review": df.get("needs_review", ""),
        }
    )
    return result.reindex(columns=columns)
