import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import debug_exports
from pdf_parser import parse_money, parse_sber

try:
    import fitz
except ModuleNotFoundError:
    fitz = None


class SberParserTest(unittest.TestCase):
    def test_column_block_expense_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUDGET_DEBUG_EXPORTS": "1"}, clear=False):
                with patch.object(debug_exports, "EXPORTS_DIR", Path(tmp)):
                    operations = parse_sber(
                        "\n".join(
                            [
                                "15.05.2026",
                                "09:29",
                                "Рестораны и кафе",
                                "280,00",
                                "260 749,62",
                                "15.05.2026",
                                "614550",
                                "COFFEE POINT MOSCOW RUS. Операция по карте ****0653",
                            ]
                        ),
                        "test_profile",
                        "sber_test.pdf",
                    )
                    debug_text = (Path(tmp) / "sber_raw_lines_debug.txt").read_text(encoding="utf-8")

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["operation_datetime"], "2026-05-15T09:29:00")
        self.assertEqual(operations[0]["raw_category"], "Рестораны и кафе")
        self.assertEqual(operations[0]["bank_amount"], -280.0)
        self.assertIn("COFFEE POINT", operations[0]["description"])
        self.assertIn("0001 | OPERATION_START", debug_text)
        self.assertIn("0008 | DESCRIPTION_LINE", debug_text)

    def test_column_block_income_operation(self):
        operations = parse_sber(
            "\n".join(
                [
                    "14.05.2026",
                    "09:50",
                    "Перевод на карту",
                    "+15 000,00",
                    "329 100,62",
                    "14.05.2026",
                    "168270",
                    "Перевод от З. Анна Сергеевна. Операция по счету ****9683",
                ]
            ),
            "test_profile",
            "sber_test.pdf",
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["operation_datetime"], "2026-05-14T09:50:00")
        self.assertEqual(operations[0]["raw_category"], "Перевод на карту")
        self.assertEqual(operations[0]["bank_amount"], 15000.0)
        self.assertEqual(operations[0]["direction"], "income")
        self.assertIn("Перевод от З. Анна Сергеевна", operations[0]["description"])

    def test_one_line_operation_fallback(self):
        operations = parse_sber(
            "\n".join(
                [
                    "Выписка по счёту",
                    "Дата закрытия счёта 16.05.2026",
                    "Продолжение на следующей странице",
                    "Остаток на 16.05.2026 260 749,62",
                    "15.05.2026 09:29 Рестораны и кафе 280,00 260 749,62",
                    "15.05.2026 614550 COFFEE POINT MOSCOW RUS. Операция по карте ****0653",
                ]
            ),
            "test_profile",
            "sber_test.pdf",
        )
        descriptions = " ".join(operation["description"] for operation in operations)

        self.assertEqual(len(operations), 1)
        self.assertNotIn("Дата закрытия счёта", descriptions)
        self.assertNotIn("Продолжение на следующей странице", descriptions)
        self.assertEqual(operations[0]["operation_datetime"], "2026-05-15T09:29:00")
        self.assertEqual(operations[0]["raw_category"], "Рестораны и кафе")
        self.assertEqual(operations[0]["bank_amount"], -280.0)

    def test_auth_codes_and_times_are_not_operations(self):
        operations = parse_sber(
            "\n".join(
                [
                    "15.05.2026",
                    "168425",
                    "COFFEE POINT MOSCOW RUS",
                    "15.05.2026",
                    "14:04",
                    "15.05.2026",
                    "06:08",
                    "15.05.2026",
                    "09:29",
                    "Cafe",
                    "280,00",
                    "260 749,62",
                    "15.05.2026",
                    "614550",
                    "COFFEE POINT MOSCOW RUS",
                ]
            ),
            "test_profile",
            "sber_test.pdf",
        )
        descriptions = " ".join(operation["description"] for operation in operations)

        self.assertEqual(len(operations), 1)
        self.assertNotIn("168425", descriptions)
        self.assertNotIn("14:04", descriptions)
        self.assertNotIn("06:08", descriptions)

    def test_parse_money_requires_kopecks(self):
        self.assertEqual(parse_money("280,00"), 280.0)
        self.assertEqual(parse_money("1 270,00"), 1270.0)
        self.assertEqual(parse_money("+15 000,00"), 15000.0)
        self.assertEqual(parse_money("2 098 060,00"), 2098060.0)
        self.assertIsNone(parse_money("168425"))
        self.assertIsNone(parse_money("482142"))
        self.assertIsNone(parse_money("14:04"))
        self.assertIsNone(parse_money("614550"))

    def test_column_block_description_skips_page_headers(self):
        operations = parse_sber(
            "\n".join(
                [
                    "10.05.2026",
                    "13:49",
                    "Отдых и развлечения",
                    "93,95",
                    "309,02",
                    "10.05.2026",
                    "779003",
                    "WHOOSH MOSCOW RUS. Операция по карте ****8640",
                    "Продолжение на следующей странице",
                    "Выписка по платёжному счёту",
                    "Страница 2 из 111",
                    "ДАТА ОПЕРАЦИИ (МСК)",
                    "Дата обработки¹",
                    "и код авторизации",
                    "КАТЕГОРИЯ",
                    "Описание операции",
                    "СУММА В ВАЛЮТЕ СЧЁТА",
                    "10.05.2026",
                    "11:53",
                    "Выдача наличных",
                    "5 000,00",
                    "402,97",
                    "10.05.2026",
                    "888107",
                    "ATM 60210427 BARNAUL RUS. Операция по карте ****8640",
                ]
            ),
            "test_profile",
            "sber_test.pdf",
        )

        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[0]["description"], "WHOOSH MOSCOW RUS. Операция по карте ****8640")

    def test_uploaded_sber_debit_account_may_blocks_when_available(self):
        pdf_path = Path("/Users/user/Downloads/Выписка_по_счёту_дебетовой_карты (4).pdf")
        if fitz is None or not pdf_path.exists():
            self.skipTest("Local Sber fixture is not available")
        with fitz.open(pdf_path) as doc:
            text = "\n".join(page.get_text("text") for page in doc)

        operations = parse_sber(text, "test_profile", pdf_path.name)
        may_operations = [operation for operation in operations if operation["operation_datetime"].startswith("2026-05")]

        self.assertEqual(len(may_operations), 33)
        self.assertTrue(any("KRASNOE&BELOE" in operation["description"] for operation in may_operations))
        self.assertTrue(any("NEM-NEM" in operation["description"] for operation in may_operations))
        self.assertTrue(any("WHOOSH" in operation["description"] for operation in may_operations))


if __name__ == "__main__":
    unittest.main()
