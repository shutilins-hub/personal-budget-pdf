import unittest

try:
    import pandas as pd
    from ui_flow import (
        build_budget_readiness,
        build_home_primary_action,
        build_home_secondary_actions,
        build_user_journey_steps,
        determine_user_next_step,
        visible_operation_columns,
    )
except ModuleNotFoundError:
    pd = None
    build_budget_readiness = None
    build_home_primary_action = None
    build_home_secondary_actions = None
    build_user_journey_steps = None
    determine_user_next_step = None
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
