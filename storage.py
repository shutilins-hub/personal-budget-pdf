from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
CONFIG_DIR = BASE_DIR / "config"
DB_PATH = DATA_DIR / "budget.sqlite3"
GLOBAL_RULE_CANDIDATES_PATH = DATA_DIR / "global_rule_candidates.json"
SERVICE_DESCRIPTION_MARKERS = (
    "Выписка по",
    "Страница",
    "Продолжение",
    "Дата формирования",
    "Дата закрытия",
    "Дата открытия",
    "Владелец счёта",
    "Номер счёта",
    "Остаток на",
    "ИТОГО",
    "Пополнение",
    "Списание",
    "ПАО Сбербанк",
    "Для проверки",
    "QR-код",
    "Генеральная лицензия",
    "ДАТА ОПЕРАЦИИ",
    "Дата обработки",
    "и код авторизации",
    "КАТЕГОРИЯ",
    "Описание операции",
    "СУММА В ВАЛЮТЕ СЧЁТА",
    "Сумма в валюте",
    "операции²",
    "ОСТАТОК СРЕДСТВ",
    "В валюте счёта",
    "За период",
)
TIME_ONLY_RE = r"^\d{2}:\d{2}$"
AUTH_CODE_RE = r"^\d{5,6}$"


def normalize_description(description: str) -> str:
    return " ".join((description or "").casefold().split())


def is_service_description(description: str) -> bool:
    normalized = normalize_description(description)
    return any(marker.casefold() in normalized for marker in SERVICE_DESCRIPTION_MARKERS)


def is_suspicious_operation(operation: dict[str, Any]) -> bool:
    description = normalize_description(operation.get("description", ""))
    raw_category = normalize_description(operation.get("raw_category", ""))
    if re.fullmatch(TIME_ONLY_RE, description):
        return True
    if re.fullmatch(AUTH_CODE_RE, description) and raw_category in {"", "проверить"}:
        return True
    amount = float(operation.get("bank_amount") or 0)
    if amount.is_integer() and 10000 <= abs(amount) <= 999999 and raw_category in {"", "проверить"}:
        return True
    return False


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_dirs()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                bank TEXT,
                source_file TEXT,
                source_file_name TEXT,
                import_batch_id TEXT,
                document_type TEXT,
                account_id TEXT,
                account_type TEXT,
                account_role TEXT,
                owner_name TEXT,
                operation_datetime TEXT,
                processing_date TEXT,
                description TEXT,
                raw_description TEXT,
                raw_category TEXT,
                bank_amount REAL,
                direction TEXT,
                cashflow_amount REAL,
                operation_type TEXT,
                budget_category TEXT,
                personal_amount REAL,
                budget_amount REAL,
                planning_amount REAL,
                count_in_budget INTEGER,
                count_in_plan INTEGER,
                count_in_cashflow INTEGER,
                plan_category TEXT,
                plan_exclusion_reason TEXT,
                debt_amount REAL,
                debt_type TEXT,
                confidence REAL,
                classification_source TEXT,
                needs_review INTEGER,
                rule_id TEXT,
                linked_operation_id TEXT,
                duplicate_key TEXT,
                comment TEXT,
                normalized_description TEXT,
                merchant_anchor TEXT,
                person_anchor TEXT,
                phone_anchor TEXT,
                card_last4 TEXT,
                auth_code TEXT,
                expense_nature TEXT,
                created_at TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(operations)").fetchall()}
        migrations = {
            "raw_description": "ALTER TABLE operations ADD COLUMN raw_description TEXT",
            "source_file_name": "ALTER TABLE operations ADD COLUMN source_file_name TEXT",
            "import_batch_id": "ALTER TABLE operations ADD COLUMN import_batch_id TEXT",
            "normalized_description": "ALTER TABLE operations ADD COLUMN normalized_description TEXT",
            "merchant_anchor": "ALTER TABLE operations ADD COLUMN merchant_anchor TEXT",
            "person_anchor": "ALTER TABLE operations ADD COLUMN person_anchor TEXT",
            "confidence": "ALTER TABLE operations ADD COLUMN confidence REAL DEFAULT 0",
            "classification_source": "ALTER TABLE operations ADD COLUMN classification_source TEXT",
            "budget_amount": "ALTER TABLE operations ADD COLUMN budget_amount REAL DEFAULT 0",
            "planning_amount": "ALTER TABLE operations ADD COLUMN planning_amount REAL DEFAULT 0",
            "count_in_budget": "ALTER TABLE operations ADD COLUMN count_in_budget INTEGER DEFAULT 0",
            "count_in_plan": "ALTER TABLE operations ADD COLUMN count_in_plan INTEGER DEFAULT 0",
            "plan_category": "ALTER TABLE operations ADD COLUMN plan_category TEXT",
            "plan_exclusion_reason": "ALTER TABLE operations ADD COLUMN plan_exclusion_reason TEXT",
            "account_type": "ALTER TABLE operations ADD COLUMN account_type TEXT",
            "account_role": "ALTER TABLE operations ADD COLUMN account_role TEXT",
            "document_type": "ALTER TABLE operations ADD COLUMN document_type TEXT",
            "account_id": "ALTER TABLE operations ADD COLUMN account_id TEXT",
            "owner_name": "ALTER TABLE operations ADD COLUMN owner_name TEXT",
            "cashflow_amount": "ALTER TABLE operations ADD COLUMN cashflow_amount REAL DEFAULT 0",
            "count_in_cashflow": "ALTER TABLE operations ADD COLUMN count_in_cashflow INTEGER DEFAULT 1",
            "debt_amount": "ALTER TABLE operations ADD COLUMN debt_amount REAL DEFAULT 0",
            "debt_type": "ALTER TABLE operations ADD COLUMN debt_type TEXT",
            "linked_operation_id": "ALTER TABLE operations ADD COLUMN linked_operation_id TEXT",
            "duplicate_key": "ALTER TABLE operations ADD COLUMN duplicate_key TEXT",
            "phone_anchor": "ALTER TABLE operations ADD COLUMN phone_anchor TEXT",
            "card_last4": "ALTER TABLE operations ADD COLUMN card_last4 TEXT",
            "auth_code": "ALTER TABLE operations ADD COLUMN auth_code TEXT",
            "expense_nature": "ALTER TABLE operations ADD COLUMN expense_nature TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)
        conn.execute(
            """
            UPDATE operations
            SET raw_description = description
            WHERE raw_description IS NULL OR raw_description = ''
            """
        )
        conn.execute(
            """
            UPDATE operations
            SET normalized_description = lower(trim(description))
            WHERE normalized_description IS NULL OR normalized_description = ''
            """
        )
        conn.execute("DROP INDEX IF EXISTS idx_operations_unique")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_operations_lookup
            ON operations(profile_id, bank, account_id, operation_datetime)
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_duplicate_key
            ON operations(duplicate_key)
            WHERE duplicate_key IS NOT NULL AND duplicate_key != ''
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_batches (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                source_file_name TEXT,
                bank TEXT,
                document_type TEXT,
                account_id TEXT,
                account_type TEXT,
                account_role TEXT,
                owner_name TEXT,
                period_start TEXT,
                period_end TEXT,
                imported_at TEXT,
                operations_found INTEGER,
                operations_inserted INTEGER,
                duplicates_skipped INTEGER,
                status TEXT,
                warning TEXT
            )
            """
        )


def load_json(path: Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_global_rule_candidates() -> list[dict[str, Any]]:
    return load_json(GLOBAL_RULE_CANDIDATES_PATH, [])


def record_global_rule_candidate(operation: dict[str, Any], suggested_category: str, profile_id: str) -> None:
    merchant = operation.get("merchant_anchor") or operation.get("person_anchor") or operation.get("normalized_description") or operation.get("description", "")
    merchant = str(merchant).strip()
    if not merchant:
        return
    candidates = load_global_rule_candidates()
    key = (normalize_description(merchant), suggested_category)
    now = datetime.now().isoformat(timespec="seconds")
    for candidate in candidates:
        candidate_key = (normalize_description(candidate.get("merchant_anchor", "")), candidate.get("suggested_category"))
        if candidate_key == key:
            profiles = set(candidate.get("profile_ids", []))
            profiles.add(profile_id)
            candidate["profile_ids"] = sorted(profiles)
            candidate["profiles_count"] = len(profiles)
            candidate["operations_count"] = int(candidate.get("operations_count") or 0) + 1
            candidate["confirmed_count"] = int(candidate.get("confirmed_count") or 0) + 1
            examples = candidate.setdefault("examples", [])
            description = str(operation.get("description") or "")
            if description and description not in examples:
                examples.append(description[:160])
                candidate["examples"] = examples[:5]
            candidate["updated_at"] = now
            save_json(GLOBAL_RULE_CANDIDATES_PATH, candidates)
            return
    candidates.insert(
        0,
        {
            "merchant_anchor": merchant,
            "suggested_category": suggested_category,
            "profiles_count": 1,
            "profile_ids": [profile_id],
            "operations_count": 1,
            "confirmed_count": 1,
            "confidence": 0.6,
            "examples": [str(operation.get("description") or "")[:160]],
            "status": "new",
            "created_at": now,
            "updated_at": now,
        },
    )
    save_json(GLOBAL_RULE_CANDIDATES_PATH, candidates)


def default_categories() -> list[str]:
    return load_json(CONFIG_DIR / "default_categories.json", [])


def categories_config() -> dict[str, list[dict[str, Any]]]:
    return load_json(CONFIG_DIR / "categories.json", {"expense": [], "income": []})


def default_operation_types() -> list[str]:
    return load_json(CONFIG_DIR / "default_operation_types.json", [])


def default_profile_template() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "default_profile.json", {})


def profile_path(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id / "profile.json"


def merchant_rules_path(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id / "merchant_rules.json"


def plan_rules_path(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id / "plan_rules.json"


def source_files_path(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id / "source_files.json"


def custom_categories_path(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id / "custom_categories.json"


def load_custom_categories(profile_id: str) -> dict[str, list[dict[str, Any]]]:
    return load_json(custom_categories_path(profile_id), {"expense": [], "income": []})


def save_custom_categories(profile_id: str, categories: dict[str, list[dict[str, Any]]]) -> None:
    save_json(custom_categories_path(profile_id), categories)


def category_labels(kind: str, profile_id: str | None = None, include_inactive: bool = False) -> list[str]:
    config = categories_config()
    rows = list(config.get(kind, []))
    if profile_id:
        rows.extend(load_custom_categories(profile_id).get(kind, []))
    labels: list[str] = []
    for row in rows:
        if include_inactive or row.get("active", True):
            label = str(row.get("label", "")).strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def normalize_rule_anchor(value: str) -> str:
    return normalize_description(value)


def infer_anchor_direction(anchor: str) -> str | None:
    normalized = normalize_rule_anchor(anchor)
    if "перевод от" in normalized:
        return "income"
    if "перевод для" in normalized:
        return "expense"
    return None


def rule_anchors(rule: dict[str, Any]) -> list[str]:
    anchors = []
    for key in ["merchant_anchor", "person_anchor"]:
        if rule.get(key):
            anchors.append(str(rule[key]))
    anchors.extend(str(item) for item in rule.get("match_contains_any", []) if item)
    anchors.extend(str(item) for item in rule.get("contains_any", []) if item)
    return anchors


def is_rule_direction_invalid(rule: dict[str, Any]) -> bool:
    direction = rule.get("direction")
    if not direction:
        return False
    for anchor in rule_anchors(rule):
        inferred = infer_anchor_direction(anchor)
        if inferred and inferred != direction:
            return True
    return False


def plan_rule_dedupe_key(rule: dict[str, Any], include_scenario: bool = True) -> tuple[Any, ...]:
    anchors = tuple(sorted(normalize_rule_anchor(item) for item in rule.get("match_contains_any", []) if item))
    base: tuple[Any, ...] = (rule.get("direction") or "", anchors)
    if include_scenario:
        return (*base, rule.get("scenario") or "")
    return base


def list_profiles() -> list[dict[str, Any]]:
    ensure_dirs()
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*/profile.json")):
        try:
            profiles.append(load_json(path, {}))
        except json.JSONDecodeError:
            continue
    return profiles


def create_profile(name: str, monthly_limit: float = 0) -> dict[str, Any]:
    template = default_profile_template()
    default_plan = template.get("plan", {})
    profile_id = uuid.uuid4().hex[:12]
    profile = {
        "id": profile_id,
        "name": name.strip() or "Новый профиль",
        "monthly_limit": float(monthly_limit or template.get("monthly_limit", sum(default_plan.values()))),
        "plan_strategy": template.get("plan_strategy", "median"),
        "buffer_percent": template.get("buffer_percent", 10),
        "round_to": template.get("round_to", 500),
        "plan": default_plan,
        "income_plan": template.get("income_plan", {}),
        "own_identity": template.get("own_identity", {"full_name": "", "name_aliases": [], "phones": [], "account_last4": [], "banks": []}),
        "rules": [],
    }
    save_json(profile_path(profile_id), profile)
    return profile


def get_or_create_default_profile() -> dict[str, Any]:
    profiles = list_profiles()
    if profiles:
        return profiles[0]
    template = default_profile_template()
    profile = {
        "id": template.get("id", "default"),
        "name": template.get("name", "Основной профиль"),
        "monthly_limit": template.get("monthly_limit", 0),
        "plan_strategy": template.get("plan_strategy", "median"),
        "buffer_percent": template.get("buffer_percent", 10),
        "round_to": template.get("round_to", 500),
        "plan": template.get("plan", {}),
        "income_plan": template.get("income_plan", {}),
        "own_identity": template.get("own_identity", {"full_name": "", "name_aliases": [], "phones": [], "account_last4": [], "banks": []}),
        "rules": [],
    }
    save_json(profile_path(profile["id"]), profile)
    return profile


def load_profile(profile_id: str) -> dict[str, Any]:
    profile = load_json(profile_path(profile_id), {})
    template = default_profile_template()
    changed = False
    if not profile.get("plan"):
        profile["plan"] = template.get("plan", {})
        changed = True
    if profile.get("plan"):
        plan_sum = sum(float(value or 0) for value in profile["plan"].values())
        if float(profile.get("monthly_limit") or 0) != plan_sum:
            profile["manual_limit"] = profile.get("manual_limit", profile.get("monthly_limit", 0))
            profile["monthly_limit"] = plan_sum
            changed = True
    if not profile.get("monthly_limit") and profile.get("plan"):
        profile["monthly_limit"] = sum(profile["plan"].values())
        changed = True
    if not profile.get("income_plan"):
        profile["income_plan"] = template.get("income_plan", {})
        changed = True
    if "own_identity" not in profile:
        profile["own_identity"] = template.get("own_identity", {"full_name": "", "name_aliases": [], "phones": [], "account_last4": [], "banks": []})
        changed = True
    for key in ["plan_strategy", "buffer_percent", "round_to", "rules"]:
        if key not in profile:
            profile[key] = template.get(key, [] if key == "rules" else None)
            changed = True
    if changed and profile.get("id"):
        save_profile(profile)
    clean_invalid_rules(profile_id)
    profile["merchant_rules"] = load_json(merchant_rules_path(profile_id), [])
    profile["plan_rules"] = load_json(plan_rules_path(profile_id), [])
    profile["source_files"] = load_json(source_files_path(profile_id), {})
    cleaned_plan_rules = clean_duplicate_plan_rules(profile_id, profile["plan_rules"])
    if len(cleaned_plan_rules) != len(profile["plan_rules"]):
        profile["plan_rules"] = cleaned_plan_rules
        save_plan_rules(profile_id, cleaned_plan_rules)
    return profile


def save_profile(profile: dict[str, Any]) -> None:
    profile_copy = dict(profile)
    profile_copy.pop("merchant_rules", None)
    profile_copy.pop("plan_rules", None)
    profile_copy.pop("source_files", None)
    save_json(profile_path(profile["id"]), profile_copy)


def load_source_files(profile_id: str) -> dict[str, Any]:
    return load_json(source_files_path(profile_id), {})


def save_source_file_metadata(profile_id: str, source_file: str, metadata: dict[str, Any]) -> None:
    files = load_source_files(profile_id)
    files[source_file] = metadata
    save_json(source_files_path(profile_id), files)


def save_merchant_rules(profile_id: str, rules: list[dict[str, Any]]) -> None:
    save_json(merchant_rules_path(profile_id), rules)


def append_merchant_rule(profile_id: str, rule: dict[str, Any]) -> None:
    inferred = next((infer_anchor_direction(anchor) for anchor in rule_anchors(rule) if infer_anchor_direction(anchor)), None)
    if inferred:
        rule["direction"] = inferred
    if is_rule_direction_invalid(rule):
        return
    rules = load_json(merchant_rules_path(profile_id), [])
    rules.insert(0, rule)
    save_merchant_rules(profile_id, rules)


def merchant_rule_dedupe_key(rule: dict[str, Any]) -> tuple[Any, ...]:
    anchors = tuple(sorted(normalize_rule_anchor(item) for item in rule_anchors(rule) if item))
    return (rule.get("direction") or "", anchors, rule.get("scenario") or rule.get("operation_type") or "")


def upsert_merchant_rule(profile_id: str, rule: dict[str, Any]) -> None:
    inferred = next((infer_anchor_direction(anchor) for anchor in rule_anchors(rule) if infer_anchor_direction(anchor)), None)
    if inferred:
        rule["direction"] = inferred
    if is_rule_direction_invalid(rule):
        return
    rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
    rules = load_json(merchant_rules_path(profile_id), [])
    new_key = merchant_rule_dedupe_key(rule)
    rules = [
        existing
        for existing in rules
        if not (existing.get("enabled", True) and merchant_rule_dedupe_key(existing) == new_key)
    ]
    rules.insert(0, rule)
    save_merchant_rules(profile_id, rules)


def save_plan_rules(profile_id: str, rules: list[dict[str, Any]]) -> None:
    save_json(plan_rules_path(profile_id), rules)


def clean_duplicate_plan_rules(profile_id: str, rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source_rules = list(load_json(plan_rules_path(profile_id), []) if rules is None else rules)
    seen = set()
    cleaned = []
    for rule in source_rules:
        key = plan_rule_dedupe_key(rule, include_scenario=False)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(rule)
    if rules is None:
        save_plan_rules(profile_id, cleaned)
    return cleaned


def upsert_plan_rule(profile_id: str, rule: dict[str, Any]) -> None:
    inferred = next((infer_anchor_direction(anchor) for anchor in rule_anchors(rule) if infer_anchor_direction(anchor)), None)
    if inferred:
        rule["direction"] = inferred
    if is_rule_direction_invalid(rule):
        return
    rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
    rules = load_json(plan_rules_path(profile_id), [])
    new_key = plan_rule_dedupe_key(rule, include_scenario=False)
    rules = [
        existing
        for existing in rules
        if not (
            existing.get("enabled", True)
            and plan_rule_dedupe_key(existing, include_scenario=False) == new_key
        )
    ]
    rules.insert(0, rule)
    save_plan_rules(profile_id, rules)


def append_plan_rule(profile_id: str, rule: dict[str, Any]) -> None:
    upsert_plan_rule(profile_id, rule)


def upsert_profile_rule(profile_id: str, rule: dict[str, Any]) -> None:
    if rule.get("match_contains_any") or str(rule.get("id", "")).startswith("plan_") or rule.get("scenario"):
        upsert_plan_rule(profile_id, rule)
    else:
        upsert_merchant_rule(profile_id, rule)


def clean_duplicate_rules(profile_id: str) -> dict[str, int]:
    merchant_rules = load_json(merchant_rules_path(profile_id), [])
    plan_rules = load_json(plan_rules_path(profile_id), [])

    merchant_seen = set()
    clean_merchants = []
    for rule in merchant_rules:
        key = merchant_rule_dedupe_key(rule)
        if key in merchant_seen:
            continue
        merchant_seen.add(key)
        clean_merchants.append(rule)

    clean_plans = clean_duplicate_plan_rules(profile_id, plan_rules)
    if len(clean_merchants) != len(merchant_rules):
        save_merchant_rules(profile_id, clean_merchants)
    if len(clean_plans) != len(plan_rules):
        save_plan_rules(profile_id, clean_plans)
    return {
        "merchant_removed": len(merchant_rules) - len(clean_merchants),
        "plan_removed": len(plan_rules) - len(clean_plans),
    }


def clean_invalid_rules(profile_id: str) -> dict[str, int]:
    merchant_rules = load_json(merchant_rules_path(profile_id), [])
    valid_merchant_rules = [rule for rule in merchant_rules if not is_rule_direction_invalid(rule)]
    if len(valid_merchant_rules) != len(merchant_rules):
        save_merchant_rules(profile_id, valid_merchant_rules)

    plan_rules = load_json(plan_rules_path(profile_id), [])
    valid_plan_rules = []
    seen_plan_keys = set()
    for rule in plan_rules:
        if is_rule_direction_invalid(rule):
            continue
        key = plan_rule_dedupe_key(rule, include_scenario=False)
        if key in seen_plan_keys:
            continue
        seen_plan_keys.add(key)
        valid_plan_rules.append(rule)
    if len(valid_plan_rules) != len(plan_rules):
        save_plan_rules(profile_id, valid_plan_rules)

    return {
        "merchant_removed": len(merchant_rules) - len(valid_merchant_rules),
        "plan_removed": len(plan_rules) - len(valid_plan_rules),
    }


def insert_operations(operations: list[dict[str, Any]]) -> int:
    return insert_operations_with_stats(operations)["inserted"]


def build_duplicate_key(operation: dict[str, Any]) -> str:
    normalized = normalize_description(operation.get("normalized_description") or operation.get("description", ""))
    optional_parts = [
        operation.get("auth_code"),
        operation.get("operation_code"),
        operation.get("card_last4"),
        operation.get("document_number"),
    ]
    parts = [
        operation.get("profile_id", ""),
        operation.get("bank", ""),
        operation.get("account_id", ""),
        operation.get("operation_datetime", ""),
        operation.get("bank_amount", ""),
        normalized,
        *[part for part in optional_parts if part],
    ]
    return "|".join(str(part) for part in parts)


def create_import_batch(
    profile_id: str,
    source_file_name: str,
    metadata: dict[str, Any],
    operations_found: int = 0,
    status: str = "started",
    warning: str = "",
) -> str:
    init_db()
    batch_id = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO import_batches (
                id, profile_id, source_file_name, bank, document_type, account_id, account_type,
                account_role, owner_name, period_start, period_end, imported_at, operations_found,
                operations_inserted, duplicates_skipped, status, warning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                batch_id,
                profile_id,
                source_file_name,
                metadata.get("bank", ""),
                metadata.get("document_type") or metadata.get("detected_document_type", ""),
                metadata.get("account_id", ""),
                metadata.get("account_type", ""),
                metadata.get("account_role", ""),
                metadata.get("owner_name", ""),
                metadata.get("period_start", ""),
                metadata.get("period_end", ""),
                now,
                int(operations_found or 0),
                0,
                0,
                status,
                warning,
            ],
        )
    return batch_id


def update_import_batch(batch_id: str, updates: dict[str, Any]) -> None:
    if not updates:
        return
    allowed = {
        "bank",
        "document_type",
        "account_id",
        "account_type",
        "account_role",
        "owner_name",
        "period_start",
        "period_end",
        "operations_found",
        "operations_inserted",
        "duplicates_skipped",
        "status",
        "warning",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    assignments = ", ".join(f"{key} = ?" for key in clean)
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE import_batches SET {assignments} WHERE id = ?", [*clean.values(), batch_id])


def import_batches_df(profile_id: str) -> pd.DataFrame:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT *
            FROM import_batches
            WHERE profile_id = ?
            ORDER BY datetime(imported_at) DESC
            """,
            conn,
            params=[profile_id],
        )


def get_account_import_status(profile_id: str, bank: str, account_id: str = "") -> dict[str, Any]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        op_row = conn.execute(
            """
            SELECT min(operation_datetime), max(operation_datetime), count(*), count(DISTINCT source_file)
            FROM operations
            WHERE profile_id = ? AND bank = ? AND coalesce(account_id, '') = coalesce(?, '')
            """,
            [profile_id, bank, account_id or ""],
        ).fetchone()
        batch_row = conn.execute(
            """
            SELECT period_start, period_end
            FROM import_batches
            WHERE profile_id = ? AND bank = ? AND coalesce(account_id, '') = coalesce(?, '')
            ORDER BY datetime(imported_at) DESC
            LIMIT 1
            """,
            [profile_id, bank, account_id or ""],
        ).fetchone()
    return {
        "first_operation_datetime": op_row[0] if op_row else None,
        "last_operation_datetime": op_row[1] if op_row else None,
        "operations_count": int(op_row[2] or 0) if op_row else 0,
        "source_files_count": int(op_row[3] or 0) if op_row else 0,
        "last_import_period_start": batch_row[0] if batch_row else None,
        "last_import_period_end": batch_row[1] if batch_row else None,
    }


def insert_operations_with_stats(operations: list[dict[str, Any]], import_batch_id: str | None = None) -> dict[str, int]:
    init_db()
    stats = {"attempted": len(operations), "inserted": 0, "filtered": 0, "duplicates": 0}
    fields = [
        "id",
        "profile_id",
        "bank",
        "source_file",
        "source_file_name",
        "import_batch_id",
        "document_type",
        "account_id",
        "account_type",
        "account_role",
        "owner_name",
        "operation_datetime",
        "processing_date",
        "description",
        "raw_description",
        "raw_category",
        "bank_amount",
        "direction",
        "cashflow_amount",
        "operation_type",
        "budget_category",
        "personal_amount",
        "budget_amount",
        "planning_amount",
        "count_in_budget",
        "count_in_plan",
        "count_in_cashflow",
        "plan_category",
        "plan_exclusion_reason",
        "debt_amount",
        "debt_type",
        "confidence",
        "classification_source",
        "needs_review",
        "rule_id",
        "linked_operation_id",
        "duplicate_key",
        "comment",
        "normalized_description",
        "merchant_anchor",
        "person_anchor",
        "phone_anchor",
        "card_last4",
        "auth_code",
        "expense_nature",
        "created_at",
    ]
    with sqlite3.connect(DB_PATH) as conn:
        for operation in operations:
            if is_service_description(operation.get("description", "")):
                stats["filtered"] += 1
                continue
            if is_suspicious_operation(operation):
                stats["filtered"] += 1
                continue
            operation.setdefault("id", uuid.uuid4().hex)
            operation.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
            operation.setdefault("raw_description", operation.get("description", ""))
            operation.setdefault("source_file_name", operation.get("source_file", ""))
            if import_batch_id:
                operation["import_batch_id"] = import_batch_id
            else:
                operation.setdefault("import_batch_id", "")
            operation.setdefault("account_type", "unknown")
            operation.setdefault("account_role", operation.get("account_type", "unknown"))
            operation.setdefault("document_type", "")
            operation.setdefault("account_id", "")
            operation.setdefault("owner_name", "")
            operation.setdefault("confidence", 0.0)
            operation.setdefault("classification_source", "")
            operation.setdefault("merchant_anchor", "")
            operation.setdefault("person_anchor", "")
            operation.setdefault("phone_anchor", "")
            operation.setdefault("card_last4", "")
            operation.setdefault("auth_code", "")
            operation.setdefault("expense_nature", "")
            operation.setdefault("cashflow_amount", operation.get("bank_amount", 0.0))
            operation.setdefault("count_in_cashflow", True)
            operation.setdefault("budget_amount", operation.get("personal_amount", 0.0))
            operation.setdefault("planning_amount", 0.0)
            operation.setdefault("count_in_budget", False)
            operation.setdefault("count_in_plan", False)
            operation.setdefault("plan_category", operation.get("budget_category", ""))
            operation.setdefault("plan_exclusion_reason", "")
            operation.setdefault("debt_amount", 0.0)
            operation.setdefault("debt_type", "")
            operation.setdefault("linked_operation_id", "")
            operation["normalized_description"] = normalize_description(operation.get("description", ""))
            operation["duplicate_key"] = operation.get("duplicate_key") or build_duplicate_key(operation)
            values = [operation.get(field) for field in fields]
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO operations ({','.join(fields)}) VALUES ({','.join(['?'] * len(fields))})",
                values,
            )
            if cursor.rowcount:
                stats["inserted"] += 1
            else:
                stats["duplicates"] += 1
    return stats


def operations_df(profile_id: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    init_db()
    query = "SELECT * FROM operations WHERE profile_id = ?"
    params: list[Any] = [profile_id]
    if start_date:
        start_date = start_date.isoformat() if hasattr(start_date, "isoformat") else str(start_date)
        query += " AND date(operation_datetime) >= date(?)"
        params.append(start_date)
    if end_date:
        end_date = end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date)
        query += " AND date(operation_datetime) <= date(?)"
        params.append(end_date)
    query += " ORDER BY datetime(operation_datetime) DESC, created_at DESC"
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["needs_review"] = df["needs_review"].astype(bool)
        df = df[~df["description"].fillna("").apply(is_service_description)]
        suspicious = df.apply(
            lambda row: is_suspicious_operation(
                {
                    "description": row.get("description", ""),
                    "raw_category": row.get("raw_category", ""),
                    "bank_amount": row.get("bank_amount", 0),
                }
            ),
            axis=1,
        )
        df = df[~suspicious]
    return df


def available_months(profile_id: str) -> list[str]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT strftime('%Y-%m', operation_datetime) AS month
            FROM operations
            WHERE profile_id = ? AND operation_datetime IS NOT NULL
            ORDER BY month DESC
            """,
            [profile_id],
        ).fetchall()
    return [row[0] for row in rows if row[0]]


def latest_month_with_operations(profile_id: str) -> str | None:
    months = available_months(profile_id)
    return months[0] if months else None


def latest_operation_date(profile_id: str) -> str | None:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT max(date(operation_datetime)) FROM operations WHERE profile_id = ?",
            [profile_id],
        ).fetchone()
    return row[0] if row else None


def delete_profile_operations(profile_id: str) -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM operations WHERE profile_id = ?", [profile_id])
        return cursor.rowcount


def delete_profile_source_file_operations(profile_id: str, source_file: str) -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "DELETE FROM operations WHERE profile_id = ? AND source_file = ?",
            [profile_id, source_file],
        )
        return cursor.rowcount


def update_operation(operation_id: str, updates: dict[str, Any]) -> None:
    if not updates:
        return
    allowed = {
        "operation_type",
        "budget_category",
        "personal_amount",
        "budget_amount",
        "planning_amount",
        "count_in_budget",
        "count_in_plan",
        "count_in_cashflow",
        "plan_category",
        "plan_exclusion_reason",
        "debt_amount",
        "debt_type",
        "confidence",
        "classification_source",
        "needs_review",
        "rule_id",
        "linked_operation_id",
        "duplicate_key",
        "comment",
        "expense_nature",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    assignments = ", ".join(f"{key} = ?" for key in clean)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE operations SET {assignments} WHERE id = ?",
            [*clean.values(), operation_id],
        )


def append_profile_rule(profile_id: str, rule: dict[str, Any]) -> None:
    profile = load_profile(profile_id)
    profile.setdefault("rules", [])
    profile["rules"].insert(0, rule)
    save_profile(profile)
