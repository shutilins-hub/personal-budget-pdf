from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import debug_exports
from debug_exports import write_debug_json, write_debug_text, write_debug_tsv
from privacy import sanitize_text


class PrivacyAndDebugExportsTest(unittest.TestCase):
    def test_sanitize_text_masks_phone(self) -> None:
        result = sanitize_text("Телефон +7 999 123-45-67")
        self.assertNotIn("+7 999 123-45-67", result)
        self.assertIn("[телефон скрыт]", result)

    def test_sanitize_text_masks_card_number(self) -> None:
        result = sanitize_text("Карта 4276 1234 5678 9012")
        self.assertNotIn("4276 1234 5678 9012", result)

    def test_sanitize_text_masks_long_account_number(self) -> None:
        result = sanitize_text("Счет 40817810900000000001")
        self.assertNotIn("40817810900000000001", result)

    def test_sanitize_text_masks_fio(self) -> None:
        result = sanitize_text("Клиент Иванов Иван Иванович")
        self.assertNotIn("Иванов Иван Иванович", result)
        self.assertIn("[ФИО скрыто]", result)

    def test_write_debug_text_does_not_write_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": ""}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    self.assertFalse(write_debug_text("debug.txt", "Иванов Иван Иванович"))
                    self.assertEqual([], list(Path(tmp).iterdir()))

    def test_write_debug_text_writes_only_sanitized_text_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": "1"}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    self.assertTrue(write_debug_text("debug.txt", "Иванов Иван Иванович +7 999 123-45-67"))
                    content = (Path(tmp) / "debug.txt").read_text(encoding="utf-8")

        self.assertNotIn("Иванов Иван Иванович", content)
        self.assertNotIn("+7 999 123-45-67", content)
        self.assertIn("[ФИО скрыто]", content)

    def test_write_debug_tsv_sanitizes_dataframe_strings(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "description": "Перевод от Иванов Иван Иванович",
                    "phone": "+7 999 123-45-67",
                    "amount": 1000,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": "1"}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    self.assertTrue(write_debug_tsv("debug.tsv", frame))
                    content = (Path(tmp) / "debug.tsv").read_text(encoding="utf-8")

        self.assertNotIn("Иванов Иван Иванович", content)
        self.assertNotIn("+7 999 123-45-67", content)
        self.assertIn("[ФИО скрыто]", content)

    def test_write_debug_json_sanitizes_nested_strings(self) -> None:
        payload = {
            "client": "Иванов Иван Иванович",
            "items": [
                {"phone": "+7 999 123-45-67"},
                {"card": "4276 1234 5678 9012"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": "1"}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    self.assertTrue(write_debug_json("debug.json", payload))
                    content = (Path(tmp) / "debug.json").read_text(encoding="utf-8")

        self.assertNotIn("Иванов Иван Иванович", content)
        self.assertNotIn("+7 999 123-45-67", content)
        self.assertNotIn("4276 1234 5678 9012", content)
        self.assertIn("[ФИО скрыто]", content)


if __name__ == "__main__":
    unittest.main()
