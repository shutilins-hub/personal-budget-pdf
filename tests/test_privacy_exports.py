from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import debug_exports
from privacy import sanitize_text
from report_builder import write_import_debug


SENSITIVE_TEXT = (
    "Клиент Иванов Иван Иванович\n"
    "Телефон +7 999 123-45-67\n"
    "Карта 4276 1234 5678 9012\n"
    "Счет 40817810900000000001\n"
)


class PrivacyExportsTests(unittest.TestCase):
    def test_sanitize_text_masks_phone(self) -> None:
        result = sanitize_text("Телефон +7 999 123-45-67")
        self.assertNotIn("+7 999 123-45-67", result)
        self.assertIn("[телефон скрыт]", result)

    def test_sanitize_text_masks_card_and_account(self) -> None:
        result = sanitize_text("Карта 4276 1234 5678 9012, счет 40817810900000000001")
        self.assertNotIn("4276 1234 5678 9012", result)
        self.assertNotIn("40817810900000000001", result)
        self.assertTrue("[карта скрыта]" in result or "[номер скрыт]" in result)
        self.assertTrue("[счет скрыт]" in result or "[номер скрыт]" in result)

    def test_sanitize_text_masks_fio(self) -> None:
        result = sanitize_text("Клиент Иванов Иван Иванович")
        self.assertNotIn("Иванов Иван Иванович", result)
        self.assertIn("[ФИО скрыто]", result)

    def test_import_debug_does_not_write_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": ""}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    write_import_debug(SENSITIVE_TEXT, [], {"files": [{"first_30_lines": [SENSITIVE_TEXT]}]})
                    self.assertEqual([], list(Path(tmp).iterdir()))

    def test_import_debug_writes_sanitized_text_when_enabled(self) -> None:
        parsed = [
            {
                "description": "Перевод от Иванов Иван Иванович +7 999 123-45-67",
                "bank_amount": 10000,
                "operation_datetime": "2026-05-01T10:00:00",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": "1"}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    write_import_debug(SENSITIVE_TEXT, parsed, {"files": [{"first_30_lines": [SENSITIVE_TEXT]}]})
                    text_debug = (Path(tmp) / "extracted_text_debug.txt").read_text(encoding="utf-8")
                    summary_debug = (Path(tmp) / "import_summary.json").read_text(encoding="utf-8")
                    operations_debug = (Path(tmp) / "parsed_operations_debug.tsv").read_text(encoding="utf-8")

        combined = "\n".join([text_debug, summary_debug, operations_debug])
        self.assertNotIn("Иванов Иван Иванович", combined)
        self.assertNotIn("+7 999 123-45-67", combined)
        self.assertNotIn("4276 1234 5678 9012", combined)
        self.assertNotIn("40817810900000000001", combined)
        self.assertIn("[ФИО скрыто]", combined)


if __name__ == "__main__":
    unittest.main()
