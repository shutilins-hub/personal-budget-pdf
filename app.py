from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

import storage
from bank_adapters import detect_document_type, link_internal_transfers, parse_by_document_type
from budget_engine import dashboard_metrics, financial_health_assessment, income_plan_fact, plan_fact
from classifier import build_rule_from_operation, classify_operations, rule_matches
from financial_health import build_financial_health_report
from pdf_parser import detect_bank, extract_text_from_uploaded_pdf, parse_text
from privacy import sanitize_text
from planner import build_auto_expense_plan, build_auto_income_plan, build_auto_plan
from planner import (
    build_raw_auto_plan_from_operations,
    build_raw_income_plan_from_operations,
    build_layered_plan_from_operations,
    default_plan_behavior_for_candidate,
    default_rule_scope_for_candidate,
    get_income_review_candidates_from_operations,
    get_plan_review_candidates_from_operations,
    infer_anchor_direction,
    plan_coverage_score,
    prepare_planning_dataframe,
    previous_full_months,
    recommended_plan_totals,
)
from report_builder import (
    raw_category_summary,
    recurring_operations_summary,
    recurring_people_summary,
    unrecognized_summary,
    write_plan_debug,
    write_layered_plan_debug,
    write_import_debug,
)
from reclassification import reclassify_profile_operations
from ui.components import (
    apply_app_style,
    category_status,
    category_status_meta,
    money,
    pct,
    render_attention_card,
    render_category_summary_row,
    render_metric_card,
    render_metric_grid,
    render_progress_row,
    render_section_card,
)
from storage import (
    append_profile_rule,
    append_merchant_rule,
    append_plan_rule,
    available_months,
    clean_duplicate_plan_rules,
    clean_duplicate_rules,
    clean_invalid_rules,
    create_profile,
    category_labels,
    delete_profile_operations,
    default_categories,
    default_operation_types,
    default_profile_template,
    get_or_create_default_profile,
    init_db,
    insert_operations_with_stats,
    list_profiles,
    load_profile,
    load_custom_categories,
    save_source_file_metadata,
    latest_month_with_operations,
    latest_operation_date,
    operations_df,
    save_profile,
    save_custom_categories,
    save_merchant_rules,
    save_plan_rules,
    update_operation,
    upsert_profile_rule,
)


MONTH_NAMES = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


st.set_page_config(page_title="Личный бюджет по PDF", layout="wide")


def make_widget_key(prefix: str, *parts) -> str:
    raw = "_".join(str(part) for part in parts if part is not None)
    safe = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", raw)
    return f"{prefix}_{safe[:120]}"


FALLBACK_EXPENSE_PLAN_CATEGORIES = [
    "Жильё",
    "Продукты / супермаркеты",
    "Кафе / доставка / рестораны",
    "Транспорт",
    "Такси",
    "Авто / каршеринг",
    "Связь / интернет / подписки",
    "Здоровье / аптеки",
    "Психолог / терапия",
    "Красота / уход",
    "Маркетплейсы",
    "Дом / ремонт / бытовое",
    "Дом / одежда / бытовое",
    "Одежда",
    "Обучение",
    "Развлечения",
    "Подарки / семья",
    "Путешествия",
    "Документы / визы",
    "Крупная медицина / стоматология",
    "Кредиты / проценты / комиссии",
    "Наличные / проверить",
    "Переводы, которые нужно уточнить",
    "Прочее / проверить",
]

FALLBACK_INCOME_CATEGORIES = [
    "Зарплата / аванс / премия",
    "Доп. доход / проекты",
    "Продажа сайтов",
    "Возврат налога / кешбэк",
    "Социальные выплаты",
    "Прочий личный доход",
    "Проверить доход",
]


def expense_categories(profile: dict | None = None) -> list[str]:
    labels = category_labels("expense", (profile or {}).get("id")) if profile else category_labels("expense")
    return labels or FALLBACK_EXPENSE_PLAN_CATEGORIES


def income_categories(profile: dict | None = None) -> list[str]:
    labels = category_labels("income", (profile or {}).get("id")) if profile else category_labels("income")
    return labels or FALLBACK_INCOME_CATEGORIES


def manual_plan_editor_df(profile: dict) -> pd.DataFrame:
    current_plan = profile.get("plan") or {}
    income_set = set(income_categories(profile))
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for category in expense_categories(profile):
        if category in seen:
            continue
        rows.append({"Категория": category, "Лимит": float(current_plan.get(category, 0) or 0)})
        seen.add(category)
    for category, amount in current_plan.items():
        if category in seen or category in income_set:
            continue
        rows.append({"Категория": category, "Лимит": float(amount or 0)})
        seen.add(category)
    return pd.DataFrame(rows)


def render_manual_plan_editor(profile: dict) -> None:
    st.subheader("Ручной план по категориям")
    st.caption("Можно вручную задать лимиты. Сумма категорий станет планом месяца и будет использоваться в контроле бюджета.")
    editor_key = make_widget_key("manual_category_plan_editor", profile.get("id"))
    edited = st.data_editor(
        manual_plan_editor_df(profile),
        hide_index=True,
        use_container_width=True,
        disabled=["Категория"],
        key=editor_key,
        column_config={
            "Категория": st.column_config.TextColumn("Категория"),
            "Лимит": st.column_config.NumberColumn("Лимит, ₽", min_value=0.0, step=500.0, format="%.0f"),
        },
    )
    if edited is None or edited.empty:
        st.info("Нет расходных категорий для плана.")
        return
    edited["Лимит"] = pd.to_numeric(edited["Лимит"], errors="coerce").fillna(0).clip(lower=0)
    total = float(edited["Лимит"].sum())
    render_metric_grid([{"label": "Сумма ручного плана", "value": money(total), "hint": "Это будет общий лимит месяца после сохранения."}])
    if st.button("Сохранить ручной план", key=make_widget_key("save_manual_category_plan", profile.get("id")), type="primary"):
        manual_plan = {
            str(row["Категория"]): float(row["Лимит"])
            for _, row in edited.iterrows()
            if str(row.get("Категория") or "").strip()
        }
        profile["plan"] = manual_plan
        profile["monthly_limit"] = float(sum(manual_plan.values()))
        profile["plan_source"] = "manual_category_plan"
        profile["plan_updated_at"] = datetime.now().isoformat(timespec="seconds")
        profile["auto_plan_accepted"] = True
        save_profile(profile)
        write_plan_debug(profile, profile.get("plan_history_months_used", []))
        st.success("Ручной план сохранён. Контроль месяца пересчитан по новым лимитам.")
        st.rerun()


EXPENSE_PLAN_CATEGORIES = FALLBACK_EXPENSE_PLAN_CATEGORIES
INCOME_CATEGORIES = FALLBACK_INCOME_CATEGORIES

ACCOUNT_TYPE_LABELS = {
    "debit_account": "Дебетовый счёт / карта",
    "credit_card": "Кредитная карта",
    "installment_card": "Карта рассрочки",
    "loan_account": "Кредит / заём",
    "savings_account": "Накопительный / вклад",
    "wallet": "Кошелёк",
    "marketplace_wallet": "Кошелёк / маркетплейс",
    "unknown": "Не знаю",
}

CREDIT_REPAYMENT_MARKERS = (
    "погашение кредит",
    "погашение задолж",
    "платеж по кредит",
    "платёж по кредит",
    "credit",
    "кредитн",
    "рассроч",
)


def navigate_to(tab_id: str) -> None:
    st.session_state["active_tab"] = tab_id
    st.session_state["pending_navigation"] = None


def navigate_to_review() -> None:
    navigate_to("Очистка")
    st.session_state["review_filter"] = "needs_review"
    st.session_state["focus_review"] = True


def set_active_tab_from_nav() -> None:
    selected = st.session_state.get("nav_selected_tab")
    if selected:
        navigate_to(selected)


def month_label(month_key: str) -> str:
    year, month = [int(part) for part in month_key.split("-")]
    return f"{MONTH_NAMES[month]} {year}"


def month_range(month_key: str) -> tuple[date, date]:
    year, month = [int(part) for part in month_key.split("-")]
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def month_picker(profile_id: str) -> tuple[str | None, date, date]:
    months = available_months(profile_id)
    default_month = latest_month_with_operations(profile_id)
    today_key = date.today().strftime("%Y-%m")
    if not months:
        start, end = month_range(today_key)
        return None, start, end
    labels = {month_label(month): month for month in months}
    default_label = month_label(default_month or months[0])
    selected_label = st.sidebar.selectbox("Месяц отчёта", list(labels.keys()), index=list(labels.keys()).index(default_label))
    selected_month = labels[selected_label]
    start, end = month_range(selected_month)
    return selected_month, start, end


def month_progress(start_date: date, end_date: date) -> tuple[int, int]:
    today = date.today()
    days_in_month = (end_date - start_date).days + 1
    if today < start_date:
        return 0, days_in_month
    if today > end_date:
        return days_in_month, days_in_month
    return (today - start_date).days + 1, days_in_month


def render_user_journey(history: pd.DataFrame, operations: pd.DataFrame, profile: dict, active_step: str) -> None:
    months_count = 0
    if not history.empty and "operation_datetime" in history.columns:
        months_count = history["operation_datetime"].astype(str).str[:7].nunique()
    review_count = int(operations["needs_review"].sum()) if not operations.empty and "needs_review" in operations.columns else 0
    has_plan = bool(profile.get("auto_plan_accepted") or profile.get("plan_source"))
    steps = [
        ("Профиль и загрузка", months_count >= 3),
        ("Очистка операций", review_count == 0 and not operations.empty),
        ("План месяца", has_plan),
        ("Контроль бюджета", has_plan and review_count == 0),
    ]
    step_tabs = {
        "Профиль и загрузка": "Профиль и загрузка",
        "Очистка операций": "Очистка",
        "План месяца": "План",
        "Контроль бюджета": "Контроль",
    }
    active_index = next((idx for idx, (title, _) in enumerate(steps) if title == active_step), 0)
    html = ['<div class="step-strip">']
    for idx, (title, done) in enumerate(steps):
        css = "step-done" if done or idx < active_index else ""
        label = "готово" if done or idx < active_index else "далее"
        if title == active_step:
            css = "step-active"
            label = "активен"
        html.append(f'<div class="step {css}"><b>{title}</b><div>{label}</div></div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    nav_cols = st.columns(4)
    for idx, (title, _) in enumerate(steps):
        if title == active_step:
            nav_cols[idx].button("Вы здесь", key=make_widget_key("journey_nav_current", active_step, title), use_container_width=True, disabled=True)
        else:
            nav_cols[idx].button(
                "Открыть",
                key=make_widget_key("journey_nav", active_step, title),
                use_container_width=True,
                on_click=navigate_to,
                args=(step_tabs[title],),
            )
    if months_count < 3:
        st.info("Шаг 1: заполните профиль и загрузите больше выписок. Для автоплана лучше иметь минимум 3–6 месяцев истории.")
    elif review_count >= 10:
        st.info("Шаг 2: разберите регулярные переводы и крупные операции.")
    elif not has_plan:
        st.info("Шаг 3: рассчитайте и примите план месяца.")
    else:
        st.success("Шаг 4: добавляйте новые выписки и следите за фактом.")


def profile_selector() -> dict:
    profiles = list_profiles()
    if not profiles:
        profiles = [get_or_create_default_profile()]
    names = {f"{profile['name']} ({profile['id']})": profile["id"] for profile in profiles}
    selected = st.sidebar.selectbox("Профиль", list(names.keys()))
    return load_profile(names[selected])


def compact_new_profile_form() -> None:
    if st.sidebar.button("+ Новый профиль", use_container_width=True):
        st.session_state["show_new_profile_form"] = not st.session_state.get("show_new_profile_form", False)
    if not st.session_state.get("show_new_profile_form", False):
        return
    with st.sidebar.form("new_profile_compact"):
        name = st.text_input("Название профиля")
        full_name = st.text_input("Ф.И.О.")
        phones = st.text_input("Телефоны через запятую")
        banks = st.text_input("Банки и кошельки")
        initial_limit = st.number_input("Начальный лимит, опционально", min_value=0.0, value=0.0, step=1000.0)
        if st.form_submit_button("Создать профиль"):
            profile = create_profile(name.strip() or "Новый профиль", initial_limit)
            profile["own_identity"] = {
                "full_name": full_name.strip(),
                "name_aliases": [full_name.strip()] if full_name.strip() else [],
                "phones": [item.strip() for item in phones.split(",") if item.strip()],
                "account_last4": [],
                "banks": [item.strip() for item in banks.split(",") if item.strip()],
            }
            save_profile(profile)
            st.session_state["show_new_profile_form"] = False
            st.rerun()


def render_sidebar(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, start_date: date, end_date: date) -> None:
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    st.sidebar.caption(
        f"В месяце: {len(operations)} операций · На проверку: {int(metrics['review_count'])} · "
        f"Осталось: {money(metrics['limit_left'])}"
    )
    if st.sidebar.button("Настройки профиля", use_container_width=True):
        st.session_state["open_profile_settings_hint"] = True
    if st.session_state.get("open_profile_settings_hint"):
        st.sidebar.info("Настройки профиля теперь находятся во вкладке “Профиль”.")
    with st.sidebar.expander("Опасная зона"):
        st.caption("Удаляет только операции текущего профиля. Профиль, план и правила останутся.")
        if st.button("Очистить тестовые данные", use_container_width=True, key=make_widget_key("danger_clear", profile["id"])):
            deleted = delete_profile_operations(profile["id"])
            st.sidebar.success(f"Удалено операций: {deleted}")
            st.rerun()


def create_profile_form() -> None:
    with st.sidebar.expander("Создать профиль"):
        name = st.text_input("Название профиля")
        default_limit = float(default_profile_template().get("monthly_limit", 0))
        limit = st.number_input(
            "Лимит на месяц",
            min_value=0.0,
            value=default_limit,
            step=1000.0,
            key="new_profile_limit",
        )
        if st.button("Создать", use_container_width=True):
            create_profile(name, limit)
            st.rerun()


def account_metadata_form(uploaded_files: list, profile_id: str | None = None) -> dict[str, dict]:
    metadata_by_file = {}
    if not uploaded_files:
        return metadata_by_file
    st.markdown("**Что это за счёт?**")
    for uploaded_file in uploaded_files:
        source_file = sanitize_text(getattr(uploaded_file, "name", "uploaded.pdf"))
        with st.expander(source_file, expanded=True):
            try:
                preview_text = extract_text_from_uploaded_pdf(uploaded_file)
                detection = detect_document_type(preview_text)
                preview_bank = detection.get("bank") or detect_bank(preview_text)
            except Exception:
                detection = {}
                preview_bank = "Неизвестный банк"
            st.caption(
                f"Банк: {preview_bank} · Тип документа: {detection.get('document_type', 'не определён')} · "
                f"Статус: {'будет пропущен' if detection.get('document_type') == 'irrelevant_document' else 'готов к импорту'}"
            )
            detected_account_type = detection.get("account_type", "unknown")
            default_index = list(ACCOUNT_TYPE_LABELS.keys()).index(detected_account_type) if detected_account_type in ACCOUNT_TYPE_LABELS else 0
            account_type = st.selectbox(
                "Тип счёта",
                list(ACCOUNT_TYPE_LABELS.keys()),
                format_func=lambda value: ACCOUNT_TYPE_LABELS[value],
                index=default_index,
                key=make_widget_key("account_type", source_file),
            )
            account_name = st.text_input("Название счёта", value=source_file, key=make_widget_key("account_name", source_file))
            metadata = {
                "source_file": source_file,
                "detected_document_type": detection.get("document_type", "unknown_document"),
                "document_type": detection.get("document_type", "unknown_document"),
                "account_role": detection.get("account_role", account_type),
                "detection_confidence": detection.get("confidence", 0.0),
                "detection_reason": detection.get("reason", ""),
                "account_type": account_type,
                "account_name": account_name,
                "account_limit": 0.0,
                "debt_start": 0.0,
                "debt_end": 0.0,
                "minimum_payment": 0.0,
                "payment_due_date": "",
                "grace_period_end": "",
            }
            account_status = storage.get_account_import_status(profile_id or "", preview_bank or "", metadata.get("account_id", ""))
            if account_status.get("operations_count"):
                first_dt = str(account_status.get("first_operation_datetime") or "")[:10]
                last_dt = str(account_status.get("last_operation_datetime") or "")[:10]
                st.info(
                    f"По этому счёту уже есть история: {first_dt} — {last_dt}. "
                    "Новые операции добавятся к истории, дубли будут пропущены."
                )
            if account_type == "credit_card":
                col1, col2 = st.columns(2)
                metadata["account_limit"] = col1.number_input("Кредитный лимит", min_value=0.0, step=1000.0, key=make_widget_key("account_limit", source_file))
                metadata["debt_end"] = col2.number_input("Текущий долг", min_value=0.0, step=1000.0, key=make_widget_key("debt_end", source_file))
                col3, col4 = st.columns(2)
                metadata["minimum_payment"] = col3.number_input("Минимальный платёж", min_value=0.0, step=500.0, key=make_widget_key("minimum_payment", source_file))
                due_date = col4.date_input("Дата платежа", value=date.today(), key=make_widget_key("payment_due_date", source_file))
                metadata["payment_due_date"] = due_date.isoformat()
            metadata_by_file[source_file] = metadata
    return metadata_by_file


def is_credit_repayment_description(description: str) -> bool:
    normalized = " ".join(str(description or "").casefold().split())
    return any(marker in normalized for marker in CREDIT_REPAYMENT_MARKERS)


def apply_account_context(operations: list[dict], metadata: dict) -> list[dict]:
    account_type = metadata.get("account_type", "unknown")
    for operation in operations:
        operation["account_type"] = account_type
        operation["account_role"] = account_type
        direction = operation.get("direction")
        description = operation.get("description", "")
        if account_type in {"credit_card", "installment_card"} and direction == "income":
            operation.update(
                operation_type="Погашение кредита",
                budget_category="Не учитывать",
                personal_amount=0.0,
                budget_amount=0.0,
                planning_amount=0.0,
                count_in_budget=False,
                count_in_plan=False,
                plan_category="Не учитывать",
                needs_review=False,
                confidence=0.9,
                classification_source="account_type_repayment",
            )
        elif account_type in {"savings_account"}:
            operation.update(
                operation_type="Внутренний перевод",
                budget_category="Не учитывать",
                personal_amount=0.0,
                budget_amount=0.0,
                planning_amount=0.0,
                count_in_budget=False,
                count_in_plan=False,
                plan_category="Не учитывать",
                needs_review=False,
                confidence=0.9,
                classification_source="account_type_savings",
            )
        elif account_type == "wallet" and direction == "income":
            operation.update(
                operation_type="Внутренний перевод",
                budget_category="Не учитывать",
                personal_amount=0.0,
                budget_amount=0.0,
                planning_amount=0.0,
                count_in_budget=False,
                count_in_plan=False,
                plan_category="Не учитывать",
                needs_review=False,
                confidence=0.9,
                classification_source="account_type_wallet_topup",
            )
        elif account_type == "debit_account" and direction == "expense" and is_credit_repayment_description(description):
            operation.update(
                operation_type="Погашение кредита",
                budget_category="Не учитывать",
                personal_amount=0.0,
                budget_amount=0.0,
                planning_amount=0.0,
                count_in_budget=False,
                count_in_plan=False,
                plan_category="Не учитывать",
                needs_review=False,
                confidence=0.8,
                classification_source="account_type_repayment_transfer",
            )
    return operations


def import_pdfs(profile: dict, uploaded_files: list, start_date: date, end_date: date, metadata_by_file: dict[str, dict] | None = None) -> dict:
    all_text_parts = []
    all_parsed = []
    file_summaries = []
    total_inserted = 0
    total_duplicates = 0
    total_filtered = 0
    skipped_irrelevant = 0
    document_detections = []
    account_metadata_debug = []
    metadata_by_file = metadata_by_file or {}
    for uploaded_file in uploaded_files:
        source_file = sanitize_text(getattr(uploaded_file, "name", "uploaded.pdf"))
        metadata = metadata_by_file.get(source_file, {"source_file": source_file, "account_type": "unknown", "account_name": source_file})
        text = extract_text_from_uploaded_pdf(uploaded_file)
        detection = detect_document_type(text)
        document_detections.append({"source_file": source_file, **detection})
        if detection.get("document_type") == "irrelevant_document":
            batch_id = storage.create_import_batch(
                profile["id"],
                source_file,
                {
                    **metadata,
                    "bank": detection.get("bank", ""),
                    "document_type": detection.get("document_type"),
                    "account_type": detection.get("account_type", "unknown"),
                },
                operations_found=0,
                status="skipped_irrelevant",
                warning="PDF не похож на банковскую выписку",
            )
            skipped_irrelevant += 1
            file_summaries.append(
                {
                    "import_batch_id": batch_id,
                    "source_file": source_file,
                    "bank": detection.get("bank", ""),
                    "document_type": detection.get("document_type"),
                    "account_type": detection.get("account_type", "unknown"),
                    "account_name": metadata.get("account_name", ""),
                    "text_chars": len(text),
                    "parsed_operations": 0,
                    "saved_operations": 0,
                    "duplicates_skipped": 0,
                    "filtered_operations": 0,
                    "skipped_irrelevant": True,
                    "first_30_lines": [sanitize_text(line) for line in text.splitlines()[:30]],
                }
            )
            all_text_parts.append(f"===== {source_file} | skipped_irrelevant =====\n{text}")
            continue
        bank = detection.get("bank") if detection.get("confidence", 0) >= 0.5 else detect_bank(text)
        metadata.update(
            {
                "bank": bank,
                "detected_document_type": detection.get("document_type", "unknown_document"),
                "document_type": detection.get("document_type", "unknown_document"),
                "account_type": metadata.get("account_type") or detection.get("account_type", "unknown"),
                "account_role": metadata.get("account_role") or detection.get("account_role", metadata.get("account_type", "unknown")),
                "detection_confidence": detection.get("confidence", 0.0),
                "detection_reason": detection.get("reason", ""),
                "profile_id": profile["id"],
                "imported_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        adapter_metadata = dict(metadata)
        adapter_metadata["source_file"] = source_file
        parsed = parse_by_document_type(text, adapter_metadata)
        if not parsed:
            parsed = parse_text(text, profile["id"], source_file, bank)
            for operation in parsed:
                operation["document_type"] = metadata.get("document_type", "unknown_document")
        classified = classify_operations(parsed, profile)
        classified = apply_account_context(classified, metadata)
        classified = prepare_planning_dataframe(pd.DataFrame(classified), profile).to_dict("records") if classified else []
        batch_id = storage.create_import_batch(profile["id"], source_file, metadata, operations_found=len(parsed), status="parsed")
        for operation in classified:
            operation["import_batch_id"] = batch_id
            operation["source_file_name"] = source_file
        stats = insert_operations_with_stats(classified, import_batch_id=batch_id)
        storage.update_import_batch(
            batch_id,
            {
                "operations_found": len(parsed),
                "operations_inserted": stats["inserted"],
                "duplicates_skipped": stats["duplicates"],
                "status": "imported",
                "warning": "Период уже был загружен, новых операций может не быть" if stats["inserted"] == 0 and stats["duplicates"] else "",
            },
        )
        save_source_file_metadata(profile["id"], source_file, metadata)
        account_metadata_debug.append(metadata)
        total_inserted += stats["inserted"]
        total_duplicates += stats["duplicates"]
        total_filtered += stats["filtered"]
        all_text_parts.append(f"===== {source_file} | {bank} =====\n{text}")
        all_parsed.extend(classified)
        file_summaries.append(
            {
                "source_file": source_file,
                "import_batch_id": batch_id,
                "bank": bank,
                "document_type": metadata.get("document_type", "unknown_document"),
                "account_role": metadata.get("account_role", metadata.get("account_type", "unknown")),
                "account_type": metadata.get("account_type", "unknown"),
                "account_name": metadata.get("account_name", ""),
                "text_chars": len(text),
                "parsed_operations": len(parsed),
                "saved_operations": stats["inserted"],
                "duplicates_skipped": stats["duplicates"],
                "filtered_operations": stats["filtered"],
                "first_30_lines": [sanitize_text(line) for line in text.splitlines()[:30]],
            }
        )
    if total_inserted:
        reclassify_profile_operations(profile["id"], preserve_manual_overrides=True)
    period_operations = operations_df(profile["id"], start_date, end_date)
    linked_pairs = link_internal_transfers(profile["id"])
    review_count = int(period_operations["needs_review"].sum()) if not period_operations.empty else 0
    parsed_df = pd.DataFrame(all_parsed)
    summary = {
        "files_uploaded": len(uploaded_files),
        "files": file_summaries,
        "parsed_operations": len(all_parsed),
        "saved_operations": total_inserted,
        "duplicates_skipped": total_duplicates,
        "filtered_operations": total_filtered,
        "skipped_irrelevant": skipped_irrelevant,
        "internal_transfer_links": len(linked_pairs),
        "document_detection": document_detections,
        "account_metadata": account_metadata_debug,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "operations_in_period": len(period_operations),
        "needs_review": review_count,
        "raw_category_summary": raw_category_summary(parsed_df).to_dict("records"),
    }
    write_import_debug("\n\n".join(all_text_parts), all_parsed, summary)
    return summary


def show_import_diagnostics(summary: dict) -> None:
    st.success(f"Импортировано операций: {summary['saved_operations']}. На проверку: {summary['needs_review']}.")
    cols = st.columns(4)
    cols[0].metric("Файлов загружено", summary["files_uploaded"])
    cols[1].metric("Найдено парсером", summary["parsed_operations"])
    cols[2].metric("Сохранено в базу", summary["saved_operations"])
    cols[3].metric("В периоде", summary["operations_in_period"])
    with st.expander("Диагностика импорта"):
        st.write(f"Дублей пропущено: {summary['duplicates_skipped']}")
        st.write(f"Отфильтровано защитой: {summary['filtered_operations']}")
        for file_summary in summary["files"]:
            st.markdown(f"**{file_summary['source_file']}**")
            st.write(f"Банк определён: {file_summary['bank']}")
            st.write(f"Тип счёта: {ACCOUNT_TYPE_LABELS.get(file_summary.get('account_type'), file_summary.get('account_type'))}")
            st.write(f"Символов текста извлечено: {file_summary['text_chars']}")
            st.write(f"Операций найдено парсером: {file_summary['parsed_operations']}")
            st.write(f"Операций сохранено в базу: {file_summary['saved_operations']}")
            if file_summary["parsed_operations"] == 0:
                st.text("\n".join(file_summary["first_30_lines"]))
        if summary.get("raw_category_summary"):
            st.markdown("**Сводка распознанных raw_category**")
            st.dataframe(pd.DataFrame(summary["raw_category_summary"]), use_container_width=True, hide_index=True)


def render_import_history(profile_id: str) -> None:
    batches = storage.import_batches_df(profile_id)
    if batches.empty:
        st.caption("Истории загрузок пока нет.")
        return
    display = batches.copy()
    display["период"] = display["period_start"].fillna("").astype(str) + " — " + display["period_end"].fillna("").astype(str)
    display = display.rename(
        columns={
            "imported_at": "дата загрузки",
            "bank": "банк",
            "source_file_name": "файл",
            "account_type": "тип счёта",
            "operations_found": "найдено",
            "operations_inserted": "добавлено",
            "duplicates_skipped": "дублей",
            "status": "статус",
        }
    )
    columns = ["дата загрузки", "банк", "файл", "тип счёта", "период", "найдено", "добавлено", "дублей", "статус"]
    st.dataframe(display[[column for column in columns if column in display.columns]].head(20), use_container_width=True, hide_index=True)
    with st.expander("Детали истории загрузок"):
        st.dataframe(batches, use_container_width=True, hide_index=True)


def upload_pdf(profile: dict, start_date: date, end_date: date) -> None:
    st.subheader("Загрузка выписок")
    st.write("Загрузите PDF-выписки минимум за 6 месяцев из всех банков, которыми пользуетесь.")
    uploaded_files = st.file_uploader(
        "Добавьте выписки или справки о движении средств",
        type=["pdf"],
        accept_multiple_files=True,
    )
    uploaded_names = [getattr(file, "name", "uploaded.pdf") for file in uploaded_files or []]
    if st.session_state.get("uploaded_names") != uploaded_names:
        st.session_state["uploaded_names"] = uploaded_names
        st.session_state.pop("last_import_summary", None)
    metadata_by_file = account_metadata_form(uploaded_files or [], profile["id"])
    import_clicked = st.button("Импортировать и перейти к очистке", disabled=not uploaded_files, type="primary")
    recalc_clicked = st.button("Пересчитать отчёт без загрузки PDF")
    if import_clicked:
        st.session_state["last_import_summary"] = import_pdfs(profile, uploaded_files, start_date, end_date, metadata_by_file)
        st.session_state["calculated"] = True
        st.session_state["active_page_after_import"] = "Очистка"
        st.rerun()
    if recalc_clicked:
        st.session_state["calculated"] = True
        st.info("Отчёт пересчитан по операциям в базе.")
        st.rerun()
    if st.session_state.get("last_import_summary"):
        show_import_diagnostics(st.session_state["last_import_summary"])
        st.success("Следующий шаг: перейдите в раздел “Очистка” и разберите регулярные переводы.")
    elif uploaded_files:
        st.info("PDF загружен, но ещё не обработан.")
    st.subheader("История загрузок")
    render_import_history(profile["id"])
    st.session_state["has_uploaded_files"] = bool(uploaded_files)


def period_picker(profile_id: str) -> tuple[str | None, date, date]:
    auto_month = st.sidebar.checkbox("Автоматически выбрать месяц по выписке", value=True)
    if auto_month:
        month_key, start, end = month_picker(profile_id)
        return month_key, start, end
    today = date.today()
    start = st.sidebar.date_input("Период с", value=today.replace(day=1))
    end = st.sidebar.date_input("Период по", value=today)
    if start > end:
        st.sidebar.warning("Дата начала позже даты конца. Поменяйте период.")
    return start.strftime("%Y-%m"), start, end


def dashboard(profile: dict, operations: pd.DataFrame) -> None:
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    cols = st.columns(4)
    cols[0].metric("Личные доходы", money(metrics["personal_income"]))
    cols[1].metric("Расходы до компенсаций", money(metrics["gross_expense"]))
    cols[2].metric("Компенсации", money(metrics["compensation"]))
    cols[3].metric("Чистые расходы", money(metrics["net_expense"]))
    cols2 = st.columns(4)
    cols2[0].metric("Итог доход − чистые расходы", money(metrics["balance"]))
    cols2[1].metric("Лимит месяца", money(metrics["limit"]))
    cols2[2].metric("Осталось по лимиту", money(metrics["limit_left"]))
    cols2[3].metric("Операций на проверку", int(metrics["review_count"]))
    if metrics["limit"]:
        st.progress(max(0.0, min(1.0, metrics["net_expense"] / metrics["limit"])), text=f"Осталось по лимиту: {money(metrics['limit_left'])}")
    if metrics["review_count"]:
        st.warning("Часть операций не распознана. Проверьте их вручную.")


def month_status_text(profile: dict, operations: pd.DataFrame, start_date: date, end_date: date) -> tuple[str, str]:
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    days_elapsed, days_in_month = month_progress(start_date, end_date)
    progress = days_elapsed / days_in_month if days_in_month else 0
    used = metrics["net_expense"] / metrics["limit"] if metrics["limit"] else 0
    if metrics["review_count"]:
        return "Расчёт неполный", f"Есть {int(metrics['review_count'])} операций на проверку."
    if profile.get("plan_source") == "raw_auto_plan":
        return "План пока черновой", "В плане могут быть неразобранные переводы, категории нужно уточнить."
    if metrics["limit"] and used > progress + 0.15:
        return "Внимание", f"Расходы идут быстрее плана: использовано {pct(used)}, прошло {pct(progress)} месяца."
    if metrics["limit"]:
        return "Всё нормально", f"Использовано {pct(used)} плана, прошло {pct(progress)} месяца."
    return "Нужен план", "Рассчитайте план месяца, чтобы видеть остаток и прогресс."


def get_operations_for_category(profile_id: str, month: str | None, category: str) -> pd.DataFrame:
    if not month:
        return pd.DataFrame()
    start_date, end_date = month_range(month)
    month_operations = operations_df(profile_id, start_date, end_date)
    if month_operations.empty:
        return month_operations
    operation_type = month_operations.get("operation_type", pd.Series("", index=month_operations.index)).fillna("")
    count_in_budget = month_operations.get("count_in_budget", pd.Series(False, index=month_operations.index)).fillna(False).astype(bool)
    budget_category = month_operations.get("budget_category", pd.Series("", index=month_operations.index)).fillna("")
    plan_category = month_operations.get("plan_category", pd.Series("", index=month_operations.index)).fillna("")
    review_category = category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}
    category_mask = budget_category.eq(category) | plan_category.eq(category)
    budget_mask = count_in_budget | (review_category & month_operations.get("needs_review", pd.Series(False, index=month_operations.index)).fillna(False).astype(bool))
    exclude_types = {"Внутренний перевод", "Проектный оборот", "Проектный расход", "Проектный приход", "Не учитывать", "Погашение кредита"}
    df = month_operations[category_mask & budget_mask & ~operation_type.isin(exclude_types)].copy()
    if "duplicate_key" in df.columns:
        df = df.drop_duplicates(subset=["duplicate_key"], keep="first")
    return df


def category_operations_display(category_operations: pd.DataFrame) -> pd.DataFrame:
    if category_operations.empty:
        return pd.DataFrame(columns=["Дата", "Описание", "Сумма", "Банк", "Статус"])
    df = category_operations.copy()
    df["operation_datetime"] = pd.to_datetime(df["operation_datetime"], errors="coerce")
    amount_column = "budget_amount" if "budget_amount" in df.columns else "personal_amount"
    amounts = df[amount_column].fillna(0)
    if (amounts == 0).all():
        amounts = df["bank_amount"].abs()
    return pd.DataFrame(
        {
            "Дата": df["operation_datetime"].dt.strftime("%d.%m").fillna(""),
            "Описание": df["description"].fillna(""),
            "Сумма": amounts.map(money),
            "Банк": df["bank"].fillna(""),
            "Статус": df["operation_type"].fillna("Проверить"),
        }
    )


def update_category_operation(
    row: pd.Series,
    operation_type: str,
    category: str,
    create_rule: bool,
    profile: dict,
) -> None:
    amount = abs(float(row.get("budget_amount") or row.get("personal_amount") or row.get("bank_amount") or 0))
    personal_amount = amount if operation_type in {"Личный расход", "Расход из фонда"} else 0.0
    if operation_type == "Компенсация совместных расходов":
        personal_amount = -amount
    planning_updates = manual_planning_updates(operation_type, category, personal_amount)
    update_operation(
        row["id"],
        {
            "operation_type": operation_type,
            "budget_category": category,
            "personal_amount": personal_amount,
            **planning_updates,
            "confidence": 0.95,
            "classification_source": "manual_category_row",
            "needs_review": False,
        },
    )
    if create_rule:
        append_profile_rule(profile["id"], build_rule_from_operation(row.to_dict(), operation_type, category, personal_amount))
        reclassify_profile_operations(profile["id"], preserve_manual_overrides=True)
    st.rerun()


def ignore_category_operation(row: pd.Series) -> None:
    update_operation(
        row["id"],
        {
            "operation_type": "Не учитывать",
            "budget_category": "Не учитывать",
            "personal_amount": 0.0,
            "budget_amount": 0.0,
            "planning_amount": 0.0,
            "count_in_budget": False,
            "count_in_plan": False,
            "plan_category": "Не учитывать",
            "confidence": 0.95,
            "classification_source": "manual_category_ignore",
            "needs_review": False,
        },
    )
    st.rerun()


def render_category_operation_actions(row: pd.Series, profile: dict, category: str, key_prefix: str) -> None:
    action_options = ["Действие", "Изменить категорию", "Проектный оборот", "Перевод самому себе", "Создать правило для похожих", "Не учитывать эту операцию", "Перейти к проверке"]
    if category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}:
        action_options = ["Разобрать", *action_options[1:]]
    action = st.selectbox(
        "Действие",
        action_options,
        key=make_widget_key(key_prefix, "action", row["id"]),
        label_visibility="collapsed",
    )
    if action in {"Разобрать", "Изменить категорию"}:
        selected_category = st.selectbox(
            "Новая категория",
            expense_categories(profile),
            key=make_widget_key(key_prefix, "new_category", row["id"]),
        )
        create_rule = st.checkbox(
            "Создать правило для похожих",
            key=make_widget_key(key_prefix, "create_rule", row["id"]),
        )
        if st.button("Сохранить", key=make_widget_key(key_prefix, "save_category", row["id"])):
            update_category_operation(row, "Личный расход", selected_category, create_rule, profile)
    elif action == "Проектный оборот":
        create_rule = st.checkbox(
            "Применить к похожим операциям",
            key=make_widget_key(key_prefix, "project_rule", row["id"]),
            help="Например, все операции TILDA будут исключаться из личного бюджета как проектный оборот.",
        )
        st.caption("Операция не будет считаться личным расходом и не попадёт в план месяца.")
        if st.button("Сохранить как проектный оборот", key=make_widget_key(key_prefix, "save_project", row["id"])):
            update_category_operation(row, "Проектный оборот", "Не учитывать", create_rule, profile)
    elif action == "Перевод самому себе":
        create_rule = st.checkbox(
            "Применить к похожим операциям",
            key=make_widget_key(key_prefix, "internal_rule", row["id"]),
        )
        st.caption("Операция не будет считаться расходом, доходом или частью плана.")
        if st.button("Сохранить как перевод самому себе", key=make_widget_key(key_prefix, "save_internal", row["id"])):
            update_category_operation(row, "Внутренний перевод", "Не учитывать", create_rule, profile)
    elif action == "Создать правило для похожих":
        operation_type = st.selectbox(
            "Что делать с похожими операциями?",
            ["Личный расход", "Проектный оборот", "Внутренний перевод", "Не учитывать"],
            key=make_widget_key(key_prefix, "rule_operation_type", row["id"]),
        )
        if operation_type == "Личный расход":
            category_options = expense_categories(profile)
        else:
            category_options = ["Не учитывать"]
        selected_category = st.selectbox(
            "Категория для похожих операций",
            category_options,
            key=make_widget_key(key_prefix, "rule_category", row["id"]),
        )
        if st.button("Создать правило", key=make_widget_key(key_prefix, "save_rule", row["id"])):
            amount = abs(float(row.get("budget_amount") or row.get("personal_amount") or row.get("bank_amount") or 0))
            personal_amount = amount if operation_type == "Личный расход" else 0.0
            append_profile_rule(profile["id"], build_rule_from_operation(row.to_dict(), operation_type, selected_category, personal_amount))
            reclassify_profile_operations(profile["id"], preserve_manual_overrides=True)
            st.success("Правило создано. Похожие операции пересчитаны.")
            st.rerun()
    elif action == "Не учитывать эту операцию":
        if st.button("Не учитывать", key=make_widget_key(key_prefix, "ignore", row["id"])):
            ignore_category_operation(row)
    elif action == "Перейти к проверке":
        st.caption("Эта операция останется в списке проверки. Откройте раздел “Очистка”, чтобы разобрать её подробно.")


def render_category_progress_card(category: str, fact: float, plan: float, is_open: bool = False) -> None:
    meta = category_status_meta(fact, plan)
    is_review = category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}
    card_css = "category-review" if is_review else str(meta.get("card_css") or "")
    status_label = "разобрать" if is_review and meta["label"] != "перерасход" else meta["label"]
    width = min(100, max(0, float(meta["usage"]) * 100))
    arrow = "▼" if is_open else "›"
    st.markdown(
        f'<div class="category-card {card_css}">'
        f'<div class="category-head"><div class="category-title">{arrow} {category}</div>'
        f'<div class="category-amount">{money(fact)} / {money(plan)}</div></div>'
        f'<div class="bar"><div style="width:{width:.1f}%"></div></div>'
        f'<div class="category-foot"><span>{meta["bottom"]}</span><span class="category-status">{status_label}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_category_operations(category: str, category_operations: pd.DataFrame, fact: float, plan: float, profile: dict, key_prefix: str) -> None:
    if category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}:
        st.info("Эти операции попали сюда, потому что сервис не уверен в категории.")
    if category_operations.empty:
        st.caption("Операций в этой категории за выбранный месяц не найдено.")
        return
    amount_column = "budget_amount" if "budget_amount" in category_operations.columns else "personal_amount"
    amounts = category_operations[amount_column].fillna(0)
    if (amounts == 0).all():
        amounts = category_operations["bank_amount"].abs()
    total = float(amounts.sum())
    count = len(category_operations)
    average = total / count if count else 0
    largest = float(amounts.abs().max()) if count else 0
    st.caption(f"Операций: {count} · Сумма: {money(total)} · Средний чек: {money(average)} · Крупнейшая операция: {money(largest)}")
    sort_df = category_operations.copy()
    sort_df["_amount"] = amounts.abs()
    sort_df["_dt"] = pd.to_datetime(sort_df["operation_datetime"], errors="coerce")
    sort_df = sort_df.sort_values(["_dt", "_amount"], ascending=[False, False])
    focus_id = st.session_state.get("focus_operation_id")
    if focus_id and "id" in sort_df.columns:
        sort_df["_focus"] = sort_df["id"].astype(str).eq(str(focus_id)).astype(int)
        sort_df = sort_df.sort_values(["_focus", "_dt", "_amount"], ascending=[False, False, False])
    if fact > plan and plan:
        top = sort_df.head(3)
        st.markdown("**Крупнейшие операции, которые повлияли на перерасход:**")
        for _, row in top.iterrows():
            st.write(f"{money(float(row['_amount']))} · {row.get('description', '')}")
    visible = sort_df.head(15)
    st.dataframe(category_operations_display(visible), use_container_width=True, hide_index=True)
    if len(sort_df) > 15:
        with st.expander(f"Показать ещё {len(sort_df) - 15} операций"):
            st.dataframe(category_operations_display(sort_df.iloc[15:]), use_container_width=True, hide_index=True)
    st.markdown("**Действия по операциям**")
    for idx, (_, row) in enumerate(visible.iterrows()):
        with st.container():
            col1, col2 = st.columns([3, 2])
            dt = pd.to_datetime(row.get("operation_datetime"), errors="coerce")
            date_text = dt.strftime("%d.%m") if pd.notna(dt) else ""
            col1.write(f"{date_text} · {row.get('description', '')}")
            col1.caption(f"{money(float(row.get('_amount') or 0))} · {row.get('bank', '')} · {row.get('operation_type', 'Расход')}")
            with col2:
                render_category_operation_actions(row, profile, category, make_widget_key(key_prefix, idx))


def render_category_expense_row(category: str, fact: float, plan: float, operations: pd.DataFrame, profile: dict, month: str | None, key_scope: str = "category") -> None:
    safe_category = make_widget_key("category_card", key_scope, profile["id"], month, category)
    is_open = st.session_state.get("opened_category") == category
    render_category_progress_card(category, fact, plan, is_open)
    col1, col2 = st.columns([1, 5])
    button_label = "Скрыть" if is_open else ("Разобрать" if category in {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"} else "Открыть")
    if col1.button(button_label, key=make_widget_key("category_expand", key_scope, profile["id"], month, category)):
        st.session_state["opened_category"] = None if is_open else category
        st.rerun()
    if is_open:
        category_operations = get_operations_for_category(profile["id"], month, category)
        render_category_operations(category, category_operations, fact, plan, profile, safe_category)


def render_category_progress(operations: pd.DataFrame, plan: pd.DataFrame, profile: dict | None = None, month: str | None = None, limit: int = 12, key_scope: str = "category") -> None:
    pf = plan_fact(operations, plan)
    if pf.empty:
        st.info("План-факт по категориям появится после импорта и расчёта плана.")
        return
    pf = pf[(pf["plan"] != 0) | (pf["fact"] != 0)].copy()
    if pf.empty:
        st.info("Пока нет расходов по категориям.")
        return
    review_categories = {"Прочее / проверить", "Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"}
    pf["_rank"] = pf.apply(
        lambda row: 3 if row["budget_category"] in review_categories and row["fact"] > 0 else int(category_status_meta(float(row["fact"]), float(row["plan"]))["rank"]),
        axis=1,
    )
    pf = pf.sort_values(["_rank", "fact"], ascending=[True, False]).head(limit)
    st.subheader("Расходы по категориям")
    if st.session_state.get("opened_category"):
        st.caption(f"Открыта категория: {st.session_state['opened_category']}")
    if profile and month:
        for _, row in pf.iterrows():
            render_category_expense_row(row["budget_category"], float(row["fact"]), float(row["plan"]), operations, profile, month, key_scope)
    else:
        body = "".join(render_progress_row(row["budget_category"], float(row["fact"]), float(row["plan"])) for _, row in pf.iterrows())
        render_section_card("Расходы по категориям", body)


def calculation_status(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, report_month: str | None) -> tuple[str, str, str]:
    review_count = int(operations["needs_review"].sum()) if not operations.empty and "needs_review" in operations.columns else 0
    if review_count:
        return "Есть операции на проверку", f"Нужно уточнить {review_count} операций.", "warn"
    if report_month and not history.empty:
        candidates = get_plan_review_candidates_from_operations(history, report_month, 6, profile)
        important = candidates[candidates["importance_level"] == "important"] if not candidates.empty else pd.DataFrame()
        if not important.empty:
            return "Есть неразобранные переводы", f"В плане мешают {len(important)} важных групп операций.", "warn"
    if not (profile.get("auto_plan_accepted") or profile.get("plan_source")):
        return "План неполный", "Примите план месяца, чтобы контроль был точнее.", "warn"
    return "Полный", "Ключевые операции и план готовы для контроля.", "good"


def render_budget_overview_primary(metrics: dict[str, float], start_date: date, end_date: date) -> None:
    limit = float(metrics.get("limit") or 0)
    spent = float(metrics.get("net_expense") or 0)
    left = float(metrics.get("limit_left") or 0)
    usage = spent / limit if limit else 0.0
    width = min(100, max(0, usage * 100)) if limit else 0
    left_status = "danger" if left < 0 else "warn" if limit and usage >= 0.8 else "good"
    today = date.today()
    days_left = max(0, (end_date - today).days) if today <= end_date else 0
    cards = [
        ("План месяца", money(limit), "Принятый лимит расходов", "is-plan", ""),
        ("Потрачено", money(spent), "Чистые расходы с учётом компенсаций", "is-spent", ""),
        ("Осталось", money(left), "До конца выбранного месяца", "is-left", f" status-{left_status}"),
    ]
    html = ['<div class="primary-grid">']
    for label, value, hint, kind, status_class in cards:
        html.append(
            f'<div class="primary-card {kind}{status_class}">'
            f'<div class="primary-label">{label}</div>'
            f'<div class="primary-value">{value}</div>'
            f'<div class="primary-hint">{hint}</div>'
            f'</div>'
        )
    html.append("</div>")
    if limit:
        html.append(
            f'<div class="overview-progress"><div class="bar"><div style="width:{width:.1f}%"></div></div>'
            f'<div class="overview-caption">Потрачено {usage:.0%} плана · До конца месяца {days_left} дн.</div></div>'
        )
    else:
        html.append('<div class="overview-caption">План месяца ещё не задан.</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def render_budget_health_status(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, report_month: str | None) -> tuple[str, str, str]:
    return calculation_status(profile, operations, history, report_month)


def open_review_from_status(profile: dict, operations: pd.DataFrame, report_month: str | None) -> None:
    navigate_to_review()
    if not operations.empty and "needs_review" in operations.columns:
        review = operations[operations["needs_review"] == True].copy()
        if not review.empty:
            review["_abs"] = review["bank_amount"].abs()
            row = review.sort_values("_abs", ascending=False).iloc[0]
            set_focus_operation(row.get("id"))
            set_focus_category(str(row.get("budget_category") or row.get("plan_category") or "Прочее / проверить"))


def render_budget_overview_secondary(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, report_month: str | None, metrics: dict[str, float]) -> None:
    balance = float(metrics.get("balance") or 0)
    income = float(metrics.get("personal_income") or 0)
    if balance < 0:
        balance_status = "danger"
        balance_hint = "Расходы выше личных доходов."
    elif income and balance / income < 0.1:
        balance_status = "warn"
        balance_hint = "Запас небольшой."
    else:
        balance_status = "good"
        balance_hint = "Есть запас после расходов."
    status_title, status_hint, status = render_budget_health_status(profile, operations, history, report_month)
    display_status_title = "Расчёт полный" if status_title == "Полный" else status_title
    cols = st.columns(3)
    cols[0].markdown(
        f'<div class="metric-card"><div class="metric-label">Личные доходы</div>'
        f'<div class="metric-value">{money(income)}</div><div class="metric-hint">Компенсации сюда не входят.</div></div>',
        unsafe_allow_html=True,
    )
    cols[1].markdown(
        f'<div class="metric-card status-{balance_status}"><div class="metric-label">Баланс месяца</div>'
        f'<div class="metric-value">{money(balance)}</div><div class="metric-hint">{balance_hint}</div></div>',
        unsafe_allow_html=True,
    )
    with cols[2].container(border=True):
        st.caption("Статус расчёта")
        st.markdown(f"### {display_status_title}")
        st.caption(status_hint)
        if status_title != "Полный":
            st.button(
                "Разобрать операции",
                key=make_widget_key("status_action", profile["id"], report_month),
                use_container_width=True,
                on_click=open_review_from_status,
                args=(profile, operations, report_month),
            )


def handle_health_recommendation_action(recommendation: dict) -> None:
    target = recommendation.get("action_target")
    if target == "cleanup":
        navigate_to_review()
    elif target == "plan":
        navigate_to("План")
    elif target == "income":
        st.session_state["active_section"] = "income"
        navigate_to("Контроль")
    elif target == "category":
        if recommendation.get("category"):
            set_focus_category(str(recommendation["category"]))
        navigate_to("Контроль")
    elif target == "rules":
        navigate_to("Правила")


def render_recommendation_card(recommendation: dict, index: int) -> None:
    severity = recommendation.get("severity", "info")
    st.markdown(
        f'<div class="attention-action-card status-{severity}">'
        f'<div class="attention-action-title">{recommendation.get("title", "")}</div>'
        f'<div class="attention-action-text">{recommendation.get("text", "")}</div></div>',
        unsafe_allow_html=True,
    )
    st.button(
        recommendation.get("action_label", "Открыть"),
        key=make_widget_key("health_recommendation", index, recommendation.get("title"), recommendation.get("action_target")),
        on_click=handle_health_recommendation_action,
        args=(recommendation,),
    )


def render_financial_health_block(profile: dict, operations: pd.DataFrame, plan: pd.DataFrame, report_month: str | None) -> None:
    if not report_month:
        return
    report = build_financial_health_report(profile["id"], report_month, operations, plan, profile_income_plan_df(profile))
    metrics = report["key_metrics"]
    safe = report["safe_to_spend"]
    ratio = report["income_expense_ratio"]
    severity = report.get("severity", "good")
    st.subheader("Оценка месяца")
    render_metric_grid(
        [
            {"label": "Статус месяца", "value": report["month_status"], "hint": report["summary_text"], "status": "warn" if severity in {"warning", "incomplete"} else "danger" if severity == "danger" else "good"},
            {"label": "Можно тратить до конца", "value": money(safe["total_left"]), "hint": f"Примерно {money(safe['per_day'])} в день" if metrics["days_left"] else "Месяц уже закончился", "status": "danger" if safe["status"] == "overspent" else "warn" if safe["status"] in {"tight", "danger"} else "good"},
            {"label": "Доходы и расходы", "value": money(metrics["balance"]), "hint": ratio["text"], "status": "danger" if ratio["status"] == "danger" else "warn" if ratio["status"] == "warning" else "good"},
            {"label": "Качество данных", "value": f"{report['data_quality']['confidence_score']:.0f}/100", "hint": report["data_quality"]["status"], "status": "danger" if report["data_quality"]["confidence_score"] < 60 else "warn" if report["data_quality"]["confidence_score"] < 85 else "good"},
        ]
    )
    st.caption(
        f"Прошло {metrics['month_progress_percent']:.0%} месяца, "
        f"использовано {metrics['plan_used_percent']:.0%} плана. "
        f"До конца месяца {metrics['days_left']} дн."
        if metrics["plan_used_percent"] is not None
        else "План месяца не задан, поэтому темп расходов оценивается ограниченно."
    )
    recommendations = report.get("recommendations", [])
    if recommendations:
        st.subheader("Что сделать дальше")
        for index, recommendation in enumerate(recommendations[:5]):
            render_recommendation_card(recommendation, index)


def attention_items(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, report_month: str | None, plan: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    if not operations.empty:
        review = operations[operations["needs_review"] == True].copy()
        if not review.empty:
            review["_abs"] = review["bank_amount"].abs()
            for _, row in review.sort_values("_abs", ascending=False).head(5).iterrows():
                items.append(
                    {
                        "type": "operation",
                        "title": "Операция на проверку",
                        "text": f"{money(float(row['bank_amount']))} · {row.get('description', '')}",
                        "status": "warn",
                        "button": "Разобрать",
                        "operation_id": row.get("id"),
                        "category": row.get("budget_category") or row.get("plan_category") or "Прочее / проверить",
                    }
                )
    pf = plan_fact(operations, plan)
    if not pf.empty:
        over = pf[(pf["plan"] > 0) & (pf["fact"] > pf["plan"])].sort_values("diff").head(3)
        for _, row in over.iterrows():
            category = row["budget_category"]
            items.append(
                {
                    "type": "category",
                    "title": "Перерасход категории",
                    "text": f"{category}: перерасход {money(abs(float(row['diff'])))}",
                    "status": "danger",
                    "button": "Открыть категорию",
                    "category": category,
                }
            )
    if report_month and not history.empty:
        candidates = get_plan_review_candidates_from_operations(history, report_month, 6, profile)
        important = candidates[candidates["importance_level"] == "important"] if not candidates.empty else pd.DataFrame()
        for _, row in important.head(3).iterrows():
            items.append(
                {
                    "type": "rule",
                    "title": "Регулярный перевод не разобран",
                    "text": f"{row['anchor']} · {money(float(row['total_sum']))} за историю",
                    "status": "warn",
                    "button": "Создать правило",
                    "anchor": row["anchor"],
                }
            )
    today = date.today()
    for metadata in (profile.get("source_files", {}) or {}).values():
        due = metadata.get("payment_due_date")
        if due:
            try:
                due_date = date.fromisoformat(due)
            except ValueError:
                continue
            if 0 <= (due_date - today).days <= 7:
                items.append(
                    {
                        "type": "payment",
                        "title": "Скоро платёж",
                        "text": f"{metadata.get('account_name') or metadata.get('source_file')}: до {due}",
                        "status": "warn",
                        "button": "Посмотреть обязательства",
                    }
                )
    return items[:10]


def render_attention_card_action(item: dict, index: int) -> None:
    status = item.get("status") or "warn"
    st.markdown(
        f'<div class="attention-action-card status-{status}">'
        f'<div class="attention-action-title">{item.get("title", "Что проверить")}</div>'
        f'<div class="attention-action-text">{item.get("text", "")}</div></div>',
        unsafe_allow_html=True,
    )
    button_label = item.get("button") or "Открыть"
    key = make_widget_key("attention_action", index, item.get("type"), item.get("operation_id"), item.get("category"), item.get("anchor"))
    st.button(button_label, key=key, on_click=handle_attention_action, args=(item,))


def handle_attention_action(item: dict) -> None:
    if item.get("type") == "category" and item.get("category"):
        set_focus_category(str(item["category"]))
        navigate_to("Контроль")
    elif item.get("type") == "operation" and item.get("operation_id") is not None:
        set_focus_operation(item["operation_id"])
        if item.get("category"):
            set_focus_category(str(item["category"]))
        navigate_to_review()
    elif item.get("type") == "rule":
        navigate_to("Очистка")
        st.session_state["active_section"] = "cleanup"
        st.session_state["focus_anchor"] = item.get("anchor")
    else:
        st.session_state["active_section"] = "attention"


def render_clickable_attention_cards(items: list[dict]) -> None:
    if not items:
        render_attention_card("Пока спокойно", "Нет крупных вопросов на главной. Можно перейти к контролю бюджета.", "good")
        return
    for index, item in enumerate(items):
        render_attention_card_action(item, index)


def render_home_page(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, plan: pd.DataFrame, report_month: str | None, start_date: date, end_date: date, latest_date: str | None) -> None:
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    st.markdown(
        f"""
        <div class="budget-hero">
            <h1>Бюджет месяца</h1>
            <div class="budget-sub">Профиль: <b>{profile.get('name')}</b> · Месяц: <b>{month_label(report_month) if report_month else 'не выбран'}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_user_journey(history, operations, profile, "Контроль бюджета")
    render_budget_overview_primary(metrics, start_date, end_date)
    render_budget_overview_secondary(profile, operations, history, report_month, metrics)
    st.markdown(
        f'<div class="utility-line">Компенсации: <b>{money(float(metrics["compensation"]))}</b> · '
        f'Операций на проверку: <b>{int(metrics["review_count"])}</b> · '
        f'Операций в месяце: <b>{len(operations)}</b> · '
        f'Последняя операция: <b>{latest_date or "нет данных"}</b></div>',
        unsafe_allow_html=True,
    )
    render_financial_health_block(profile, operations, plan, report_month)
    render_category_progress(operations, plan, profile, report_month, key_scope="home")
    credit_obligations(profile, metrics)
    st.subheader("Что требует внимания")
    items = attention_items(profile, operations, history, report_month, plan)
    render_clickable_attention_cards(items)


def credit_obligations(profile: dict, metrics: dict[str, float]) -> None:
    source_files = profile.get("source_files", {}) or {}
    credit_files = [
        metadata for metadata in source_files.values()
        if metadata.get("account_type") in {"credit_card", "installment_card", "loan_account"}
    ]
    if not credit_files:
        return
    st.subheader("Кредиты и обязательные платежи")
    rows = []
    today = date.today()
    for metadata in credit_files:
        limit = float(metadata.get("account_limit") or 0)
        used = float(metadata.get("debt_end") or metadata.get("debt_start") or 0)
        free = max(0.0, limit - used) if limit else 0.0
        minimum_payment = float(metadata.get("minimum_payment") or 0)
        due_date_text = metadata.get("payment_due_date") or ""
        usage_ratio = used / limit if limit else 0.0
        rows.append(
            {
                "счёт": metadata.get("account_name") or metadata.get("source_file"),
                "тип": ACCOUNT_TYPE_LABELS.get(metadata.get("account_type"), metadata.get("account_type")),
                "кредитный лимит": limit,
                "использовано": used,
                "свободно": free,
                "минимальный платёж": minimum_payment,
                "дата платежа": due_date_text,
                "использовано лимита": f"{usage_ratio:.0%}" if limit else "",
            }
        )
        if limit and usage_ratio > 0.7:
            st.warning("Кредитный лимит сильно использован.")
        if due_date_text:
            try:
                due_date = date.fromisoformat(due_date_text)
                if 0 <= (due_date - today).days <= 7:
                    st.warning("Скоро обязательный платёж.")
            except ValueError:
                pass
        income = float(metrics.get("personal_income") or 0)
        if income and minimum_payment > income * 0.2:
            st.warning("Платёж заметно нагружает бюджет.")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_health(profile: dict, operations: pd.DataFrame, start_date: date, end_date: date) -> None:
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    days_elapsed, days_in_month = month_progress(start_date, end_date)
    health = financial_health_assessment(metrics, days_elapsed, days_in_month, int(metrics["review_count"]))
    st.info(f"{health['status']}: {health['message']}")
    if metrics["limit"]:
        st.caption(
            f"Прошло {health['month_progress_ratio']:.0%} месяца, использовано {health['budget_used_ratio']:.0%} лимита."
        )


def render_main_charts(profile: dict, operations: pd.DataFrame, plan: pd.DataFrame) -> None:
    expense_pf = plan_fact(operations, plan)
    chart_source = expense_pf[expense_pf["fact"] != 0][["budget_category", "plan", "fact"]]
    if not chart_source.empty:
        st.subheader("План-факт по расходам")
        st.bar_chart(chart_source.set_index("budget_category")[["plan", "fact"]])
        st.subheader("Структура чистых расходов")
        st.bar_chart(chart_source.set_index("budget_category")["fact"])
    metrics = dashboard_metrics(operations, profile.get("monthly_limit", 0))
    st.subheader("Доходы vs чистые расходы")
    st.bar_chart(
        pd.DataFrame(
            {
                "показатель": ["Личные доходы", "Чистые расходы", "Итог"],
                "сумма": [metrics["personal_income"], metrics["net_expense"], metrics["balance"]],
            }
        ).set_index("показатель")
    )


def render_income_section(profile: dict, operations: pd.DataFrame) -> None:
    st.subheader("Доходы месяца")
    income_df = income_plan_fact(operations, profile_income_plan_df(profile))
    if income_df.empty:
        st.info("Доходов за выбранный месяц пока нет.")
    else:
        display = income_df.rename(
            columns={
                "income_category": "Источник дохода",
                "plan": "План",
                "fact": "Факт",
                "diff": "Разница",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)
    if not operations.empty:
        non_income = operations[
            operations["direction"].isin(["income", "incoming"])
            & operations["operation_type"].isin(["Компенсация совместных расходов", "Внутренний перевод", "Возврат займа", "Проектный оборот", "Проектный приход", "Не учитывать"])
        ]
        if not non_income.empty:
            with st.expander("Поступления, которые не считаются личным доходом"):
                summary = non_income.groupby("operation_type", as_index=False)["bank_amount"].sum().rename(
                    columns={"operation_type": "Что это", "bank_amount": "Сумма"}
                )
                st.dataframe(summary, use_container_width=True, hide_index=True)


def operation_choice_label(row: pd.Series) -> str:
    dt = pd.to_datetime(row.get("operation_datetime"), errors="coerce")
    date_text = dt.strftime("%d.%m") if pd.notna(dt) else ""
    amount = float(row.get("bank_amount") or 0)
    description = str(row.get("description") or "")[:90]
    operation_type = str(row.get("operation_type") or "Проверить")
    return f"{date_text} · {money(amount)} · {description} · сейчас: {operation_type}"


def reassignment_options_for_row(row: pd.Series) -> tuple[str, list[str], str]:
    direction = str(row.get("direction") or "")
    if direction in {"income", "incoming"}:
        return (
            "Что это за поступление?",
            [
                "Личный доход",
                "Компенсация расходов",
                "Мне вернули долг",
                "Я занял деньги",
                "Перевод между своими счетами",
                "Проектный оборот",
                "Не учитывать",
            ],
            "Личный доход",
        )
    return (
        "Что это за списание?",
        [
            "Обычный расход",
            "Проектный оборот",
            "Перевод между своими счетами",
            "Я дал в долг",
            "Я вернул долг",
            "Не учитывать",
        ],
        "Обычный расход",
    )


def operation_update_from_reassignment(row: pd.Series, scenario: str, category: str) -> tuple[str, str, float, dict]:
    amount = abs(float(row.get("bank_amount") or row.get("budget_amount") or row.get("personal_amount") or 0))
    if scenario == "Личный доход":
        operation_type = "Личный доход"
        final_category = category
        personal_amount = amount
    elif scenario == "Компенсация расходов":
        operation_type = "Компенсация совместных расходов"
        final_category = category
        personal_amount = -amount
    elif scenario == "Обычный расход":
        operation_type = "Личный расход"
        final_category = category
        personal_amount = amount
    elif scenario == "Проектный оборот":
        operation_type = "Проектный оборот"
        final_category = "Не учитывать"
        personal_amount = 0.0
    elif scenario == "Перевод между своими счетами":
        operation_type = "Внутренний перевод"
        final_category = "Не учитывать"
        personal_amount = 0.0
    elif scenario == "Мне вернули долг":
        operation_type = "Возврат займа"
        final_category = "Не учитывать"
        personal_amount = 0.0
    elif scenario == "Я занял деньги":
        operation_type = "Заём получен"
        final_category = "Не учитывать"
        personal_amount = 0.0
    elif scenario == "Я дал в долг":
        operation_type = "Заём выдан"
        final_category = "Не учитывать"
        personal_amount = 0.0
    elif scenario == "Я вернул долг":
        operation_type = "Возврат займа"
        final_category = "Не учитывать"
        personal_amount = 0.0
    else:
        operation_type = "Не учитывать"
        final_category = "Не учитывать"
        personal_amount = 0.0
    return operation_type, final_category, personal_amount, manual_planning_updates(operation_type, final_category, personal_amount)


def save_operation_reassignment(row: pd.Series, scenario: str, category: str, create_rule: bool, profile: dict) -> None:
    operation_type, final_category, personal_amount, planning_updates = operation_update_from_reassignment(row, scenario, category)
    update_operation(
        row["id"],
        {
            "operation_type": operation_type,
            "budget_category": final_category,
            "personal_amount": personal_amount,
            **planning_updates,
            "confidence": 0.95,
            "classification_source": "manual_reassignment",
            "needs_review": False,
        },
    )
    if create_rule:
        append_profile_rule(profile["id"], build_rule_from_operation(row.to_dict(), operation_type, final_category, personal_amount))
        reclassify_profile_operations(profile["id"], preserve_manual_overrides=True)


def render_operation_reassignment_section(profile: dict, operations: pd.DataFrame) -> None:
    st.subheader("Исправить назначение операции")
    st.caption("Если вы ошиблись после разметки, выберите операцию и назначьте ей новый смысл. Например: поступление было не возвратом долга, а переводом самому себе или компенсацией.")
    if operations.empty:
        st.info("За выбранный месяц операций нет.")
        return
    editable = operations.copy()
    editable["operation_datetime"] = pd.to_datetime(editable["operation_datetime"], errors="coerce")
    editable["_abs"] = editable["bank_amount"].abs()
    mode = st.radio(
        "Какие операции показать",
        ["Все", "Поступления", "Списания"],
        horizontal=True,
        key=make_widget_key("reassign_mode", profile["id"]),
    )
    if mode == "Поступления":
        editable = editable[editable["direction"].isin(["income", "incoming"])]
    elif mode == "Списания":
        editable = editable[~editable["direction"].isin(["income", "incoming"])]
    search = st.text_input(
        "Поиск по описанию",
        placeholder="Например: Никита, TILDA, СБП",
        key=make_widget_key("reassign_search", profile["id"]),
    )
    if search:
        editable = editable[editable["description"].fillna("").str.contains(search, case=False, regex=False)]
    editable = editable.sort_values(["operation_datetime", "_abs"], ascending=[False, False]).head(200)
    if editable.empty:
        st.info("По выбранному фильтру операций нет.")
        return
    options = editable["id"].astype(str).tolist()
    label_by_id = {str(row["id"]): operation_choice_label(row) for _, row in editable.iterrows()}
    selected_id = st.selectbox(
        "Операция",
        options,
        format_func=lambda value: label_by_id.get(str(value), str(value)),
        key=make_widget_key("reassign_operation", profile["id"], mode, search),
    )
    row = editable[editable["id"].astype(str) == str(selected_id)].iloc[0]
    question, scenarios, default_scenario = reassignment_options_for_row(row)
    scenario = st.selectbox(question, scenarios, index=scenarios.index(default_scenario), key=make_widget_key("reassign_scenario", profile["id"], selected_id))
    if scenario in {"Обычный расход", "Компенсация расходов"}:
        category = st.selectbox(
            "Категория расхода",
            expense_categories(profile),
            key=make_widget_key("reassign_expense_category", profile["id"], selected_id, scenario),
        )
    elif scenario == "Личный доход":
        category = st.selectbox(
            "Категория дохода",
            income_categories(profile),
            key=make_widget_key("reassign_income_category", profile["id"], selected_id),
        )
    else:
        category = "Не учитывать"
        st.caption("Эта операция не будет считаться личным доходом, расходом или частью плана.")
    if scenario == "Компенсация расходов":
        st.caption("Компенсация не считается доходом. Она уменьшает расход выбранной категории.")
    remember_choice = st.radio(
        "Запомнить для похожих операций?",
        ["Только эта операция", "Похожие операции этого месяца", "Всегда для этого профиля", "Предложить в общий справочник"],
        horizontal=False,
        key=make_widget_key("reassign_remember_choice", profile["id"], selected_id, scenario),
    )
    operation_type, final_category, personal_amount, _ = operation_update_from_reassignment(row, scenario, category)
    st.info(
        f"После сохранения: {operation_type} · {final_category} · влияние на бюджет: {money(personal_amount)}"
    )
    if st.button("Сохранить новое назначение", key=make_widget_key("save_reassignment", profile["id"], selected_id, scenario), type="primary"):
        create_rule = remember_choice in {"Похожие операции этого месяца", "Всегда для этого профиля"}
        save_operation_reassignment(row, scenario, category, create_rule, profile)
        if remember_choice == "Предложить в общий справочник":
            storage.record_global_rule_candidate(row.to_dict(), final_category, profile["id"])
        st.success("Операция обновлена. Месяц пересчитан.")
        st.rerun()


def normalized_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def personal_rule_exists_for_anchor(profile: dict, anchor: str) -> bool:
    needle = normalized_text(anchor)
    if not needle:
        return False
    for rule in (profile.get("merchant_rules", []) or []) + (profile.get("plan_rules", []) or []):
        anchors = []
        for key in ["merchant_anchor", "person_anchor"]:
            if rule.get(key):
                anchors.append(rule[key])
        anchors.extend(rule.get("contains_any", []) or [])
        anchors.extend(rule.get("match_contains_any", []) or [])
        if any(normalized_text(anchor_value) == needle for anchor_value in anchors):
            return True
    return False


def suggest_category_for_operation(operation: dict, profile: dict) -> dict:
    text = normalized_text(
        " ".join(
            str(operation.get(key) or "")
            for key in ["merchant_anchor", "person_anchor", "description", "raw_category"]
        )
    )
    for rule in profile.get("merchant_rules", []) or []:
        if rule.get("enabled", True) and rule_matches(rule, operation):
            return {
                "suggested_category": rule.get("budget_category") or rule.get("plan_category") or "Прочее / проверить",
                "confidence": rule.get("confidence", 0.95),
                "source": "personal_rule",
                "reason": "Совпало личное правило профиля",
            }
    try:
        global_rules = pd.read_json("config/global_merchant_rules.json").to_dict("records")
    except ValueError:
        global_rules = []
    for rule in global_rules:
        patterns = rule.get("patterns") or rule.get("contains_any") or []
        if any(normalized_text(pattern) in text for pattern in patterns):
            return {
                "suggested_category": rule.get("category") or rule.get("budget_category") or "Прочее / проверить",
                "confidence": rule.get("confidence", 0.9),
                "source": "global_merchant_rule",
                "reason": "Совпало правило глобального справочника",
            }
    current_category = operation.get("budget_category") or operation.get("plan_category") or "Прочее / проверить"
    if current_category and current_category not in {"Прочее / проверить", "Проверить"}:
        return {
            "suggested_category": current_category,
            "confidence": operation.get("confidence", 0.5),
            "source": "current_category",
            "reason": "Используется текущая категория операции",
        }
    return {
        "suggested_category": "Прочее / проверить",
        "confidence": 0.2,
        "source": "fallback",
        "reason": "Правило не найдено",
    }


def build_unknown_merchant_candidates(profile_id: str, profile: dict | None = None) -> pd.DataFrame:
    profile = profile or load_profile(profile_id)
    history = operations_df(profile_id)
    if history.empty:
        return pd.DataFrame()
    confidence = pd.to_numeric(history.get("confidence", pd.Series(0, index=history.index)), errors="coerce").fillna(0)
    needs_review = history.get("needs_review", pd.Series(False, index=history.index)).fillna(False).astype(bool)
    unresolved = history[(needs_review | (confidence < 0.85))].copy()
    if unresolved.empty:
        return pd.DataFrame()
    unresolved["anchor"] = (
        unresolved.get("merchant_anchor", pd.Series("", index=unresolved.index)).fillna("").astype(str)
    )
    person_anchor = unresolved.get("person_anchor", pd.Series("", index=unresolved.index)).fillna("").astype(str)
    normalized_description = unresolved.get("normalized_description", pd.Series("", index=unresolved.index)).fillna("").astype(str)
    unresolved.loc[unresolved["anchor"] == "", "anchor"] = person_anchor
    unresolved.loc[unresolved["anchor"] == "", "anchor"] = normalized_description.str.slice(0, 80)
    unresolved = unresolved[unresolved["anchor"].fillna("") != ""].copy()
    if unresolved.empty:
        return pd.DataFrame()
    rows = []
    for anchor, group in unresolved.groupby("anchor"):
        has_rule = personal_rule_exists_for_anchor(profile, str(anchor))
        if has_rule:
            continue
        sample = group.iloc[0].to_dict()
        suggestion = suggest_category_for_operation(sample, profile)
        months_seen = group["operation_datetime"].astype(str).str[:7].nunique()
        rows.append(
            {
                "merchant / anchor": anchor,
                "пример": str(group["description"].dropna().iloc[0])[:160] if not group["description"].dropna().empty else "",
                "количество": len(group),
                "сумма": float(group["bank_amount"].abs().sum()),
                "месяцев": months_seen,
                "банки": ", ".join(sorted(group["bank"].dropna().astype(str).unique())),
                "текущая категория": sample.get("budget_category", ""),
                "предложенная категория": suggestion["suggested_category"],
                "уверенность": suggestion["confidence"],
                "источник": suggestion["source"],
                "has_rule": has_rule,
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["количество", "сумма"], ascending=[False, False])
    return result


def render_unknown_merchant_candidates(profile: dict) -> None:
    st.subheader("Новые операции для справочника")
    candidates = build_unknown_merchant_candidates(profile["id"], profile)
    if candidates.empty:
        st.success("Новых повторяющихся операций без правила пока нет.")
        return
    st.dataframe(
        candidates.drop(columns=["has_rule"], errors="ignore").head(30),
        use_container_width=True,
        hide_index=True,
    )
    anchors = candidates["merchant / anchor"].astype(str).tolist()
    selected_anchor = st.selectbox("Операция / merchant", anchors, key=make_widget_key("unknown_anchor_select", profile["id"], len(anchors)))
    selected = candidates[candidates["merchant / anchor"].astype(str) == selected_anchor].iloc[0]
    category = st.selectbox(
        "Категория",
        expense_categories(profile),
        index=expense_categories(profile).index(selected["предложенная категория"]) if selected["предложенная категория"] in expense_categories(profile) else 0,
        key=make_widget_key("unknown_anchor_category", profile["id"], selected_anchor),
    )
    action = st.radio(
        "Что сделать",
        ["Создать правило для профиля", "Предложить в общий справочник", "Игнорировать"],
        horizontal=True,
        key=make_widget_key("unknown_anchor_action", profile["id"], selected_anchor),
    )
    if st.button("Применить", key=make_widget_key("unknown_anchor_apply", profile["id"], selected_anchor, action)):
        if action == "Создать правило для профиля":
            rule = {
                "id": f"merchant_{uuid.uuid4().hex[:10]}",
                "enabled": True,
                "merchant_anchor": selected_anchor,
                "contains_any": [selected_anchor],
                "direction": "expense",
                "operation_type": "Личный расход",
                "budget_category": category,
                "personal_amount_mode": "abs",
                "confidence": 0.95,
                "comment": "Создано из новых операций справочника",
            }
            upsert_profile_rule(profile["id"], rule)
            stats = reclassify_profile_operations(profile["id"], preserve_manual_overrides=True)
            st.success(f"Правило создано. Пересчитано операций: {stats['changed']}.")
        elif action == "Предложить в общий справочник":
            storage.record_global_rule_candidate({"merchant_anchor": selected_anchor, "description": selected["пример"]}, category, profile["id"])
            st.success("Кандидат добавлен в общий справочник.")
        else:
            st.info("Кандидат оставлен без правила.")
        st.rerun()


def render_attention_summary(operations: pd.DataFrame) -> None:
    review = operations[operations["needs_review"] == True] if not operations.empty else pd.DataFrame()
    if review.empty:
        st.success("Нет операций, требующих проверки.")
        return
    income_count = int((review["direction"] == "income").sum())
    expense_count = int((review["direction"] != "income").sum())
    st.warning(f"Проверьте операции: всего {len(review)}, поступлений {income_count}, списаний {expense_count}.")
    st.dataframe(
        display_operations(review.sort_values("bank_amount", key=lambda s: s.abs(), ascending=False).head(5)),
        use_container_width=True,
        hide_index=True,
    )


def profile_plan_df(profile: dict) -> pd.DataFrame:
    plan = profile.get("plan") or default_profile_template().get("plan", {})
    rows = [{"budget_category": category, "suggested_plan": amount} for category, amount in plan.items()]
    return pd.DataFrame(rows)


def profile_income_plan_df(profile: dict) -> pd.DataFrame:
    plan = profile.get("income_plan") or default_profile_template().get("income_plan", {})
    rows = [{"income_category": category, "suggested_plan": amount} for category, amount in plan.items()]
    return pd.DataFrame(rows)


def display_operations(operations: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "operation_datetime": "дата",
        "bank": "банк",
        "document_type": "тип документа",
        "account_type": "тип счёта",
        "account_role": "роль счёта",
        "account_id": "account id",
        "raw_category": "категория банка",
        "merchant_anchor": "merchant",
        "person_anchor": "человек",
        "description": "описание",
        "bank_amount": "сумма",
        "direction": "направление",
        "cashflow_amount": "движение по счёту",
        "operation_type": "тип",
        "budget_category": "категория",
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
        "needs_review": "проверить",
    }
    existing = [column for column in columns if column in operations.columns]
    return operations[existing].rename(columns=columns)


def editable_review(profile: dict, operations: pd.DataFrame, key_prefix: str = "review") -> None:
    review = operations[operations["needs_review"] == True]
    if review.empty:
        st.info("Сейчас нет операций, которые нужно проверить.")
        return
    if st.session_state.get("focus_review"):
        st.success("Открыты операции на проверку.")
    review_mode = st.radio(
        "Фильтр",
        ["Все", "Поступления", "Списания"],
        horizontal=True,
        key=make_widget_key(key_prefix, "filter"),
    )
    if review_mode == "Поступления":
        review = review[review["direction"] == "income"]
    elif review_mode == "Списания":
        review = review[review["direction"] != "income"]
    review = review.assign(_abs_amount=review["bank_amount"].abs())
    focus_id = st.session_state.get("focus_operation_id")
    if focus_id and "id" in review.columns:
        review["_focus"] = review["id"].astype(str).eq(str(focus_id)).astype(int)
        review = review.sort_values(["_focus", "_abs_amount"], ascending=[False, False])
    else:
        review = review.sort_values("_abs_amount", ascending=False)
    st.caption(
        f"На проверку: {len(review)} · Поступлений: {int((review['direction'] == 'income').sum())} · "
        f"Списаний: {int((review['direction'] != 'income').sum())}"
    )
    income_review = review[review["direction"] == "income"]
    expense_review = review[review["direction"] != "income"]
    st.subheader("Поступления на проверку")
    if income_review.empty:
        st.info("Поступлений на проверку нет.")
    else:
        render_review_rows(profile, income_review, mode="income", key_prefix=key_prefix)
    st.subheader("Расходы/списания на проверку")
    if expense_review.empty:
        st.info("Списаний на проверку нет.")
    else:
        render_review_rows(profile, expense_review, mode="expense", key_prefix=key_prefix)


def quick_update_operation(row: pd.Series, operation_type: str, category: str, personal_amount: float) -> None:
    planning_updates = manual_planning_updates(operation_type, category, personal_amount)
    update_operation(
        row["id"],
        {
            "operation_type": operation_type,
            "budget_category": category,
            "personal_amount": personal_amount,
            **planning_updates,
            "confidence": 0.95,
            "classification_source": "manual_quick_button",
            "needs_review": False,
        },
    )
    st.rerun()


def render_quick_buttons(row: pd.Series, categories: list[str], prefix: str, selected_category: str) -> None:
    default_category = selected_category if selected_category in categories else "Прочее / проверить"
    bank_abs = abs(float(row["bank_amount"] or 0))
    if row["direction"] == "income":
        cols = st.columns(6)
        if cols[0].button("Это доход", key=f"{prefix}_quick_income_{row['id']}"):
            quick_update_operation(row, "Личный доход", "Прочий личный доход", bank_abs)
        if cols[1].button("Компенсация", key=f"{prefix}_quick_comp_{row['id']}"):
            quick_update_operation(row, "Компенсация совместных расходов", default_category, -bank_abs)
        if cols[2].button("Возврат долга", key=f"{prefix}_quick_debt_{row['id']}"):
            quick_update_operation(row, "Возврат займа", default_category, 0.0)
        if cols[3].button("Перевод самому себе", key=f"{prefix}_quick_transfer_{row['id']}"):
            quick_update_operation(row, "Внутренний перевод", "", 0.0)
        if cols[4].button("Проектный приход", key=f"{prefix}_quick_project_{row['id']}"):
            quick_update_operation(row, "Проектный приход", "", 0.0)
        if cols[5].button("Не учитывать", key=f"{prefix}_quick_ignore_{row['id']}"):
            quick_update_operation(row, "Не учитывать", "", 0.0)
    else:
        cols = st.columns(5)
        if cols[0].button("Это расход", key=f"{prefix}_quick_expense_{row['id']}"):
            quick_update_operation(row, "Личный расход", default_category, bank_abs)
        if cols[1].button("Перевод самому себе", key=f"{prefix}_quick_transfer_{row['id']}"):
            quick_update_operation(row, "Внутренний перевод", "", 0.0)
        if cols[2].button("Долг / заём", key=f"{prefix}_quick_debt_{row['id']}"):
            quick_update_operation(row, "Заём выдан", default_category, 0.0)
        if cols[3].button("Проектный расход", key=f"{prefix}_quick_project_{row['id']}"):
            quick_update_operation(row, "Проектный расход", "", 0.0)
        if cols[4].button("Не учитывать", key=f"{prefix}_quick_ignore_{row['id']}"):
            quick_update_operation(row, "Не учитывать", "", 0.0)


def default_personal_amount(operation_type: str, bank_amount: float, current_value: float) -> float:
    bank_abs = abs(float(bank_amount or 0))
    if operation_type == "Компенсация совместных расходов":
        return -bank_abs
    if operation_type in {"Личный расход", "Личный доход", "Расход из фонда"}:
        return bank_abs
    if operation_type in {"Внутренний перевод", "Заём выдан", "Возврат займа", "Не учитывать"}:
        return 0.0
    return float(current_value or 0)


def manual_planning_updates(operation_type: str, category: str, personal_amount: float) -> dict:
    if operation_type == "Личный расход":
        return {
            "budget_amount": abs(personal_amount),
            "planning_amount": abs(personal_amount),
            "count_in_budget": True,
            "count_in_plan": True,
            "plan_category": category,
            "plan_exclusion_reason": "",
        }
    if operation_type == "Компенсация совместных расходов":
        amount = -abs(personal_amount)
        return {
            "budget_amount": amount,
            "planning_amount": amount,
            "count_in_budget": True,
            "count_in_plan": True,
            "plan_category": category,
            "plan_exclusion_reason": "",
        }
    if operation_type == "Расход из фонда":
        return {
            "budget_amount": abs(personal_amount),
            "planning_amount": 0.0,
            "count_in_budget": True,
            "count_in_plan": False,
            "plan_category": category,
            "plan_exclusion_reason": "Разовый расход из фонда",
        }
    if operation_type == "Личный доход":
        return {
            "budget_amount": abs(personal_amount),
            "planning_amount": 0.0,
            "count_in_budget": True,
            "count_in_plan": False,
            "plan_category": category,
            "plan_exclusion_reason": "Доход не входит в расходный план",
        }
    return {
        "budget_amount": 0.0,
        "planning_amount": 0.0,
        "count_in_budget": False,
        "count_in_plan": False,
        "plan_category": category,
        "plan_exclusion_reason": "Не входит в базовый план",
    }


def render_review_rows(profile: dict, review: pd.DataFrame, mode: str, key_prefix: str = "review") -> None:
    for _, row in review.head(30).iterrows():
        with st.expander(f"{row['operation_datetime']} · {money(row['bank_amount'])} · {row['description']}"):
            st.caption(f"{row.get('bank', '')} · сейчас: {row.get('operation_type', 'Проверить')} · {row.get('budget_category', 'Прочее / проверить')}")
            row_key = make_widget_key(key_prefix, mode, row["id"])
            render_quick_buttons(row, expense_categories(profile), row_key, row.get("budget_category", "Прочее / проверить"))
            st.divider()
            if row["direction"] == "income":
                scenarios = ["Личный доход", "Компенсация расходов", "Возврат долга", "Перевод самому себе", "Проектный приход", "Не учитывать", "Другое / расширенная настройка"]
                scenario = st.selectbox("Что это за поступление?", scenarios, key=make_widget_key(row_key, "type"))
                if scenario == "Личный доход":
                    operation_type = "Личный доход"
                    category_options = income_categories(profile)
                    category_label = "Категория дохода"
                    amount_value = abs(float(row["bank_amount"] or 0))
                elif scenario == "Компенсация расходов":
                    operation_type = "Компенсация совместных расходов"
                    category_options = expense_categories(profile)
                    category_label = "Какую категорию уменьшает?"
                    amount_value = -abs(float(row["bank_amount"] or 0))
                    st.caption("Компенсация не считается доходом. Она уменьшает расход выбранной категории.")
                elif scenario == "Возврат долга":
                    operation_type = "Возврат займа"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                elif scenario == "Проектный приход":
                    operation_type = "Проектный приход"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                elif scenario in {"Перевод самому себе", "Не учитывать"}:
                    operation_type = "Внутренний перевод" if scenario == "Перевод самому себе" else "Не учитывать"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                else:
                    operation_type = st.selectbox("operation_type", default_operation_types(), key=make_widget_key(row_key, "technical_type"))
                    category_options = income_categories(profile)
                    category_label = "Категория"
                    amount_value = default_personal_amount(operation_type, row["bank_amount"], row["personal_amount"])
            else:
                scenarios = ["Регулярный расход", "Перевод самому себе", "Долг / заём", "Проектный расход", "Не учитывать", "Другое / расширенная настройка"]
                scenario = st.selectbox("Что это за списание?", scenarios, key=make_widget_key(row_key, "type"))
                if scenario == "Регулярный расход":
                    operation_type = "Личный расход"
                    category_options = expense_categories(profile)
                    category_label = "Категория расхода"
                    amount_value = abs(float(row["bank_amount"] or 0))
                elif scenario == "Долг / заём":
                    operation_type = "Заём выдан"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                elif scenario == "Проектный расход":
                    operation_type = "Проектный расход"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                elif scenario in {"Перевод самому себе", "Не учитывать"}:
                    operation_type = "Внутренний перевод" if scenario == "Перевод самому себе" else "Не учитывать"
                    category_options = ["Не учитывать"]
                    category_label = "Категория"
                    amount_value = 0.0
                else:
                    operation_type = st.selectbox("operation_type", default_operation_types(), key=make_widget_key(row_key, "technical_type"))
                    category_options = expense_categories(profile)
                    category_label = "Категория"
                    amount_value = default_personal_amount(operation_type, row["bank_amount"], row["personal_amount"])
            col2, col3 = st.columns(2)
            category = col2.selectbox(
                category_label,
                category_options,
                index=category_options.index(row["budget_category"]) if row["budget_category"] in category_options else 0,
                key=make_widget_key(row_key, "cat", operation_type),
            )
            personal_amount = col3.number_input("Сумма для личного бюджета", value=float(amount_value), step=100.0, key=make_widget_key(row_key, "amount", operation_type))
            comment = st.text_input("Комментарий", value=row.get("comment", "") or "", key=make_widget_key(row_key, "comment"))
            create_rule = st.checkbox("Применить ко всем похожим операциям", key=make_widget_key(row_key, "rule"))
            if st.button("Сохранить правку", key=make_widget_key(row_key, "save")):
                planning_updates = manual_planning_updates(operation_type, category, personal_amount)
                update_operation(
                    row["id"],
                    {
                        "operation_type": operation_type,
                        "budget_category": category,
                        "personal_amount": personal_amount,
                        **planning_updates,
                        "confidence": 0.95,
                        "classification_source": "manual_review",
                        "needs_review": False,
                        "comment": comment,
                    },
                )
                if create_rule:
                    append_profile_rule(
                        profile["id"],
                        build_rule_from_operation(row.to_dict(), operation_type, category, personal_amount),
                    )
                st.success("Сохранено")
                st.rerun()


def settings(profile: dict) -> None:
    with st.sidebar.expander("Настройки плана"):
        profile["monthly_limit"] = st.number_input(
            "Лимит на месяц",
            min_value=0.0,
            value=float(profile.get("monthly_limit", 0)),
            step=1000.0,
            key=f"monthly_limit_{profile['id']}",
        )
        profile["plan_strategy"] = st.selectbox(
            "Автоплан",
            ["median", "p75"],
            index=0 if profile.get("plan_strategy", "median") == "median" else 1,
            key=f"plan_strategy_{profile['id']}",
        )
        profile["buffer_percent"] = st.number_input(
            "Запас, %",
            min_value=0.0,
            max_value=100.0,
            value=float(profile.get("buffer_percent", 10)),
            step=1.0,
            key=f"buffer_percent_{profile['id']}",
        )
        profile["round_to"] = st.number_input(
            "Округлять до",
            min_value=100,
            value=int(profile.get("round_to", 500)),
            step=100,
            key=f"round_to_{profile['id']}",
        )
        if st.button("Сохранить настройки", use_container_width=True):
            save_profile(profile)
            st.rerun()
    with st.sidebar.expander("План доходов"):
        income_plan = profile.get("income_plan") or default_profile_template().get("income_plan", {})
        for category, value in income_plan.items():
            income_plan[category] = st.number_input(
                category,
                min_value=0.0,
                value=float(value),
                step=1000.0,
                key=f"income_plan_{profile['id']}_{category}",
            )
        profile["income_plan"] = income_plan
        if st.button("Сохранить план доходов", use_container_width=True):
            save_profile(profile)
            st.rerun()
    with st.sidebar.expander("Мои данные для переводов"):
        identity = profile.get("own_identity") or {"full_name": "", "name_aliases": [], "phones": [], "account_last4": [], "banks": []}
        identity["full_name"] = st.text_input("Ф.И.О. полностью", value=identity.get("full_name", ""), key=f"identity_full_name_{profile['id']}")
        aliases_text = st.text_area(
            "Варианты имени, каждый с новой строки",
            value="\n".join(identity.get("name_aliases", [])),
            key=f"identity_aliases_{profile['id']}",
        )
        phones_text = st.text_input("Телефоны через запятую", value=", ".join(identity.get("phones", [])), key=f"identity_phones_{profile['id']}")
        last4_text = st.text_input("Последние 4 цифры карт/счетов через запятую", value=", ".join(identity.get("account_last4", [])), key=f"identity_last4_{profile['id']}")
        banks_text = st.text_input("Банки и кошельки через запятую", value=", ".join(identity.get("banks", [])), key=f"identity_banks_{profile['id']}")
        if st.button("Сохранить мои данные", use_container_width=True, key=f"save_identity_{profile['id']}"):
            profile["own_identity"] = {
                "full_name": identity["full_name"].strip(),
                "name_aliases": [item.strip() for item in aliases_text.splitlines() if item.strip()],
                "phones": [item.strip() for item in phones_text.split(",") if item.strip()],
                "account_last4": [item.strip() for item in last4_text.split(",") if item.strip()],
                "banks": [item.strip() for item in banks_text.split(",") if item.strip()],
            }
            save_profile(profile)
            st.rerun()


def danger_zone(profile: dict) -> None:
    with st.sidebar.expander("Очистка"):
        st.caption("Удаляет только операции текущего профиля. Профиль, план и правила останутся.")
        if st.button("Очистить операции профиля", use_container_width=True):
            deleted = delete_profile_operations(profile["id"])
            st.sidebar.success(f"Удалено операций: {deleted}")
            st.rerun()


def reclassification_controls(profile: dict) -> None:
    with st.sidebar.expander("Правила"):
        st.caption("Применяет текущие правила к уже импортированным операциям.")
        preserve = st.checkbox(
            "Не перетирать ручные правки",
            value=True,
            key=make_widget_key("reclassify_preserve_manual", profile["id"]),
        )
        if st.button(
            "Переклассифицировать операции по текущим правилам",
            use_container_width=True,
            key=make_widget_key("reclassify_profile", profile["id"]),
        ):
            stats = reclassify_profile_operations(profile["id"], preserve_manual_overrides=preserve)
            st.session_state["last_reclassification_stats"] = stats
            st.sidebar.success(f"Обновлено операций: {stats['changed']} из {stats['processed']}.")
            st.rerun()


def auto_plan_controls(profile: dict, history: pd.DataFrame) -> pd.DataFrame:
    plan = profile_plan_df(profile)
    if st.sidebar.button("Обновить автоплан по истории", use_container_width=True):
        generated = build_auto_plan(
            history.tail(2000),
            strategy=profile.get("plan_strategy", "median"),
            buffer_percent=float(profile.get("buffer_percent", 10)),
            round_to=int(profile.get("round_to", 500)),
        )
        if generated.empty:
            st.sidebar.info("Пока мало истории, оставил базовый план.")
        else:
            profile["plan"] = dict(zip(generated["budget_category"], generated["suggested_plan"]))
            profile["monthly_limit"] = float(generated["suggested_plan"].sum())
            save_profile(profile)
            st.sidebar.success("Автоплан обновлён.")
            st.rerun()
    return plan


def direction_label(direction: str) -> str:
    return "поступление" if direction in {"income", "incoming"} else "списание"


def display_plan_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(
            columns=[
                "Операция / человек / merchant",
                "Направление",
                "Сколько раз",
                "Сумма за историю",
                "В среднем в месяц",
                "Примеры",
                "Рекомендация",
            ]
        )
    df = candidates.copy()
    nature_labels = {
        "recurring": "похоже на постоянную статью",
        "oneoff_large": "разовая крупная / проверить",
        "oneoff_minor": "мелкая разовая",
        "unknown": "на проверку",
    }
    df["Рекомендация"] = df.apply(
        lambda row: nature_labels.get(str(row.get("expense_nature") or ""), "разобрать перед автопланом")
        if row["importance_level"] in {"important", "oneoff_large"}
        else "можно оставить на проверку",
        axis=1,
    )
    result = pd.DataFrame(
        {
            "Операция / человек / merchant": df["anchor"],
            "Направление": df["direction"].map(direction_label),
            "Сколько раз": df["count"],
            "Сумма за историю": df["total_sum"],
            "В среднем в месяц": df["median_monthly_sum"],
            "Примеры": df["examples"],
            "Тип": df.get("expense_nature", "").map(nature_labels).fillna("на проверку") if "expense_nature" in df.columns else "",
            "Рекомендация": df["Рекомендация"],
        }
    )
    return result


def display_hidden_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=["Операция", "Направление", "Сумма", "Пример"])
    table = candidates.rename(columns={"total_sum": "amount", "examples": "example"}).copy()
    return pd.DataFrame(
        {
            "Операция": table["anchor"],
            "Направление": table["direction"].map(direction_label),
            "Сумма": table["amount"],
            "Пример": table["example"],
        }
    )


def display_recommended_plan(recommended: pd.DataFrame) -> pd.DataFrame:
    columns = ["Категория", "Слой", "История", "Среднее", "Медиана", "Рекомендую", "Статус", "Комментарий"]
    if recommended.empty:
        return pd.DataFrame(columns=columns)
    df = recommended.copy()
    if "layer" not in df.columns:
        df["layer"] = "База"
    if "status" not in df.columns:
        df["status"] = "ready"
    if "comment" not in df.columns:
        df["comment"] = ""
    status_labels = {
        "ready": "Готово",
        "needs_classification": "Разобрать",
        "low_history": "Мало истории",
        "excluded": "Исключено",
        "check": "Проверить",
        "ready": "Готово",
    }
    return pd.DataFrame(
        {
            "Категория": df["budget_category"],
            "Слой": df["layer"],
            "История": df["months_count"].fillna(0).astype(int).astype(str) + " мес.",
            "Среднее": df["mean"].round(0).astype(int),
            "Медиана": df["median"].round(0).astype(int),
            "Рекомендую": df["suggested_plan"].round(0).astype(int),
            "Статус": df["status"].map(status_labels).fillna(df["status"]),
            "Комментарий": df["comment"],
        },
        columns=columns,
    )


def category_sum(df: pd.DataFrame, names: set[str]) -> float:
    if df.empty or "budget_category" not in df.columns or "suggested_plan" not in df.columns:
        return 0.0
    return float(df.loc[df["budget_category"].isin(names), "suggested_plan"].sum())


def friendly_plan_table(recommended: pd.DataFrame) -> pd.DataFrame:
    display = display_recommended_plan(recommended)
    if display.empty:
        return display
    return display[["Категория", "Рекомендую", "История", "Статус", "Комментарий"]]


def rule_anchor(rule: dict) -> str:
    anchors = rule.get("match_contains_any") or rule.get("contains_any") or []
    return rule.get("merchant_anchor") or rule.get("person_anchor") or (", ".join(anchors) if anchors else "")


def scenario_label(rule: dict) -> str:
    scenario = rule.get("scenario") or ""
    labels = {
        "regular_expense": "Регулярный расход",
        "compensation": "Компенсация",
        "personal_income": "Личный доход",
        "internal_transfer": "Перевод между своими счетами",
        "debt": "Долг / заём",
        "loan_return": "Долг / заём",
        "project_turnover": "Проектный оборот",
        "ignore_in_plan": "Не учитывать",
        "custom": "Другое",
        "custom_income": "Другое",
    }
    return labels.get(scenario, rule.get("operation_type") or "Правило")


def rule_affected_count(rule: dict, operations: pd.DataFrame) -> int:
    if operations.empty:
        return 0
    anchor = rule_anchor(rule)
    direction = rule.get("direction")
    if not anchor:
        return 0
    text = anchor.casefold()
    mask = pd.Series(True, index=operations.index)
    if direction:
        mask &= operations["direction"].fillna("").eq(direction)
    haystack = (
        operations.get("description", pd.Series("", index=operations.index)).fillna("").astype(str)
        + " "
        + operations.get("merchant_anchor", pd.Series("", index=operations.index)).fillna("").astype(str)
        + " "
        + operations.get("person_anchor", pd.Series("", index=operations.index)).fillna("").astype(str)
    ).str.casefold()
    return int((mask & haystack.str.contains(re.escape(text), regex=True)).sum())


def rules_dataframe(profile: dict, operations: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source, rules in [("merchant", profile.get("merchant_rules", []) or []), ("plan", profile.get("plan_rules", []) or [])]:
        for index, rule in enumerate(rules):
            rows.append(
                {
                    "source": source,
                    "index": index,
                    "id": rule.get("id", ""),
                    "Название / человек / merchant": rule_anchor(rule),
                    "Направление": direction_label(rule.get("direction", "expense")),
                    "Сценарий": scenario_label(rule),
                    "Категория": rule.get("budget_category") or rule.get("plan_category") or "Не учитывать",
                    "Статус": "активно" if rule.get("enabled", True) else "выключено",
                    "Операций": rule_affected_count(rule, operations),
                    "Последнее применение": rule.get("updated_at", ""),
                }
            )
    return pd.DataFrame(rows)


def save_rule_by_source(profile: dict, source: str, index: int, rule: dict) -> None:
    if source == "plan":
        rules = list(profile.get("plan_rules", []) or [])
        if 0 <= index < len(rules):
            rules[index] = rule
        else:
            rules.insert(0, rule)
        save_plan_rules(profile["id"], rules)
    else:
        rules = list(profile.get("merchant_rules", []) or [])
        if 0 <= index < len(rules):
            rules[index] = rule
        else:
            rules.insert(0, rule)
        save_merchant_rules(profile["id"], rules)


def delete_rule_by_source(profile: dict, source: str, index: int) -> None:
    if source == "plan":
        rules = list(profile.get("plan_rules", []) or [])
        if 0 <= index < len(rules):
            rules.pop(index)
        save_plan_rules(profile["id"], rules)
    else:
        rules = list(profile.get("merchant_rules", []) or [])
        if 0 <= index < len(rules):
            rules.pop(index)
        save_merchant_rules(profile["id"], rules)


def build_plan_rule_from_scenario(anchor: str, direction: str, scenario: str, category: str, custom: dict | None = None) -> dict:
    direction = infer_anchor_direction(anchor) or direction
    base = {
        "id": f"plan_{uuid.uuid4().hex[:10]}",
        "enabled": True,
        "match_contains_any": [anchor],
        "direction": direction,
        "scenario": "",
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "plan_category": "Прочее / проверить",
        "budget_amount_mode": "0",
        "planning_amount_mode": "0",
        "count_in_budget": False,
        "count_in_plan": False,
    }
    if scenario == "Регулярный расход":
        base.update(
            scenario="regular_expense",
            operation_type="Личный расход",
            budget_category=category,
            plan_category=category,
            budget_amount_mode="abs",
            planning_amount_mode="abs",
            count_in_budget=True,
            count_in_plan=True,
        )
    elif scenario == "Считать постоянным расходом":
        base.update(
            scenario="regular_expense",
            operation_type="Личный расход",
            budget_category=category,
            plan_category=category,
            budget_amount_mode="abs",
            planning_amount_mode="abs",
            count_in_budget=True,
            count_in_plan=True,
            manual_recurring_confirmed=True,
            comment="Пользователь подтвердил постоянный расход для одиночной операции",
        )
    elif scenario in {"Это разовая крупная операция", "Добавить в план только вручную"}:
        base.update(
            scenario="oneoff_large",
            operation_type="Расход из фонда" if scenario == "Это разовая крупная операция" else "Личный расход",
            budget_category=category,
            plan_category=category,
            budget_amount_mode="abs",
            planning_amount_mode="0",
            count_in_budget=True,
            count_in_plan=False,
            expense_nature="oneoff_large",
            comment="Разовая крупная операция, не включена как постоянная статья плана",
        )
    elif scenario == "Перевод между своими счетами":
        base.update(scenario="internal_transfer", operation_type="Внутренний перевод", budget_category="Не учитывать", plan_category="Не учитывать")
    elif scenario == "Долг / заём":
        debt_type = (custom or {}).get("debt_type", "Заём выдан")
        base.update(scenario="debt", operation_type=debt_type, budget_category="Прочее / проверить", plan_category="Не учитывать")
    elif scenario == "Проектный оборот":
        base.update(scenario="project_turnover", operation_type="Проектный оборот", budget_category="Не учитывать", plan_category="Не учитывать")
    elif scenario == "Не учитывать в плане":
        base.update(scenario="ignore_in_plan", operation_type="Не учитывать", budget_category="Не учитывать", plan_category="Не учитывать")
    elif custom:
        base.update(
            scenario="custom",
            operation_type=custom["operation_type"],
            budget_category=custom["budget_category"],
            plan_category=custom["plan_category"],
            budget_amount_mode=custom["budget_amount_mode"],
            planning_amount_mode=custom["planning_amount_mode"],
            count_in_budget=custom["count_in_budget"],
            count_in_plan=custom["count_in_plan"],
        )
    return base


def apply_rule_scope(rule: dict, selected: pd.Series, rule_scope: str, report_month: str | None) -> dict:
    rule["rule_scope"] = rule_scope
    if rule_scope == "single_operation":
        rule["operation_id"] = str(selected.get("first_operation_id") or "")
    elif rule_scope == "current_month_similar":
        rule["rule_month"] = report_month or str(selected.get("first_operation_datetime") or "")[:7]
    return rule


def apply_plan_behavior(rule: dict, plan_behavior: str, selected: pd.Series) -> dict:
    if plan_behavior == "Учитывать как постоянную статью":
        rule["planning_amount_mode"] = rule.get("planning_amount_mode") if rule.get("planning_amount_mode") not in {"0", None, ""} else rule.get("budget_amount_mode", "abs")
        rule["count_in_plan"] = True
        if int(selected.get("count") or 0) == 1 and int(selected.get("months_seen") or 0) == 1:
            rule["manual_recurring_confirmed"] = True
    elif plan_behavior == "Учитывать только в этом месяце":
        rule["planning_amount_mode"] = "0"
        rule["count_in_plan"] = False
        rule["plan_exclusion_reason"] = "Разовая операция учтена только в факте месяца"
    else:
        rule["planning_amount_mode"] = "0"
        rule["count_in_plan"] = False
    return rule


def rule_scope_label(scope: str) -> str:
    return {
        "single_operation": "Только к этой операции",
        "current_month_similar": "Ко всем похожим операциям этого месяца",
        "recurring_rule": "Сделать постоянным правилом",
        "global_person_rule": "Сделать постоянным правилом для человека",
    }.get(scope, scope)


def rule_summary(anchor: str, scenario: str, category: str, rule_scope: str, plan_behavior: str, report_month: str | None) -> str:
    month_text = month_label(report_month) if report_month else "выбранном месяце"
    if scenario in {"Перевод между своими счетами", "Проектный оборот", "Не учитывать", "Я дал в долг", "Я вернул долг", "Мне вернули долг", "Я занял деньги"}:
        return "Эти операции не попадут в личные доходы, расходы и постоянный план."
    if scenario == "Компенсация расходов":
        scope_text = "этот перевод" if rule_scope == "single_operation" else f"похожие переводы от {anchor}"
        return f"{scope_text} будут считаться компенсацией и уменьшать категорию “{category}”."
    if scenario == "Личный доход":
        return f"Поступление будет учтено как личный доход в категории “{category}”."
    if rule_scope == "single_operation":
        return f"Эта операция будет учтена как расход в категории “{category}” только в {month_text}."
    if plan_behavior == "Учитывать как постоянную статью":
        return f"Все похожие операции “{anchor}” будут считаться постоянным расходом в категории “{category}”."
    return f"Похожие операции будут учтены в факте месяца, но не попадут в постоянный план."


def build_income_rule_from_scenario(anchor: str, direction: str, scenario: str, category: str, custom: dict | None = None) -> dict:
    direction = infer_anchor_direction(anchor) or direction
    base = {
        "id": f"plan_{uuid.uuid4().hex[:10]}",
        "enabled": True,
        "match_contains_any": [anchor],
        "direction": direction,
        "scenario": "",
        "operation_type": "Проверить",
        "budget_category": "Прочее / проверить",
        "plan_category": "Не учитывать",
        "budget_amount_mode": "0",
        "planning_amount_mode": "0",
        "count_in_budget": False,
        "count_in_plan": False,
    }
    if scenario == "Личный доход":
        base.update(
            scenario="personal_income",
            operation_type="Личный доход",
            budget_category=category,
            plan_category="Не учитывать",
            budget_amount_mode="abs",
            planning_amount_mode="0",
            count_in_budget=True,
            count_in_plan=False,
        )
    elif scenario == "Компенсация расходов":
        base.update(
            scenario="compensation",
            operation_type="Компенсация совместных расходов",
            budget_category=category,
            plan_category=category,
            budget_amount_mode="-abs",
            planning_amount_mode="-abs",
            count_in_budget=True,
            count_in_plan=True,
        )
    elif scenario == "Возврат долга":
        base.update(scenario="loan_return", operation_type="Возврат займа", budget_category="Не учитывать")
    elif scenario == "Перевод между своими счетами":
        base.update(scenario="internal_transfer", operation_type="Внутренний перевод", budget_category="Не учитывать")
    elif scenario == "Проектный оборот":
        base.update(scenario="project_turnover", operation_type="Проектный оборот", budget_category="Не учитывать")
    elif scenario == "Не учитывать":
        base.update(scenario="ignore_in_plan", operation_type="Не учитывать", budget_category="Не учитывать")
    elif custom:
        base.update(
            scenario="custom_income",
            operation_type=custom["operation_type"],
            budget_category=custom["budget_category"],
            plan_category=custom["plan_category"],
            budget_amount_mode=custom["budget_amount_mode"],
            planning_amount_mode=custom["planning_amount_mode"],
            count_in_budget=custom["count_in_budget"],
            count_in_plan=custom["count_in_plan"],
        )
    return base


def render_candidate_rule_form(
    profile: dict,
    candidates: pd.DataFrame,
    direction_kind: str,
    report_month: str | None,
) -> None:
    if candidates.empty:
        return
    prefix = make_widget_key("cleanup_rule", profile["id"], direction_kind, report_month, len(candidates))
    anchor = st.selectbox(
        "Операция / человек / merchant",
        candidates["anchor"].tolist(),
        key=make_widget_key(prefix, "anchor"),
    )
    selected = candidates[candidates["anchor"] == anchor].iloc[0]
    default_scope = default_rule_scope_for_candidate(selected)
    scope_options = ["single_operation", "current_month_similar", "recurring_rule"]
    if default_scope == "recurring_rule":
        st.caption("Похоже на повторяющуюся операцию. Можно сделать постоянным правилом.")
    else:
        st.warning("Эта операция встретилась в истории один раз. Если сделать её постоянной, план месяца может быть завышен.")

    if direction_kind == "expense":
        scenario = st.radio(
            "Что это за списание?",
            [
                "Обычный расход",
                "Совместная покупка",
                "Подарок",
                "Я дал в долг",
                "Я вернул долг",
                "Перевод между своими счетами",
                "Проектный оборот",
                "Не учитывать",
                "Другое",
            ],
            key=make_widget_key(prefix, "scenario"),
        )
        category = "Прочее / проверить"
        custom = None
        if scenario == "Обычный расход":
            category = st.selectbox("Категория расхода", expense_categories(profile), key=make_widget_key(prefix, "expense_category"))
        elif scenario == "Совместная покупка":
            shared_categories = ["Жильё", "Продукты / супермаркеты", "Кафе / доставка / рестораны", "Документы / визы", "Путешествия", "Здоровье / аптеки", "Подарки / семья", "Прочее / проверить"]
            category = st.selectbox("Категория расхода", [item for item in shared_categories if item in expense_categories(profile)] or shared_categories, key=make_widget_key(prefix, "shared_category"))
            st.caption("Если позже придёт компенсация, она уменьшит эту категорию.")
        elif scenario == "Подарок":
            category = "Подарки / семья" if "Подарки / семья" in expense_categories(profile) else expense_categories(profile)[0]
            st.caption(f"Категория: {category}. Подарок попадёт в факт месяца, но не станет постоянной статьёй плана.")
        elif scenario == "Перевод между своими счетами":
            st.caption("Эти операции не будут считаться расходом или доходом.")
        elif scenario == "Проектный оборот":
            st.caption("Операции будут исключены из личного бюджета.")
        elif scenario in {"Я дал в долг", "Я вернул долг"}:
            st.caption("Долги пока не входят в личный бюджет и постоянный план.")
        plan_behavior_options = ["Учитывать только в этом месяце", "Учитывать как постоянную статью", "Не учитывать в плане"]
        default_behavior = default_plan_behavior_for_candidate(selected, scenario)
        if scenario in {"Подарок", "Я дал в долг", "Я вернул долг", "Перевод между своими счетами", "Проектный оборот", "Не учитывать"}:
            default_behavior = "Не учитывать в плане"
        plan_behavior = st.selectbox(
            "Как учитывать в плане?",
            plan_behavior_options,
            index=plan_behavior_options.index(default_behavior) if default_behavior in plan_behavior_options else 0,
            key=make_widget_key(prefix, "plan_behavior"),
        )
        if plan_behavior == "Учитывать как постоянную статью" and default_scope == "single_operation":
            st.warning("Эта операция встретилась в истории только один раз. Если добавить её как постоянную, месячный план может быть завышен.")
        with st.expander("Расширенная настройка", expanded=False):
            st.caption("Этот блок нужен для ручной технической настройки. В обычном режиме его лучше не использовать.")
            if scenario == "Другое":
                custom = {
                    "operation_type": st.selectbox("Тип операции", default_operation_types(), key=make_widget_key(prefix, "custom_type")),
                    "budget_category": st.selectbox("Категория для факта месяца", expense_categories(profile), key=make_widget_key(prefix, "custom_budget_category")),
                    "plan_category": st.selectbox("Категория для плана", expense_categories(profile), key=make_widget_key(prefix, "custom_plan_category")),
                    "budget_amount_mode": st.selectbox("Как влияет на факт", ["abs", "-abs", "0", "signed"], key=make_widget_key(prefix, "budget_mode")),
                    "planning_amount_mode": st.selectbox("Как влияет на план", ["abs", "-abs", "0", "signed"], key=make_widget_key(prefix, "planning_mode")),
                    "count_in_budget": st.checkbox("Учитывать в факте месяца", value=True, key=make_widget_key(prefix, "count_budget")),
                    "count_in_plan": st.checkbox("Учитывать в плане", value=False, key=make_widget_key(prefix, "count_plan")),
                }
        rule_scope = st.radio(
            "К чему применить?",
            scope_options,
            index=scope_options.index(default_scope),
            format_func=rule_scope_label,
            key=make_widget_key(prefix, "scope"),
        )
        if scenario == "Обычный расход":
            build_scenario = "Регулярный расход" if plan_behavior == "Учитывать как постоянную статью" else "Добавить в план только вручную"
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], build_scenario, category, custom)
        elif scenario == "Совместная покупка":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Добавить в план только вручную", category, custom)
        elif scenario == "Подарок":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Добавить в план только вручную", category, custom)
        elif scenario == "Я дал в долг":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Долг / заём", category, {"debt_type": "Заём выдан"})
        elif scenario == "Я вернул долг":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Долг / заём", category, {"debt_type": "Возврат займа"})
        elif scenario == "Перевод между своими счетами":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Перевод между своими счетами", "Не учитывать")
        elif scenario == "Проектный оборот":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Проектный оборот", "Не учитывать")
        elif scenario == "Не учитывать":
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Не учитывать в плане", "Не учитывать")
        else:
            rule = build_plan_rule_from_scenario(anchor, selected["direction"], "Другое / настроить вручную", category, custom)
        rule = apply_plan_behavior(rule, plan_behavior, selected)
    else:
        scenario = st.radio(
            "Что это за поступление?",
            [
                "Личный доход",
                "Компенсация расходов",
                "Мне вернули долг",
                "Я занял деньги",
                "Перевод между своими счетами",
                "Проектный оборот",
                "Не учитывать",
                "Другое",
            ],
            key=make_widget_key(prefix, "scenario"),
        )
        category = "Прочий личный доход"
        custom = None
        if scenario == "Личный доход":
            category = st.selectbox("Категория дохода", income_categories(profile), key=make_widget_key(prefix, "income_category"))
        elif scenario == "Компенсация расходов":
            shared_categories = ["Жильё", "Продукты / супермаркеты", "Кафе / доставка / рестораны", "Документы / визы", "Путешествия", "Здоровье / аптеки", "Подарки / семья", "Прочее / проверить"]
            category = st.selectbox("Какую категорию уменьшает?", [item for item in shared_categories if item in expense_categories(profile)] or shared_categories, key=make_widget_key(prefix, "comp_category"))
            st.caption("Компенсация не считается доходом. Она уменьшает расход выбранной категории.")
        plan_behavior_options = ["Учитывать только в этом месяце", "Учитывать как постоянную статью", "Не учитывать в плане"]
        default_behavior = "Не учитывать в плане" if scenario not in {"Компенсация расходов"} else default_plan_behavior_for_candidate(selected, scenario)
        plan_behavior = st.selectbox(
            "Как учитывать в плане?",
            plan_behavior_options,
            index=plan_behavior_options.index(default_behavior),
            key=make_widget_key(prefix, "plan_behavior"),
        )
        with st.expander("Расширенная настройка", expanded=False):
            st.caption("Этот блок нужен для ручной технической настройки. В обычном режиме его лучше не использовать.")
            if scenario == "Другое":
                custom = {
                    "operation_type": st.selectbox("Тип операции", default_operation_types(), key=make_widget_key(prefix, "custom_type")),
                    "budget_category": st.selectbox("Категория для факта месяца", income_categories(profile), key=make_widget_key(prefix, "custom_budget_category")),
                    "plan_category": st.selectbox("Категория для плана", ["Не учитывать", *expense_categories(profile)], key=make_widget_key(prefix, "custom_plan_category")),
                    "budget_amount_mode": st.selectbox("Как влияет на факт", ["abs", "-abs", "0", "signed"], key=make_widget_key(prefix, "budget_mode")),
                    "planning_amount_mode": st.selectbox("Как влияет на план", ["0", "-abs", "abs", "signed"], key=make_widget_key(prefix, "planning_mode")),
                    "count_in_budget": st.checkbox("Учитывать в факте месяца", value=True, key=make_widget_key(prefix, "count_budget")),
                    "count_in_plan": st.checkbox("Учитывать в плане", value=False, key=make_widget_key(prefix, "count_plan")),
                }
        rule_scope = st.radio(
            "К чему применить?",
            scope_options,
            index=scope_options.index(default_scope),
            format_func=rule_scope_label,
            key=make_widget_key(prefix, "scope"),
        )
        if scenario == "Личный доход":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Личный доход", category, custom)
        elif scenario == "Компенсация расходов":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Компенсация расходов", category, custom)
            rule = apply_plan_behavior(rule, plan_behavior, selected)
        elif scenario == "Мне вернули долг":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Возврат долга", "Не учитывать")
        elif scenario == "Я занял деньги":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Возврат долга", "Не учитывать")
            rule.update(operation_type="Заём получен", scenario="borrowed_money")
        elif scenario == "Перевод между своими счетами":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Перевод между своими счетами", "Не учитывать")
        elif scenario == "Проектный оборот":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Проектный оборот", "Не учитывать")
        elif scenario == "Не учитывать":
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Не учитывать", "Не учитывать")
        else:
            rule = build_income_rule_from_scenario(anchor, selected["direction"], "Другое / настроить вручную", category, custom)
    rule = apply_rule_scope(rule, selected, rule_scope, report_month)
    st.info(rule_summary(anchor, scenario, category, rule_scope, locals().get("plan_behavior", "Не учитывать в плане"), report_month))
    button_label = {
        "single_operation": "Сохранить для этой операции",
        "current_month_similar": "Сохранить для похожих операций месяца",
        "recurring_rule": "Сохранить как постоянное правило",
    }.get(rule_scope, "Сохранить правило")
    if st.button(button_label, key=make_widget_key(prefix, "create")):
        append_plan_rule(profile["id"], rule)
        stats = reclassify_profile_operations(profile["id"])
        st.success(f"Правило сохранено. Пересчитано операций: {stats['changed']}.")
        st.rerun()


def render_cleanup_page(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, report_month: str | None) -> None:
    render_user_journey(history, operations, profile, "Очистка операций")
    if not report_month or history.empty:
        st.info("Сначала загрузите историю. После импорта здесь появятся группы операций для разбора.")
        return
    candidates = get_plan_review_candidates_from_operations(history, report_month, 6, profile)
    income_candidates = get_income_review_candidates_from_operations(history, report_month, 6, profile)
    important = candidates[candidates["importance_level"].isin(["important", "oneoff_large"])] if not candidates.empty else pd.DataFrame()
    minor = candidates[candidates["importance_level"] == "minor_oneoff"] if not candidates.empty else pd.DataFrame()
    important_income = income_candidates[income_candidates["importance_level"] == "important"] if not income_candidates.empty else pd.DataFrame()
    minor_income = income_candidates[income_candidates["importance_level"] == "minor_oneoff"] if not income_candidates.empty else pd.DataFrame()

    st.subheader("Регулярные переводы и операции для уточнения")
    st.caption("Разберите группы, которые реально влияют на план. Мелкие разовые операции спрятаны ниже.")
    if important.empty:
        st.success("Важных списаний для разбора сейчас нет.")
    else:
        st.dataframe(display_plan_candidates(important), use_container_width=True, hide_index=True)
        oneoff_large = important[important.get("expense_nature", pd.Series(dtype=str)) == "oneoff_large"] if "expense_nature" in important.columns else pd.DataFrame()
        if not oneoff_large.empty:
            st.subheader("Разовые крупные операции")
            st.dataframe(
                pd.DataFrame(
                    {
                        "Операция": oneoff_large["anchor"],
                        "Сумма": oneoff_large["total_sum"],
                        "Дата": "",
                        "Категория": "на проверку",
                        "Включать в этот месяц?": "решить вручную",
                        "Делать постоянной?": "только после подтверждения",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Создать правило для списаний", expanded=True):
            render_candidate_rule_form(profile, important, "expense", report_month)
    if not minor.empty:
        with st.expander(f"Мелкие разовые операции: {len(minor)} на {money(float(minor['total_sum'].sum()))}"):
            st.caption("Эти операции не участвуют в автоплане. Они останутся в проверке месяца, если потребуется.")
            st.dataframe(display_hidden_candidates(minor), use_container_width=True, hide_index=True)

    st.subheader("Поступления")
    if important_income.empty:
        st.success("Важных поступлений для разбора сейчас нет.")
    else:
        st.dataframe(display_plan_candidates(important_income), use_container_width=True, hide_index=True)
        with st.expander("Создать правило для поступлений", expanded=True):
            render_candidate_rule_form(profile, important_income, "income", report_month)
    if not minor_income.empty:
        with st.expander(f"Мелкие разовые поступления: {len(minor_income)} на {money(float(minor_income['total_sum'].sum()))}"):
            st.caption("Эти операции не участвуют в доходном плане. Они останутся в проверке месяца, если потребуется.")
            st.dataframe(display_hidden_candidates(minor_income), use_container_width=True, hide_index=True)

    st.subheader("Операции текущего месяца на проверку")
    editable_review(profile, operations, key_prefix="cleanup_review")


def render_simplified_plan_tab(profile: dict, history: pd.DataFrame, report_month: str | None) -> None:
    render_user_journey(history, pd.DataFrame(), profile, "План месяца")
    if not report_month:
        st.info("Сначала импортируйте операции, чтобы выбрать месяц отчёта.")
        return
    default_history_months = 6
    quality = plan_coverage_score(history, report_month, default_history_months, profile)
    raw_preview = build_raw_auto_plan_from_operations(history, report_month, default_history_months, "median", 0, 500, profile)
    clean_preview = build_auto_expense_plan(history, report_month, default_history_months, "median", 0, 500, profile)
    raw_limit = float(raw_preview["suggested_plan"].sum()) if not raw_preview.empty else 0.0
    clean_limit = float(clean_preview["suggested_plan"].sum()) if not clean_preview.empty else 0.0
    raw_unparsed_transfers = category_sum(raw_preview, {"Неразобранные переводы / проверить", "Переводы, которые нужно уточнить"})
    raw_cash = category_sum(raw_preview, {"Наличные / проверить"})
    candidates = get_plan_review_candidates_from_operations(history, report_month, default_history_months, profile)
    minor_candidates = candidates[candidates["importance_level"] == "minor_oneoff"] if not candidates.empty else pd.DataFrame()

    render_metric_grid(
        [
            {"label": "Рекомендуемый план месяца", "value": money(raw_limit)},
            {"label": "Готовая часть", "value": money(clean_limit)},
            {"label": "Требует разметки", "value": money(raw_unparsed_transfers), "status": "warn" if raw_unparsed_transfers else "good"},
            {"label": "Текущий принятый план", "value": money(float(profile.get("monthly_limit") or 0))},
        ]
    )
    render_attention_card(
        "Рекомендация",
        "Сейчас план можно принять как предварительный. Если есть операции, которые нужно уточнить, после очистки план станет точнее.",
        "warn" if raw_unparsed_transfers else "good",
    )
    if raw_unparsed_transfers:
        st.warning("В плане есть операции, которые лучше разобрать на странице “Очистка”. План можно принять, но категории стоит уточнить.")

    render_manual_plan_editor(profile)
    st.divider()

    st.subheader("Рекомендуемый план")
    plan_mode = st.radio(
        "Режим плана",
        ["План с неразобранными операциями по массиву", "План по очищенным данным"],
        horizontal=True,
        key=make_widget_key("simple_auto_plan_mode", profile["id"], report_month),
    )
    col1, col2, col3, col4 = st.columns(4)
    history_months = col1.selectbox("Период истории", [3, 6, 12], index=1, key=make_widget_key("simple_auto_plan_history", profile["id"], report_month))
    strategy_label = col2.selectbox("Стратегия", ["медиана", "p75"], key=make_widget_key("simple_auto_plan_strategy", profile["id"], report_month))
    buffer_percent = col3.selectbox("Запас", [0, 5, 10, 15], index=2, key=make_widget_key("simple_auto_plan_buffer", profile["id"], report_month))
    round_to = col4.selectbox("Округление", [100, 500, 1000], index=1, key=make_widget_key("simple_auto_plan_round", profile["id"], report_month))
    strategy = "p75" if strategy_label == "p75" else "median"
    history_months_used = previous_full_months(report_month, history_months)
    layered_summary, layered_recommended, layered_debug = build_layered_plan_from_operations(
        history,
        report_month,
        history_months,
        strategy,
        buffer_percent,
        round_to,
        profile,
    )
    write_layered_plan_debug(layered_debug)
    st.subheader("Нагрузка месяца по слоям")
    render_metric_grid(
        [
            {"label": "Базовый план жизни", "value": money(layered_summary.base_living_plan)},
            {"label": "Обязательства и кредиты", "value": money(layered_summary.obligations_plan), "status": "warn" if layered_summary.obligations_plan else None},
            {"label": "Требует разметки", "value": money(layered_summary.unresolved_plan), "status": "warn" if layered_summary.unresolved_plan else "good"},
            {"label": "Итого возможная нагрузка", "value": money(layered_summary.recommended_total), "status": "warn" if layered_summary.warnings else None},
        ]
    )
    st.caption(
        "Базовый план показывает обычные расходы. Обязательства — кредиты и обязательные платежи. "
        "Неразобранные операции включены отдельно, чтобы план не был занижен."
    )
    if layered_summary.warnings:
        st.warning("План предварительный. Перед использованием разберите крупные переводы и проверьте кредитные обязательства.")
        with st.expander("Предупреждения качества плана"):
            warning_labels = {
                "owner_mismatch_files": "Есть выписки с владельцем, отличающимся от профиля.",
                "credit_accounts_without_debt_plan": "Найдены кредитные счета, но обязательные платежи не включены в план.",
                "no_housing_detected": "Жильё не найдено в плане. Проверьте, не скрыт ли перевод за квартиру.",
                "high_unresolved_transfers": "В плане много неразобранных переводов.",
                "too_few_complete_months": "Мало полных месяцев для устойчивой медианы.",
                "plan_may_be_understated": "План может быть занижен: часть исходящих операций не попала в категории.",
                "incomplete_wallet_parsing": "Есть операции кошельков, которые требуют проверки.",
                "cash_withdrawals_not_configured": "Наличные включены отдельно и требуют настройки.",
            }
            for warning in layered_summary.warnings:
                st.write(f"- {warning_labels.get(warning, warning)}")
    if layered_summary.partial_months_excluded:
        st.caption(f"Неполные месяцы исключены из медианы: {', '.join(layered_summary.partial_months_excluded)}")
    rec_key = make_widget_key("simple_recommended_plan", profile["id"], report_month)
    mode_key = make_widget_key("simple_recommended_plan_mode", profile["id"], report_month)
    hist_key = make_widget_key("simple_recommended_plan_history", profile["id"], report_month)
    calc_a, calc_b = st.columns(2)
    if calc_a.button("Рассчитать план по слоям", key=make_widget_key("simple_calculate_layered", profile["id"], report_month, history_months)):
        st.session_state[rec_key] = layered_recommended
        st.session_state[mode_key] = "План по слоям"
        st.session_state[hist_key] = history_months_used
    if calc_b.button("Рассчитать чистый план", key=make_widget_key("simple_calculate_clean", profile["id"], report_month, history_months)):
        st.session_state[rec_key] = build_auto_expense_plan(history, report_month, history_months, strategy, buffer_percent, round_to, profile)
        st.session_state[mode_key] = "План по очищенным данным"
        st.session_state[hist_key] = history_months_used
    recommended = st.session_state.get(rec_key, pd.DataFrame())
    if recommended.empty:
        recommended = layered_recommended if plan_mode == "План с неразобранными операциями по массиву" else build_auto_expense_plan(history, report_month, history_months, strategy, buffer_percent, round_to, profile)
    totals = recommended_plan_totals(recommended)
    render_metric_grid(
        [
            {"label": "Рекомендуемый план месяца", "value": money(layered_summary.recommended_total if not layered_recommended.empty else totals["recommended_total"])},
            {"label": "Готовая часть", "value": money(totals["ready_total"])},
            {"label": "Требует разметки", "value": money(totals["needs_classification_total"]), "status": "warn" if totals["needs_classification_total"] else "good"},
            {"label": "Мало истории", "value": money(totals["low_history_total"]), "status": "warn" if totals["low_history_total"] else None},
        ]
    )
    if totals["needs_classification_total"] > 0:
        st.info("В план включены неразобранные операции. Сумма ближе к реальности, но категории нужно уточнить.")
    elif totals["recommended_total"] > 0:
        st.success("План построен по размеченным операциям.")
    st.dataframe(friendly_plan_table(recommended), use_container_width=True, hide_index=True)
    with st.expander("Подробности расчёта"):
        st.dataframe(recommended, use_container_width=True, hide_index=True)
    if st.button("Принять этот план", disabled=recommended.empty, key=make_widget_key("simple_accept_auto_plan", profile["id"], report_month)):
        recommended_mode = st.session_state.get(mode_key, plan_mode)
        accepted = recommended[recommended["layer"] != "Мелкие"].copy() if "layer" in recommended.columns else recommended.copy()
        profile["plan"] = dict(zip(accepted["budget_category"], accepted["suggested_plan"]))
        profile["monthly_limit"] = float(accepted["suggested_plan"].sum())
        profile["plan_source"] = "layered_plan" if recommended_mode in {"План по слоям", "План с неразобранными операциями по массиву"} else "clean_auto_plan"
        profile["plan_updated_at"] = datetime.now().isoformat(timespec="seconds")
        profile["plan_history_months_used"] = st.session_state.get(hist_key, history_months_used)
        profile["auto_plan_accepted"] = True
        save_profile(profile)
        write_plan_debug(profile, profile["plan_history_months_used"])
        st.success("План расходов сохранён.")
        st.rerun()

    st.subheader("План доходов")
    income_recommended = build_auto_income_plan(history, report_month, history_months, strategy)
    raw_income_recommended = build_raw_income_plan_from_operations(history, report_month, history_months, strategy, 0, round_to, profile)
    income_col_a, income_col_b = st.columns(2)
    with income_col_a:
        st.caption("Чистый план доходов")
        st.dataframe(income_recommended, use_container_width=True, hide_index=True)
    with income_col_b:
        st.caption("Неразобранные поступления")
        st.dataframe(raw_income_recommended, use_container_width=True, hide_index=True)


def render_plan_tab(profile: dict, history: pd.DataFrame, report_month: str | None) -> None:
    if not report_month:
        st.info("Сначала импортируйте операции, чтобы выбрать месяц отчёта.")
        return
    default_history_months = 6
    quality = plan_coverage_score(history, report_month, default_history_months, profile)
    raw_preview = build_raw_auto_plan_from_operations(
        history,
        report_month,
        default_history_months,
        "median",
        0,
        500,
        profile,
    )
    clean_preview = build_auto_expense_plan(
        history,
        report_month,
        default_history_months,
        "median",
        0,
        500,
        profile,
    )
    raw_limit = float(raw_preview["suggested_plan"].sum()) if not raw_preview.empty else 0.0
    clean_limit = float(clean_preview["suggested_plan"].sum()) if not clean_preview.empty else 0.0
    raw_unparsed_transfers = 0.0
    raw_cash = 0.0
    if not raw_preview.empty:
        raw_unparsed_transfers = float(
            raw_preview.loc[raw_preview["budget_category"] == "Переводы, которые нужно уточнить", "suggested_plan"].sum()
        )
        raw_cash = float(raw_preview.loc[raw_preview["budget_category"] == "Наличные / проверить", "suggested_plan"].sum())
    candidates = get_plan_review_candidates_from_operations(history, report_month, default_history_months, profile)
    income_candidates = get_income_review_candidates_from_operations(history, report_month, default_history_months, profile)
    important_candidates = candidates[candidates["importance_level"] == "important"] if not candidates.empty else pd.DataFrame()
    minor_candidates = candidates[candidates["importance_level"] == "minor_oneoff"] if not candidates.empty else pd.DataFrame()
    important_income_candidates = income_candidates[income_candidates["importance_level"] == "important"] if not income_candidates.empty else pd.DataFrame()
    minor_income_candidates = income_candidates[income_candidates["importance_level"] == "minor_oneoff"] if not income_candidates.empty else pd.DataFrame()
    st.subheader("Качество плана")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("План с неразобранными операциями", money(raw_limit))
    col_b.metric("План по очищенным данным", money(clean_limit))
    col_c.metric("Операции, которые нужно уточнить", money(raw_unparsed_transfers))
    col_d.metric("Доля понятных расходов", f"{quality['coverage']:.0%}")
    col_e, col_f, col_g = st.columns(3)
    col_e.metric("Текущий план месяца", money(float(profile.get("monthly_limit") or 0)))
    col_f.metric("Наличные", money(raw_cash))
    col_g.metric("Мелких разовых скрыто", len(minor_candidates))
    st.caption("План с неразобранными операциями включает неразобранные переводы, поэтому сумма ближе к реальности, но категории нужно уточнить.")
    st.caption("Покрытие показывает, какая часть регулярных расходов уже понятна сервису.")
    clean_col_a, clean_col_b = st.columns(2)
    if clean_col_a.button("Почистить дубли правил", key=make_widget_key("clean_plan_rules", profile["id"], report_month)):
        before_count = len(profile.get("plan_rules", []))
        cleaned = clean_duplicate_plan_rules(profile["id"])
        st.success(f"Дубли правил очищены: было {before_count}, осталось {len(cleaned)}.")
        st.rerun()
    if clean_col_b.button("Почистить некорректные правила", key=make_widget_key("clean_invalid_rules", profile["id"], report_month)):
        stats = clean_invalid_rules(profile["id"])
        st.success(f"Некорректные правила очищены. Merchant: {stats['merchant_removed']}, plan: {stats['plan_removed']}.")
        st.rerun()
    with st.expander("Диагностика исключённых операций"):
        prepared = prepare_planning_dataframe(history, profile)
        if prepared.empty:
            st.info("Операций для диагностики пока нет.")
        else:
            prepared = prepared.copy()
            prepared["operation_datetime"] = pd.to_datetime(prepared["operation_datetime"], errors="coerce")
            prepared["month"] = prepared["operation_datetime"].dt.to_period("M").astype(str)
            prepared = prepared[prepared["month"].isin(previous_full_months(report_month, default_history_months))]
            excluded = prepared[
                (prepared["count_in_plan"] == False)
                & prepared["operation_type"].isin(["Внутренний перевод", "Погашение кредита", "Проектный оборот", "Проектный расход", "Проектный приход", "Не учитывать", "Заём выдан", "Возврат займа"])
            ].copy()
            if excluded.empty:
                st.info("Исключённых из плана операций за выбранную историю нет.")
            else:
                excluded["group"] = excluded["operation_type"].replace(
                    {
                        "Внутренний перевод": "Внутренние переводы",
                        "Погашение кредита": "Погашения кредитов",
                        "Проектный оборот": "Проектные обороты",
                        "Проектный расход": "Проектные обороты",
                        "Проектный приход": "Проектные обороты",
                        "Не учитывать": "Не учитывать",
                        "Заём выдан": "Долги / займы",
                        "Возврат займа": "Долги / займы",
                    }
                )
                excluded_summary = excluded.groupby("group", as_index=False).agg(
                    count=("id", "count"),
                    amount=("bank_amount", lambda values: float(values.abs().sum())),
                )
                st.caption("Исключено из плана за выбранную историю")
                st.dataframe(excluded_summary, use_container_width=True, hide_index=True)
    if quality["coverage"] < 0.8:
        st.warning("План пока нельзя считать точным: часть регулярных переводов не разобрана.")
    if not important_candidates.empty:
        st.info(f"Чтобы план был точным, разберите {len(important_candidates)} важных повторяющихся операций. Мелкие разовые переводы скрыты.")
        st.dataframe(display_plan_candidates(important_candidates), use_container_width=True, hide_index=True)
        with st.expander("Диагностика кандидатов"):
            debug_columns = [
                "anchor",
                "direction",
                "has_active_rule",
                "matched_rule_id",
                "operation_type_after_reclassify",
                "classification_source",
                "needs_plan_review",
                "reason",
            ]
            st.dataframe(candidates[[column for column in debug_columns if column in candidates.columns]], use_container_width=True, hide_index=True)
        with st.expander("Создать правило для выбранной операции", expanded=True):
            plan_rule_key = make_widget_key("plan_rule", profile["id"], report_month, len(important_candidates))
            anchor = st.selectbox(
                "Операция / человек / merchant",
                important_candidates["anchor"].tolist(),
                key=make_widget_key(plan_rule_key, "anchor"),
            )
            selected_candidate = important_candidates[important_candidates["anchor"] == anchor].iloc[0]
            scenario = st.radio(
                "Что это за операция?",
                [
                    "Регулярный расход",
                    "Перевод между своими счетами",
                    "Долг / заём",
                    "Проектный оборот",
                    "Не учитывать в плане",
                    "Другое / настроить вручную",
                ],
                key=make_widget_key(plan_rule_key, "quick_choice"),
            )
            category = "Прочее / проверить"
            custom = None
            if scenario == "Регулярный расход":
                category = st.selectbox("Категория расхода", expense_categories(profile), key=make_widget_key(plan_rule_key, "regular_category"))
            elif scenario == "Долг / заём":
                debt_choice = st.radio(
                    "Тип долга",
                    ["Я дал в долг", "Мне вернули долг", "Я вернул долг", "Я занял"],
                    key=make_widget_key(plan_rule_key, "debt_choice"),
                )
                debt_map = {
                    "Я дал в долг": "Заём выдан",
                    "Мне вернули долг": "Возврат займа",
                    "Я вернул долг": "Возврат займа",
                    "Я занял": "Заём выдан",
                }
                custom = {"debt_type": debt_map[debt_choice]}
            elif scenario == "Другое / настроить вручную":
                custom = {
                    "operation_type": st.selectbox("operation_type", default_operation_types(), index=0, key=make_widget_key(plan_rule_key, "custom_type")),
                    "budget_category": st.selectbox("budget_category", expense_categories(profile), index=0, key=make_widget_key(plan_rule_key, "custom_budget_category")),
                    "plan_category": st.selectbox("plan_category", expense_categories(profile), index=0, key=make_widget_key(plan_rule_key, "custom_plan_category")),
                    "budget_amount_mode": st.selectbox("budget_amount_mode", ["abs", "-abs", "0", "signed"], index=0, key=make_widget_key(plan_rule_key, "budget_mode")),
                    "planning_amount_mode": st.selectbox("planning_amount_mode", ["abs", "-abs", "0", "signed"], index=0, key=make_widget_key(plan_rule_key, "planning_mode")),
                    "count_in_budget": st.checkbox("count_in_budget", value=True, key=make_widget_key(plan_rule_key, "count_budget")),
                    "count_in_plan": st.checkbox("count_in_plan", value=True, key=make_widget_key(plan_rule_key, "count_plan")),
                }
            if st.button("Создать правило для плана", key=make_widget_key(plan_rule_key, "create")):
                rule = build_plan_rule_from_scenario(anchor, selected_candidate["direction"], scenario, category, custom)
                append_plan_rule(profile["id"], rule)
                stats = reclassify_profile_operations(profile["id"])
                st.session_state["last_reclassification_stats"] = stats
                st.success(f"Правило создано. Обновлено операций: {stats['changed']}.")
                st.rerun()
    else:
        st.success("Важных повторяющихся операций, мешающих плану, не найдено.")
    if not minor_candidates.empty:
        with st.expander(f"Мелкие разовые расходы, скрытые из автоплана: {len(minor_candidates)} на {money(float(minor_candidates['total_sum'].sum()))}"):
            st.caption("Эти операции не участвуют в автоплане. Они останутся в проверке месяца, если потребуется.")
            st.dataframe(display_hidden_candidates(minor_candidates), use_container_width=True, hide_index=True)
    st.subheader("Разобрать поступления")
    if important_income_candidates.empty:
        st.success("Неразобранных повторяющихся поступлений для плана не найдено.")
    else:
        st.dataframe(display_plan_candidates(important_income_candidates), use_container_width=True, hide_index=True)
        with st.expander("Диагностика поступлений"):
            debug_columns = [
                "anchor",
                "direction",
                "has_active_rule",
                "matched_rule_id",
                "operation_type_after_reclassify",
                "classification_source",
                "needs_plan_review",
                "reason",
            ]
            st.dataframe(income_candidates[[column for column in debug_columns if column in income_candidates.columns]], use_container_width=True, hide_index=True)
        with st.expander("Создать правило для поступления", expanded=True):
            income_rule_key = make_widget_key("income_rule", profile["id"], report_month, len(important_income_candidates))
            income_anchor = st.selectbox(
                "Поступление / человек / merchant",
                important_income_candidates["anchor"].tolist(),
                key=make_widget_key(income_rule_key, "anchor"),
            )
            selected_income = important_income_candidates[important_income_candidates["anchor"] == income_anchor].iloc[0]
            income_scenario = st.radio(
                "Что это за поступление?",
                [
                    "Личный доход",
                    "Компенсация расходов",
                    "Возврат долга",
                    "Перевод между своими счетами",
                    "Проектный оборот",
                    "Не учитывать",
                    "Другое / настроить вручную",
                ],
                key=make_widget_key(income_rule_key, "scenario"),
            )
            income_category = "Прочий личный доход"
            income_custom = None
            if income_scenario == "Личный доход":
                income_category = st.selectbox("Категория дохода", income_categories(profile), key=make_widget_key(income_rule_key, "income_category"))
            elif income_scenario == "Компенсация расходов":
                income_category = st.selectbox("Какую категорию уменьшает?", expense_categories(profile), key=make_widget_key(income_rule_key, "comp_category"))
                st.caption("Компенсация не считается доходом. Она уменьшает расход выбранной категории.")
            elif income_scenario == "Другое / настроить вручную":
                income_custom = {
                    "operation_type": st.selectbox("operation_type", default_operation_types(), index=0, key=make_widget_key(income_rule_key, "custom_type")),
                    "budget_category": st.selectbox("budget_category", income_categories(profile), index=0, key=make_widget_key(income_rule_key, "custom_budget_category")),
                    "plan_category": st.selectbox("plan_category", income_categories(profile), index=0, key=make_widget_key(income_rule_key, "custom_plan_category")),
                    "budget_amount_mode": st.selectbox("budget_amount_mode", ["abs", "-abs", "0", "signed"], index=0, key=make_widget_key(income_rule_key, "budget_mode")),
                    "planning_amount_mode": st.selectbox("planning_amount_mode", ["abs", "-abs", "0", "signed"], index=2, key=make_widget_key(income_rule_key, "planning_mode")),
                    "count_in_budget": st.checkbox("count_in_budget", value=True, key=make_widget_key(income_rule_key, "count_budget")),
                    "count_in_plan": st.checkbox("count_in_plan", value=False, key=make_widget_key(income_rule_key, "count_plan")),
                }
            if st.button("Создать правило для поступления", key=make_widget_key(income_rule_key, "create")):
                rule = build_income_rule_from_scenario(
                    income_anchor,
                    selected_income["direction"],
                    income_scenario,
                    income_category,
                    income_custom,
                )
                append_plan_rule(profile["id"], rule)
                stats = reclassify_profile_operations(profile["id"])
                st.session_state["last_reclassification_stats"] = stats
                st.success(f"Правило создано. Обновлено операций: {stats['changed']}.")
                st.rerun()
    if not minor_income_candidates.empty:
        with st.expander(f"Мелкие разовые поступления, скрытые из доходного плана: {len(minor_income_candidates)} на {money(float(minor_income_candidates['total_sum'].sum()))}"):
            st.caption("Эти операции не участвуют в автоплане. Они останутся в проверке месяца, если потребуется.")
            st.dataframe(display_hidden_candidates(minor_income_candidates), use_container_width=True, hide_index=True)
    st.subheader("Сформировать план по истории")
    plan_mode = st.radio(
        "Режим плана",
        ["План с неразобранными операциями по массиву", "План по очищенным данным"],
        horizontal=True,
        key=make_widget_key("auto_plan_mode", profile["id"], report_month),
    )
    col1, col2, col3, col4 = st.columns(4)
    history_months = col1.selectbox("Период истории", [3, 6, 12], index=1, key=make_widget_key("auto_plan_history", profile["id"], report_month))
    strategy_label = col2.selectbox("Стратегия", ["медиана", "p75"], key=make_widget_key("auto_plan_strategy", profile["id"], report_month))
    buffer_percent = col3.selectbox("Запас", [0, 5, 10, 15], index=2, key=make_widget_key("auto_plan_buffer", profile["id"], report_month))
    round_to = col4.selectbox("Округление", [100, 500, 1000], index=1, key=make_widget_key("auto_plan_round", profile["id"], report_month))
    strategy = "p75" if strategy_label == "p75" else "median"
    history_months_used = previous_full_months(report_month, history_months)
    if st.button("Рассчитать автоплан", key=make_widget_key("calculate_auto_plan", profile["id"], report_month, history_months)):
        if plan_mode == "План с неразобранными операциями по массиву":
            recommended_plan = build_raw_auto_plan_from_operations(
                history,
                report_month,
                history_months,
                strategy,
                buffer_percent,
                round_to,
                profile,
            )
        else:
            recommended_plan = build_auto_expense_plan(
                history,
                report_month,
                history_months,
                strategy,
                buffer_percent,
                round_to,
                profile,
            )
        st.session_state[make_widget_key("recommended_plan", profile["id"], report_month)] = recommended_plan
        st.session_state[make_widget_key("recommended_plan_history", profile["id"], report_month)] = history_months_used
        st.session_state[make_widget_key("recommended_plan_mode", profile["id"], report_month)] = plan_mode
    recommended = st.session_state.get(
        make_widget_key("recommended_plan", profile["id"], report_month),
        pd.DataFrame(),
    )
    if recommended.empty:
        st.info("Нажмите “Рассчитать автоплан”, чтобы увидеть рекомендации.")
    available_history_months = set(history.get("operation_datetime", pd.Series(dtype=str)).astype(str).str[:7])
    enough_history = len([month for month in history_months_used if month in available_history_months]) >= 3
    if not enough_history:
        st.warning("Недостаточно истории для надёжного автоплана. Нужно минимум 3 полных месяца.")
    st.subheader("Рекомендуемый план")
    totals = recommended_plan_totals(recommended)
    total_col_a, total_col_b, total_col_c, total_col_d = st.columns(4)
    total_col_a.metric("Рекомендуемый план месяца", money(totals["recommended_total"]))
    total_col_b.metric("Готовая часть", money(totals["ready_total"]))
    total_col_c.metric("Требует разметки", money(totals["needs_classification_total"]))
    total_col_d.metric("Мало истории", money(totals["low_history_total"]))
    if totals["needs_classification_total"] > 0:
        st.info("В план включены неразобранные операции. Сумма ближе к реальности, но категории нужно уточнить.")
    if totals["low_history_total"] > 0:
        st.warning("По части категорий мало истории. Проверьте суммы вручную.")
    if totals["recommended_total"] > 0 and totals["recommended_total"] == totals["ready_total"]:
        st.success("План построен по размеченным операциям.")
    st.dataframe(display_recommended_plan(recommended), use_container_width=True, hide_index=True)
    if not recommended.empty:
        with st.expander("Подробности расчёта"):
            st.dataframe(recommended, use_container_width=True, hide_index=True)
    recommended_mode = st.session_state.get(make_widget_key("recommended_plan_mode", profile["id"], report_month), plan_mode)
    accept_disabled = recommended.empty or not enough_history or (
        recommended_mode == "План по очищенным данным" and quality["coverage"] < 0.8
    )
    if accept_disabled and recommended_mode == "План по очищенным данным" and quality["coverage"] < 0.8:
        st.caption("План нельзя принять автоматически, пока регулярные переводы не разобраны.")
    if st.button("Принять этот план", disabled=accept_disabled, key=make_widget_key("accept_auto_plan", profile["id"], report_month)):
        profile["plan"] = dict(zip(recommended["budget_category"], recommended["suggested_plan"]))
        profile["monthly_limit"] = float(recommended["suggested_plan"].sum())
        profile["plan_source"] = "raw_auto_plan" if recommended_mode == "План с неразобранными операциями по массиву" else "clean_auto_plan"
        profile["plan_updated_at"] = datetime.now().isoformat(timespec="seconds")
        profile["plan_history_months_used"] = st.session_state.get(
            make_widget_key("recommended_plan_history", profile["id"], report_month),
            history_months_used,
        )
        profile["auto_plan_accepted"] = True
        save_profile(profile)
        write_plan_debug(profile, profile["plan_history_months_used"])
        st.success("План расходов сохранён.")
        st.rerun()
    st.subheader("План доходов")
    income_recommended = build_auto_income_plan(history, report_month, history_months, strategy)
    raw_income_recommended = build_raw_income_plan_from_operations(history, report_month, history_months, strategy, 0, round_to, profile)
    current_income_plan = profile.get("income_plan") or default_profile_template().get("income_plan", {})
    if not income_recommended.empty:
        income_recommended["manual_plan"] = income_recommended["income_category"].map(current_income_plan).fillna(
            income_recommended["suggested_plan"]
        )
    income_col_a, income_col_b = st.columns(2)
    with income_col_a:
        st.caption("Чистый план доходов")
        st.dataframe(income_recommended, use_container_width=True, hide_index=True)
    with income_col_b:
        st.caption("План с неразобранными операциями поступлений")
        st.dataframe(raw_income_recommended, use_container_width=True, hide_index=True)


def render_dictionary_tab(profile: dict, operations: pd.DataFrame) -> None:
    st.subheader("Правила пользователя")
    merchant_rules = profile.get("merchant_rules", []) or []
    plan_rules = profile.get("plan_rules", []) or []
    human_rules = []
    for rule in merchant_rules + plan_rules:
        anchors = rule.get("match_contains_any") or rule.get("contains_any") or []
        anchor = rule.get("merchant_anchor") or rule.get("person_anchor") or (", ".join(anchors) if anchors else "")
        human_rules.append(
            {
                "человек / merchant": anchor,
                "сценарий": rule.get("scenario") or rule.get("operation_type") or "",
                "категория": rule.get("budget_category") or rule.get("plan_category") or "",
                "направление": direction_label(rule.get("direction", "expense")),
            }
        )
    if human_rules:
        st.dataframe(pd.DataFrame(human_rules), use_container_width=True, hide_index=True)
    else:
        st.info("Личных правил пока нет. Их можно создать на странице “Очистка”.")

    st.subheader("Глобальные правила")
    global_rules = pd.read_json("config/global_merchant_rules.json")
    global_display = global_rules.copy()
    if "contains_any" in global_display.columns:
        global_display["merchant"] = global_display["contains_any"].apply(lambda value: ", ".join(value) if isinstance(value, list) else value)
    global_columns = [column for column in ["merchant", "budget_category", "operation_type", "direction"] if column in global_display.columns]
    st.dataframe(global_display[global_columns], use_container_width=True, hide_index=True)

    st.subheader("Повторяющиеся операции без правила")
    if operations.empty:
        review = pd.DataFrame()
    else:
        low_confidence = operations["confidence"] < 0.85 if "confidence" in operations.columns else True
        review = operations[(operations["needs_review"] == True) | low_confidence]
    recurring = recurring_operations_summary(review)
    st.dataframe(recurring, use_container_width=True, hide_index=True)
    if not recurring.empty:
        merchant_options = recurring["merchant"].tolist()
        merchant = st.selectbox(
            "Якорь / merchant",
            merchant_options,
            key=make_widget_key("dictionary_merchant_anchor", profile["id"], len(merchant_options)),
        )
        merchant_key = make_widget_key("dictionary_merchant", profile["id"], merchant)
        operation_type = st.selectbox(
            "Что это?",
            ["Личный расход", "Внутренний перевод", "Проектный оборот", "Не учитывать", "Другое / расширенная настройка"],
            index=0,
            key=make_widget_key(merchant_key, "operation_type"),
        )
        category_options = expense_categories(profile) if operation_type == "Личный расход" else ["Не учитывать"]
        if operation_type == "Другое / расширенная настройка":
            operation_type = st.selectbox("Тип операции", default_operation_types(), key=make_widget_key(merchant_key, "technical_type"))
            category_options = default_categories()
        category = st.selectbox("Категория", category_options, key=make_widget_key(merchant_key, "category"))
        inferred_direction = infer_anchor_direction(merchant)
        direction_options = [inferred_direction] if inferred_direction else ["expense", "income"]
        direction = st.selectbox(
            "Направление",
            direction_options,
            index=0,
            key=make_widget_key(merchant_key, "direction"),
        )
        if inferred_direction:
            st.caption(f"Направление определено по тексту перевода: {direction_label(inferred_direction)}.")
        use_in_budget = st.checkbox(
            "Учитывать в личном бюджете",
            value=operation_type in {"Личный расход", "Личный доход"},
            key=make_widget_key(merchant_key, "use_in_budget"),
        )
        if st.button("Создать правило", key=make_widget_key(merchant_key, "create_rule")):
            direction = infer_anchor_direction(merchant) or direction
            rule = {
                "id": f"merchant_{uuid.uuid4().hex[:10]}",
                "enabled": True,
                "merchant_anchor": merchant,
                "contains_any": [merchant],
                "contains_all": [],
                "bank": None,
                "direction": direction,
                "operation_type": operation_type,
                "budget_category": category,
                "personal_amount_mode": "abs" if use_in_budget and operation_type in {"Личный расход", "Личный доход"} else "0",
                "confidence": 0.95,
                "comment": "Создано из справочника",
            }
            append_merchant_rule(profile["id"], rule)
            st.success("Правило добавлено в личный справочник.")
            st.rerun()
    st.subheader("Повторяющиеся переводы людям")
    people = recurring_people_summary(review)
    st.dataframe(people, use_container_width=True, hide_index=True)
    if not people.empty:
        person_options = people["person"].tolist()
        person = st.selectbox(
            "Человек",
            person_options,
            key=make_widget_key("dictionary_person_anchor", profile["id"], len(person_options)),
        )
        person_key = make_widget_key("dictionary_person", profile["id"], person)
        person_type = st.selectbox(
            "Что это?",
            ["Компенсация совместных расходов", "Внутренний перевод", "Возврат займа", "Заём выдан", "Не учитывать", "Другое / расширенная настройка"],
            index=0,
            key=make_widget_key(person_key, "operation_type"),
        )
        if person_type == "Компенсация совместных расходов":
            person_category_options = expense_categories(profile)
        elif person_type == "Другое / расширенная настройка":
            person_type = st.selectbox("Тип операции", default_operation_types(), key=make_widget_key(person_key, "technical_type"))
            person_category_options = default_categories()
        else:
            person_category_options = ["Не учитывать"]
        person_category = st.selectbox("Категория", person_category_options, key=make_widget_key(person_key, "category"))
        if st.button("Создать правило для человека", key=make_widget_key(person_key, "create_rule")):
            person_direction = infer_anchor_direction(person)
            mode = "-abs" if person_type == "Компенсация совместных расходов" else "0"
            if person_type in {"Личный расход", "Личный доход"}:
                mode = "abs"
            append_merchant_rule(
                profile["id"],
                {
                    "id": f"person_{uuid.uuid4().hex[:10]}",
                    "enabled": True,
                    "person_anchor": person,
                    "bank": None,
                    "direction": person_direction,
                    "operation_type": person_type,
                    "budget_category": person_category,
                    "personal_amount_mode": mode,
                    "confidence": 0.95,
                    "comment": "Создано для повторяющихся переводов",
                },
            )
            st.success("Правило для человека добавлено.")
            st.rerun()
    with st.expander("Технический JSON"):
        st.caption("Сырые структуры правил нужны для отладки, обычному пользователю они не обязательны.")
        st.dataframe(global_rules, use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(merchant_rules), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(plan_rules), use_container_width=True, hide_index=True)
    with st.expander("Raw categories банка, которые часто требуют проверки"):
        st.dataframe(unrecognized_summary(review), use_container_width=True, hide_index=True)


def render_rules_tab(profile: dict, operations: pd.DataFrame) -> None:
    st.subheader("Правила")
    st.caption("Здесь можно изменить решения, которые вы приняли во время очистки операций.")
    rules_df = rules_dataframe(profile, operations)
    if rules_df.empty:
        st.info("Пока нет личных правил. Создайте их на странице “Очистка”.")
    else:
        sections = {
            "Все правила": rules_df,
            "Правила расходов": rules_df[rules_df["Направление"] == "списание"],
            "Правила поступлений": rules_df[rules_df["Направление"] == "поступление"],
            "Внутренние переводы": rules_df[rules_df["Сценарий"] == "Перевод между своими счетами"],
            "Исключённые операции": rules_df[rules_df["Сценарий"] == "Не учитывать"],
            "Проектные обороты": rules_df[rules_df["Сценарий"] == "Проектный оборот"],
        }
        section_name = st.radio("Раздел", list(sections.keys()), horizontal=True, key=make_widget_key("rules_section", profile["id"]))
        user_df = sections[section_name].drop(columns=["source", "index", "id"], errors="ignore")
        st.dataframe(user_df, use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    if col_a.button("Применить правила заново", key=make_widget_key("rules_reclassify", profile["id"])):
        stats = reclassify_profile_operations(profile["id"])
        st.success(f"Правила применены. Пересчитано операций: {stats['changed']} из {stats['processed']}.")
        st.rerun()
    if col_b.button("Почистить дубли правил", key=make_widget_key("rules_clean_duplicates", profile["id"])):
        stats = clean_duplicate_rules(profile["id"])
        st.success(f"Удалено дублей: {stats['merchant_removed'] + stats['plan_removed']}.")
        st.rerun()

    if not rules_df.empty:
        options = [
            f"{row['Название / человек / merchant']} · {row['Направление']} · {row['Сценарий']}"
            for _, row in rules_df.iterrows()
        ]
        selected_label = st.selectbox("Выберите правило для изменения", options, key=make_widget_key("rules_select", profile["id"]))
        selected_row = rules_df.iloc[options.index(selected_label)]
        source = str(selected_row["source"])
        index = int(selected_row["index"])
        source_rules = profile.get("plan_rules", []) if source == "plan" else profile.get("merchant_rules", [])
        rule = dict(source_rules[index])
        anchor = rule_anchor(rule)
        with st.form(make_widget_key("rule_edit_form", profile["id"], source, index, anchor)):
            st.markdown(f"**{anchor or 'Правило'}**")
            enabled = st.checkbox("Правило активно", value=rule.get("enabled", True))
            inferred = infer_anchor_direction(anchor)
            direction_options = [inferred] if inferred else ["expense", "income"]
            current_direction = inferred or rule.get("direction", "expense")
            direction = st.selectbox(
                "Направление",
                direction_options,
                index=direction_options.index(current_direction) if current_direction in direction_options else 0,
                format_func=direction_label,
            )
            scenario_options = [
                "Регулярный расход",
                "Компенсация расходов",
                "Личный доход",
                "Перевод между своими счетами",
                "Долг / заём",
                "Проектный оборот",
                "Не учитывать",
                "Другое / расширенная настройка",
            ]
            current_scenario = scenario_label(rule)
            scenario = st.selectbox(
                "Сценарий",
                scenario_options,
                index=scenario_options.index(current_scenario) if current_scenario in scenario_options else 0,
            )
            if scenario == "Личный доход":
                category_options = income_categories(profile)
                label = "Категория дохода"
            elif scenario == "Компенсация расходов":
                category_options = expense_categories(profile)
                label = "Какую категорию уменьшает?"
                st.caption("Компенсация не считается доходом. Она уменьшает расход выбранной категории.")
            elif scenario == "Регулярный расход":
                category_options = expense_categories(profile)
                label = "Категория расхода"
            elif scenario == "Другое / расширенная настройка":
                operation_type = st.selectbox("Тип операции", default_operation_types(), index=0)
                category_options = expense_categories(profile) + income_categories(profile) + ["Не учитывать"]
                label = "Категория"
            else:
                category_options = ["Не учитывать", "Прочее / проверить"]
                label = "Категория"
            current_category = rule.get("budget_category") or rule.get("plan_category") or category_options[0]
            category = st.selectbox(label, category_options, index=category_options.index(current_category) if current_category in category_options else 0)
            submitted = st.form_submit_button("Сохранить правило")
        if submitted:
            if scenario == "Личный доход":
                updated = build_income_rule_from_scenario(anchor, direction, "Личный доход", category)
            elif scenario == "Компенсация расходов":
                updated = build_income_rule_from_scenario(anchor, direction, "Компенсация расходов", category)
            elif scenario == "Регулярный расход":
                updated = build_plan_rule_from_scenario(anchor, direction, "Регулярный расход", category)
            elif scenario == "Перевод между своими счетами":
                updated = build_plan_rule_from_scenario(anchor, direction, "Перевод между своими счетами", "Не учитывать")
            elif scenario == "Долг / заём":
                updated = build_plan_rule_from_scenario(anchor, direction, "Долг / заём", "Не учитывать", {"debt_type": rule.get("operation_type", "Заём выдан")})
            elif scenario == "Проектный оборот":
                updated = build_plan_rule_from_scenario(anchor, direction, "Проектный оборот", "Не учитывать")
            elif scenario == "Не учитывать":
                updated = build_plan_rule_from_scenario(anchor, direction, "Не учитывать в плане", "Не учитывать")
            else:
                updated = dict(rule)
                updated.update(operation_type=operation_type, budget_category=category)
            updated["id"] = rule.get("id") or updated.get("id")
            updated["enabled"] = enabled
            updated["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_rule_by_source(profile, source, index, updated)
            stats = reclassify_profile_operations(profile["id"])
            st.success(f"Правило обновлено. Пересчитано операций: {stats['changed']}.")
            st.rerun()

        col_disable, col_delete = st.columns(2)
        if col_disable.button("Выключить" if rule.get("enabled", True) else "Включить", key=make_widget_key("rule_toggle", profile["id"], source, index)):
            rule["enabled"] = not rule.get("enabled", True)
            rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_rule_by_source(profile, source, index, rule)
            stats = reclassify_profile_operations(profile["id"])
            st.success(f"Готово. Пересчитано операций: {stats['changed']}.")
            st.rerun()
        with col_delete:
            confirm = st.checkbox(
                f"Удалить правило, влияет на {int(selected_row['Операций'])} операций",
                key=make_widget_key("rule_delete_confirm", profile["id"], source, index),
            )
            if st.button("Удалить", disabled=not confirm, key=make_widget_key("rule_delete", profile["id"], source, index)):
                delete_rule_by_source(profile, source, index)
                stats = reclassify_profile_operations(profile["id"])
                st.success(f"Правило удалено. Пересчитано операций: {stats['changed']}.")
                st.rerun()

    with st.expander("Глобальные правила merchant"):
        global_rules = pd.read_json("config/global_merchant_rules.json")
        if "contains_any" in global_rules.columns:
            global_rules = global_rules.assign(merchant=global_rules["contains_any"].apply(lambda value: ", ".join(value) if isinstance(value, list) else value))
        columns = [column for column in ["merchant", "budget_category", "operation_type", "direction"] if column in global_rules.columns]
        st.dataframe(global_rules[columns], use_container_width=True, hide_index=True)
    render_unknown_merchant_candidates(profile)
    with st.expander("Кандидаты в общий справочник"):
        candidates = pd.DataFrame(storage.load_global_rule_candidates())
        if candidates.empty:
            st.caption("Кандидатов пока нет.")
        else:
            visible = candidates.drop(columns=["profile_ids"], errors="ignore")
            st.dataframe(visible, use_container_width=True, hide_index=True)


def render_profile_settings_tab(profile: dict) -> None:
    st.subheader("Данные профиля")
    with st.expander("Основные настройки", expanded=True):
        profile["name"] = st.text_input("Название профиля", value=profile.get("name", ""), key=make_widget_key("profile_name", profile["id"]))
        profile["manual_limit"] = st.number_input(
            "Ручной общий лимит, если нужен",
            min_value=0.0,
            value=float(profile.get("manual_limit") or profile.get("monthly_limit") or 0),
            step=1000.0,
            key=make_widget_key("profile_manual_limit", profile["id"]),
        )
        if st.button("Сохранить профиль", key=make_widget_key("save_profile_settings", profile["id"])):
            save_profile(profile)
            st.rerun()

    with st.expander("Мои счета и переводы"):
        st.caption("Эти данные помогают отличать переводы самому себе от доходов и расходов.")
        identity = profile.get("own_identity") or {"full_name": "", "name_aliases": [], "phones": [], "account_last4": [], "banks": []}
        identity["full_name"] = st.text_input("Ф.И.О.", value=identity.get("full_name", ""), key=make_widget_key("identity_full_name_page", profile["id"]))
        aliases_text = st.text_area("Варианты написания имени", value="\n".join(identity.get("name_aliases", [])), key=make_widget_key("identity_aliases_page", profile["id"]))
        phones_text = st.text_input("Телефоны", value=", ".join(identity.get("phones", [])), key=make_widget_key("identity_phones_page", profile["id"]))
        last4_text = st.text_input("Последние 4 цифры карт/счетов", value=", ".join(identity.get("account_last4", [])), key=make_widget_key("identity_last4_page", profile["id"]))
        banks_text = st.text_input("Банки и кошельки", value=", ".join(identity.get("banks", [])), key=make_widget_key("identity_banks_page", profile["id"]))
        if st.button("Сохранить мои данные", key=make_widget_key("save_identity_page", profile["id"])):
            profile["own_identity"] = {
                "full_name": identity["full_name"].strip(),
                "name_aliases": [item.strip() for item in aliases_text.splitlines() if item.strip()],
                "phones": [item.strip() for item in phones_text.split(",") if item.strip()],
                "account_last4": [item.strip() for item in last4_text.split(",") if item.strip()],
                "banks": [item.strip() for item in banks_text.split(",") if item.strip()],
            }
            save_profile(profile)
            st.rerun()

    with st.expander("Категории"):
        custom = load_custom_categories(profile["id"])
        col1, col2 = st.columns(2)
        kind = col1.selectbox("Тип категории", ["expense", "income"], format_func=lambda value: "Расход" if value == "expense" else "Доход", key=make_widget_key("custom_category_kind", profile["id"]))
        label = col2.text_input("Название новой категории", key=make_widget_key("custom_category_label", profile["id"]))
        group = st.text_input("Группа", value="Мои категории", key=make_widget_key("custom_category_group", profile["id"]))
        if st.button("+ Добавить свою категорию", disabled=not label.strip(), key=make_widget_key("add_custom_category", profile["id"])):
            custom.setdefault(kind, [])
            custom[kind].append(
                {
                    "id": f"custom_{uuid.uuid4().hex[:8]}",
                    "label": label.strip(),
                    "group": group.strip() or "Мои категории",
                    "default": False,
                    "active": True,
                }
            )
            save_custom_categories(profile["id"], custom)
            st.rerun()
        for category_kind, title in [("expense", "Расходные категории"), ("income", "Доходные категории")]:
            st.markdown(f"**{title}**")
            rows = custom.get(category_kind, [])
            if not rows:
                st.caption("Пользовательских категорий пока нет.")
            for idx, row in enumerate(rows):
                cols = st.columns([3, 2, 1])
                row["label"] = cols[0].text_input("Название", value=row.get("label", ""), key=make_widget_key("cat_label", profile["id"], category_kind, idx))
                row["group"] = cols[1].text_input("Группа", value=row.get("group", "Мои категории"), key=make_widget_key("cat_group", profile["id"], category_kind, idx))
                row["active"] = cols[2].checkbox("Показать", value=row.get("active", True), key=make_widget_key("cat_active", profile["id"], category_kind, idx))
        if st.button("Сохранить категории", key=make_widget_key("save_custom_categories", profile["id"])):
            save_custom_categories(profile["id"], custom)
            st.rerun()


def profile_identity_needs_attention(profile: dict) -> bool:
    identity = profile.get("own_identity") or {}
    return not bool(identity.get("full_name") and (identity.get("name_aliases") or identity.get("phones") or identity.get("account_last4")))


def render_profile_and_upload_page(profile: dict, history: pd.DataFrame, operations: pd.DataFrame, start_date: date, end_date: date) -> None:
    render_user_journey(history, operations, profile, "Профиль и загрузка")
    if profile_identity_needs_attention(profile):
        st.info("Заполните данные профиля, чтобы сервис мог отличать переводы самому себе от доходов и расходов.")
    render_profile_settings_tab(profile)
    st.divider()
    upload_pdf(profile, start_date, end_date)


def render_control_page(profile: dict, operations: pd.DataFrame, history: pd.DataFrame, plan: pd.DataFrame, report_month: str | None, start_date: date, end_date: date) -> None:
    latest_date = latest_operation_date(profile["id"])
    if operations.empty:
        if history.empty and st.session_state.get("has_uploaded_files"):
            st.info("PDF выбран. Нажмите “Импортировать и перейти к очистке”.")
        elif history.empty:
            st.info("Нет операций. Начните с раздела “Профиль и загрузка”.")
        else:
            st.info("В базе есть операции, но за выбранный период ничего не найдено. Проверьте месяц отчёта.")
    render_home_page(profile, operations, history, plan, report_month, start_date, end_date, latest_date)
    render_income_section(profile, operations)
    render_operation_reassignment_section(profile, operations)
    with st.expander("Список операций месяца"):
        st.dataframe(display_operations(operations), use_container_width=True, hide_index=True)
    with st.expander("Подробный план-факт"):
        st.dataframe(plan_fact(operations, plan), use_container_width=True, hide_index=True)


def render_diagnostics_tab(operations: pd.DataFrame) -> None:
    st.subheader("Источник плана")
    profile = st.session_state.get("_diagnostics_profile")
    if profile:
        plan = profile.get("plan", {}) or {}
        warnings = []
        plan_sum = sum(float(value or 0) for value in plan.values())
        if float(profile.get("monthly_limit") or 0) != plan_sum:
            warnings.append("monthly_limit не равен сумме категорий плана")
        if not profile.get("plan_source"):
            warnings.append("Источник плана не задан: это может быть старый сохранённый план")
        debug = write_plan_debug(profile, profile.get("plan_history_months_used", []), warnings)
        st.json(debug)
    st.subheader("Сводка raw_category")
    st.dataframe(raw_category_summary(operations), use_container_width=True, hide_index=True)
    st.subheader("Не распознано по категориям")
    st.dataframe(unrecognized_summary(operations), use_container_width=True, hide_index=True)
    st.subheader("Повторяющиеся операции")
    st.dataframe(recurring_operations_summary(operations), use_container_width=True, hide_index=True)
    st.subheader("Повторяющиеся люди")
    st.dataframe(recurring_people_summary(operations), use_container_width=True, hide_index=True)
    st.caption("Debug-файлы создаются только при BUDGET_DEBUG_EXPORTS=1 и проходят маскирование.")


def main() -> None:
    init_db()
    apply_app_style()
    st.markdown(
        """
        <div class="budget-hero">
            <h1>Личный бюджет по PDF</h1>
            <div class="budget-sub">PDF обрабатываются локально. В базу попадают операции, а не исходные файлы.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    profile = profile_selector()
    compact_new_profile_form()
    report_month, start_date, end_date = period_picker(profile["id"])
    operations = operations_df(profile["id"], start_date, end_date)
    history = operations_df(profile["id"])
    render_sidebar(profile, operations, history, start_date, end_date)
    plan = profile_plan_df(profile)
    latest_date = latest_operation_date(profile["id"])
    st.caption(
        f"Операций в месяце: {len(operations)} · Операций в базе: {len(history)} · "
        f"Последняя дата операции: {latest_date or 'нет данных'}"
    )
    nav_tabs = ["Профиль и загрузка", "Очистка", "План", "Контроль", "Правила", "Диагностика"]
    if st.session_state.pop("active_page_after_import", None) == "Очистка":
        st.session_state["active_tab"] = "Очистка"
    if "active_tab" not in st.session_state or st.session_state["active_tab"] not in nav_tabs:
        st.session_state["active_tab"] = "Контроль" if not history.empty else "Профиль и загрузка"
    if st.session_state.get("nav_selected_tab") != st.session_state["active_tab"]:
        st.session_state["nav_selected_tab"] = st.session_state["active_tab"]
    selected_tab = st.radio(
        "Раздел",
        nav_tabs,
        horizontal=True,
        key="nav_selected_tab",
        label_visibility="collapsed",
        on_change=set_active_tab_from_nav,
    )
    if selected_tab == "Профиль и загрузка":
        render_profile_and_upload_page(profile, history, operations, start_date, end_date)
        refreshed_operations = operations_df(profile["id"], start_date, end_date)
        if st.session_state.get("last_import_summary") and len(refreshed_operations) != len(operations):
            st.info("После импорта раздел обновится автоматически при следующем действии Streamlit.")
    elif selected_tab == "Очистка":
        render_cleanup_page(profile, operations, history, report_month)
    elif selected_tab == "План":
        render_simplified_plan_tab(profile, history, report_month)
    elif selected_tab == "Контроль":
        render_control_page(profile, operations, history, plan, report_month, start_date, end_date)
    elif selected_tab == "Правила":
        render_rules_tab(profile, history)
    elif selected_tab == "Диагностика":
        st.session_state["_diagnostics_profile"] = profile
        render_diagnostics_tab(operations)
        st.subheader("Все операции")
        st.dataframe(display_operations(operations), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
