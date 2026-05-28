import unittest

try:
    import pandas as pd
    from ui_flow import (
        account_type_label,
        build_budget_readiness,
        build_home_primary_action,
        build_home_secondary_actions,
        build_user_journey_steps,
        default_income_cleanup_scenario,
        determine_user_next_step,
        format_review_operation_line,
        import_period_display,
        import_status_label,
        sort_cleanup_groups,
        visible_operation_columns,
    )
except ModuleNotFoundError:
    pd = None
    account_type_label = None
    build_budget_readiness = None
    build_home_primary_action = None
    build_home_secondary_actions = None
    build_user_journey_steps = None
    default_income_cleanup_scenario = None
    determine_user_next_step = None
    format_review_operation_line = None
    import_period_display = None
    import_status_label = None
    sort_cleanup_groups = None
    visible_operation_columns = None


def operation(needs_review=False):
    return {
        "id": "op1",
        "operation_datetime": "2026-05-10T10:00:00",
        "bank": "Сбер",
        "description": "TEST MERCHANT",
        "bank_amount": -1000,
        "operation_type": "Личный расход",
        "budget_category": "Продукты / супермаркеты",
        "needs_review": needs_review,
        "duplicate_key": "secret-duplicate-key",
        "classification_source": "technical-source",
        "rule_id": "rule-secret",
        "account_id": "account-secret",
        "linked_operation_id": "linked-secret",
    }


class UserJourneyAndDisplayTest(unittest.TestCase):
    def setUp(self):
        if pd is None:
            self.skipTest("pandas is not installed in this Python environment")

    def test_next_step_without_history_is_upload(self):
        self.assertEqual(determine_user_next_step(pd.DataFrame(), pd.DataFrame(), {}), "Профиль и загрузка")
        action = build_home_primary_action(pd.DataFrame(), pd.DataFrame(), {})
        self.assertEqual(action["target"], "Профиль и загрузка")
        self.assertEqual(action["label"], "Загрузить выписки")

    def test_next_step_with_review_is_cleanup(self):
        history = pd.DataFrame([operation(needs_review=True)])
        operations = pd.DataFrame([operation(needs_review=True)])

        self.assertEqual(determine_user_next_step(history, operations, {"plan_source": "auto_plan"}), "Очистка операций")
        action = build_home_primary_action(history, operations, {"plan_source": "auto_plan"})
        self.assertEqual(action["target"], "Очистка")
        self.assertIn("Нужно уточнить", action["status"])

    def test_next_step_without_plan_is_plan(self):
        history = pd.DataFrame([operation(False)])
        operations = pd.DataFrame([operation(False)])

        self.assertEqual(determine_user_next_step(history, operations, {}), "План месяца")
        action = build_home_primary_action(history, operations, {})
        self.assertEqual(action["target"], "План")
        self.assertEqual(action["label"], "Перейти к плану")

    def test_next_step_with_clean_data_and_plan_is_control(self):
        history = pd.DataFrame([operation(False)])
        operations = pd.DataFrame([operation(False)])

        self.assertEqual(determine_user_next_step(history, operations, {"plan_source": "auto_plan"}), "Контроль бюджета")
        action = build_home_primary_action(history, operations, {"plan_source": "auto_plan"})
        self.assertEqual(action["target"], "Контроль")
        self.assertEqual(action["label"], "Открыть контроль")

    def test_budget_readiness_reports_stage_statuses(self):
        history = pd.DataFrame([operation(False)])
        operations = pd.DataFrame([operation(needs_review=True)])

        readiness = build_budget_readiness(history, operations, {"plan_source": "auto_plan"})
        statuses = {item["title"]: item["status"] for item in readiness}

        self.assertEqual(statuses["Данные загружены"], "done")
        self.assertEqual(statuses["Очистка операций"], "needs_attention")
        self.assertEqual(statuses["План принят"], "done")
        self.assertEqual(statuses["Контроль доступен"], "done")

    def test_home_secondary_actions_do_not_duplicate_primary_target(self):
        history = pd.DataFrame([operation(False)])
        operations = pd.DataFrame([operation(False)])
        profile = {"plan_source": "auto_plan"}
        primary = build_home_primary_action(history, operations, profile)

        actions = build_home_secondary_actions(primary, history, operations, profile)

        self.assertNotIn(primary["target"], {action["action_target"] for action in actions})

    def test_account_type_labels_are_human_readable(self):
        self.assertEqual(account_type_label("debit_account"), "Дебетовая карта")
        self.assertEqual(account_type_label("credit_card"), "Кредитная карта")
        self.assertEqual(account_type_label("unknown"), "Не определён")
        self.assertEqual(account_type_label("new_internal_code"), "Не определён")

    def test_import_status_labels_are_human_readable(self):
        self.assertEqual(import_status_label("imported"), "Импортировано")
        self.assertEqual(import_status_label("skipped_irrelevant"), "Пропущено")
        self.assertEqual(import_status_label("unknown"), "Не определён")

    def test_import_period_display(self):
        self.assertEqual(import_period_display("", ""), "не определён")
        self.assertEqual(import_period_display(None, None), "не определён")
        self.assertEqual(import_period_display("2026-05-01", "2026-05-31"), "2026-05-01 — 2026-05-31")

    def test_income_transfer_default_is_not_salary(self):
        candidate = {"anchor": "Перевод от Ш. Никита Юрьевич", "examples": "Перевод от Ш. Никита Юрьевич"}
        self.assertNotEqual(default_income_cleanup_scenario(candidate), "Личный доход")
        self.assertEqual(default_income_cleanup_scenario(candidate), "Компенсация расходов")

    def test_salary_text_can_default_to_personal_income(self):
        candidate = {"anchor": "Работодатель", "examples": "Зачисление заработной платы за май"}
        self.assertEqual(default_income_cleanup_scenario(candidate), "Личный доход")

    def test_cleanup_groups_sort_by_recurrence_and_amount(self):
        groups = pd.DataFrame(
            [
                {"anchor": "Разовая крупная", "count": 1, "months_seen": 1, "total_sum": 50000, "median_monthly_sum": 50000, "expense_nature": "oneoff_large"},
                {"anchor": "Повторяется", "count": 3, "months_seen": 2, "total_sum": 18000, "median_monthly_sum": 9000, "expense_nature": "recurring"},
                {"anchor": "Мелкая", "count": 1, "months_seen": 1, "total_sum": 1000, "median_monthly_sum": 1000, "expense_nature": "oneoff_minor"},
            ]
        )
        sorted_groups = sort_cleanup_groups(groups)
        self.assertEqual(sorted_groups.iloc[0]["anchor"], "Повторяется")
        self.assertEqual(sorted_groups.iloc[1]["anchor"], "Разовая крупная")

    def test_review_operation_line_is_human_readable(self):
        row = {"operation_datetime": "2026-05-15T06:08:00", "bank_amount": 10000, "description": "Перевод от Никиты"}
        self.assertEqual(format_review_operation_line(row), "15.05 · 10 000 ₽ · Перевод от Никиты")

    def test_done_steps_still_have_tabs(self):
        history = pd.DataFrame([operation(False)])
        operations = pd.DataFrame([operation(False)])

        steps = build_user_journey_steps(history, operations, {"plan_source": "auto_plan"}, "Контроль бюджета")

        tabs = {step["title"]: step["tab"] for step in steps}
        self.assertEqual(tabs["Профиль и загрузка"], "Профиль и загрузка")
        self.assertEqual(tabs["Очистка операций"], "Очистка")
        self.assertEqual(tabs["План месяца"], "План")
        self.assertEqual(tabs["Контроль бюджета"], "Контроль")

    def test_default_operation_columns_hide_technical_fields(self):
        columns = visible_operation_columns()

        self.assertIn("operation_datetime", columns)
        self.assertIn("description", columns)
        self.assertNotIn("duplicate_key", columns)
        self.assertNotIn("classification_source", columns)
        self.assertNotIn("rule_id", columns)
        self.assertNotIn("account_id", columns)
        self.assertNotIn("linked_operation_id", columns)

    def test_technical_operation_columns_are_available_for_diagnostics(self):
        columns = visible_operation_columns(include_technical=True)

        self.assertEqual(columns["duplicate_key"], "ключ дубля")
        self.assertEqual(columns["classification_source"], "источник")
        self.assertEqual(columns["rule_id"], "id правила")
        self.assertEqual(columns["account_id"], "account id")
        self.assertEqual(columns["linked_operation_id"], "связана с")


if __name__ == "__main__":
    unittest.main()
