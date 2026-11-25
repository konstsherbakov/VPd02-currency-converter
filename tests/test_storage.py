"""Проверки файлового кэша на временных данных."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from storage import is_cache_valid, read_from_file, save_to_file


DAY = 24 * 3600
NOW = 1_800_000_000


class StorageTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "test_cache.json"
        self.enterContext(patch("storage.time", return_value=NOW))
        self.data = {
            "result": "success",
            "base_code": "USD",
            "rates": {"USD": 1, "EUR": 0.92},
            "provider": "Тестовый поставщик",
        }

    def set_cache_age(self, seconds):
        # Задаём отметку только временному файлу. Часы подменены внутри storage.
        stamp = NOW - seconds
        os.utime(self.path, (stamp, stamp))

    def test_saves_and_reads_full_dictionary(self):
        save_to_file(self.data, self.path)
        self.assertTrue(self.path.is_file())
        self.assertEqual(read_from_file(str(self.path)), self.data)

    def test_writes_indented_utf8_with_cyrillic(self):
        save_to_file(self.data, self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('\n    "provider": "Тестовый поставщик"', text)
        self.assertEqual(json.loads(text), self.data)

    def test_missing_file(self):
        with self.assertRaisesRegex(FileNotFoundError, "не найден"):
            read_from_file(self.path)
        self.assertFalse(is_cache_valid("USD", self.path))

    def test_corrupt_json_invalid_encoding_and_non_dict(self):
        for content in (b'{"result":', b"\xff", b"[]"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                self.set_cache_age(60)
                with self.assertRaises(ValueError):
                    read_from_file(self.path)
                self.assertFalse(is_cache_valid("USD", self.path))

    def test_accepts_fresh_cache(self):
        save_to_file(self.data, self.path)
        self.set_cache_age(DAY - 1)
        self.assertTrue(is_cache_valid(" usd ", self.path))

    def test_rejects_cache_exactly_24_hours_old(self):
        save_to_file(self.data, self.path)
        self.set_cache_age(DAY)
        self.assertFalse(is_cache_valid("USD", self.path))

    def test_rejects_expired_cache(self):
        save_to_file(self.data, self.path)
        self.set_cache_age(DAY + 1)
        self.assertFalse(is_cache_valid("USD", self.path))

    def test_rejects_cache_for_another_base(self):
        save_to_file(self.data, self.path)
        self.set_cache_age(60)
        self.assertFalse(is_cache_valid("EUR", self.path))

    def test_rejects_missing_or_invalid_cache_fields(self):
        cases = (
            {**self.data, "result": "error"},
            {key: value for key, value in self.data.items() if key != "rates"},
            {**self.data, "rates": {}},
            {**self.data, "rates": [1]},
        )
        for data in cases:
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                self.set_cache_age(60)
                self.assertFalse(is_cache_valid("USD", self.path))

    def test_rejects_invalid_exchange_rates(self):
        for rate in ("0", "-1", '"1.2"', "true", "false", "null", "[]", "NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(rate=rate):
                # Формируем содержимое напрямую, чтобы включить недопустимые значения вроде NaN.
                self.path.write_text(
                    '{"result":"success","base_code":"USD","rates":{"USD":' + rate + '}}',
                    encoding="utf-8",
                )
                self.set_cache_age(60)
                self.assertFalse(is_cache_valid("USD", self.path))

    def test_preserves_previous_file_when_replacement_fails(self):
        save_to_file(self.data, self.path)
        previous_bytes = self.path.read_bytes()
        previous_mtime = self.path.stat().st_mtime_ns
        with patch("storage.Path.replace", side_effect=PermissionError("Нет доступа")):
            with self.assertRaisesRegex(OSError, "Не удалось записать"):
                save_to_file({**self.data, "rates": {"USD": 1}}, self.path)
        self.assertEqual(self.path.read_bytes(), previous_bytes)
        self.assertEqual(self.path.stat().st_mtime_ns, previous_mtime)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
