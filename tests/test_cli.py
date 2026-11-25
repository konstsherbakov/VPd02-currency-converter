"""Проверки меню и совместной работы CLI, API-клиента и хранилища."""

import io
import os
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

import requests

import api_client
import cli
import currency
import storage


class CLITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "test_cache.json"
        self.enterContext(patch.object(cli, "CACHE_PATH", self.path))
        self.get = self.enterContext(patch("api_client.requests.get"))
        self.usd = {
            "result": "success",
            "base_code": "USD",
            "rates": {"USD": 1, "RUB": 91.234567, "GBP": 0.8, "EUR": 0.92},
            "time_last_update_utc": "25 Nov 2026 00:00:00 +0000",
        }
        self.eur = {
            "result": "success",
            "base_code": "EUR",
            "rates": {"EUR": 1, "GBP": 0.876543},
        }
        self.respond(self.usd)

    def respond(self, data, status=200):
        response = Mock(spec=requests.Response, status_code=status)
        response.json.return_value = data
        self.get.return_value = response

    def run_menu(self, *inputs):
        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs), redirect_stdout(output):
            cli.main()
        return output.getvalue()

    def expire_cache(self):
        expired = self.path.stat().st_mtime - 25 * 3600
        os.utime(self.path, (expired, expired))

    def test_fetches_api_and_saves_when_cache_is_missing(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(cli.get_rates_with_cache(" usd "), (self.usd, "API"))
        self.get.assert_called_once_with("https://open.er-api.com/v6/latest/USD", timeout=10)
        self.assertEqual(storage.read_from_file(self.path), self.usd)

    def test_reuses_fresh_cache_without_request_or_mtime_change(self):
        storage.save_to_file(self.usd, self.path)
        before = self.path.stat().st_mtime_ns
        self.assertEqual(cli.get_rates_with_cache("USD"), (self.usd, "локальный кэш"))
        self.get.assert_not_called()
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_replaces_expired_cache(self):
        storage.save_to_file({**self.usd, "rates": {"RUB": 90}}, self.path)
        self.expire_cache()
        self.assertEqual(cli.get_rates_with_cache("USD"), (self.usd, "API"))
        self.get.assert_called_once()
        self.assertEqual(storage.read_from_file(self.path), self.usd)

    def test_replaces_corrupt_cache(self):
        self.path.write_text("{", encoding="utf-8")
        self.assertEqual(cli.get_rates_with_cache("USD"), (self.usd, "API"))
        self.get.assert_called_once()
        self.assertEqual(storage.read_from_file(self.path), self.usd)

    def test_replaces_cache_when_base_changes(self):
        cli.get_rates_with_cache("USD")
        self.respond(self.eur)
        self.assertEqual(cli.get_rates_with_cache("EUR"), (self.eur, "API"))
        self.assertEqual(self.get.call_args_list, [
            call("https://open.er-api.com/v6/latest/USD", timeout=10),
            call("https://open.er-api.com/v6/latest/EUR", timeout=10),
        ])
        self.assertEqual(storage.read_from_file(self.path), self.eur)

    def test_forces_refresh_even_with_fresh_cache(self):
        storage.save_to_file({**self.usd, "rates": {"RUB": 90}}, self.path)
        output = self.run_menu("4", "usd", "0")
        self.assertIn("Курсы для USD обновлены.", output)
        self.assertIn("Источник данных: API", output)
        self.get.assert_called_once()
        self.assertEqual(storage.read_from_file(self.path), self.usd)

    def test_converts_usd_to_rub_with_comma_and_rounds_to_four_places(self):
        output = self.run_menu("2", "usd", "rub", "2,5", "0")
        self.assertIn("2.5 USD = 228.0864 RUB\n", output)

    def test_converts_eur_to_gbp_with_dot_and_rounds_to_four_places(self):
        self.respond(self.eur)
        output = self.run_menu("2", "EUR", "GBP", "10.12345", "0")
        self.assertIn("10.12345 EUR = 8.8736 GBP\n", output)

    def test_converts_zero_and_same_currency(self):
        output = self.run_menu("2", "USD", "RUB", "0", "2", "USD", "usd", "3,125", "0")
        self.assertIn("0 USD = 0.0000 RUB\n", output)
        self.assertIn("3.125 USD = 3.1250 USD\n", output)
        self.get.assert_called_once()

    def test_rejects_negative_nonfinite_and_invalid_amounts_before_request(self):
        cases = (
            ("-1", "Сумма не может быть отрицательной"),
            ("NaN", "Введите конечную числовую сумму"),
            ("Infinity", "Введите конечную числовую сумму"),
            ("-inf", "Введите конечную числовую сумму"),
            ("abc", "Введите конечную числовую сумму"),
            ("1,2.3", "Введите конечную числовую сумму"),
        )
        for amount, message in cases:
            with self.subTest(amount=amount):
                output = self.run_menu("2", "USD", "RUB", amount, "0")
                self.assertIn(f"Ошибка: {message}", output)
                self.assertEqual(output.count("0 — Выход"), 2)
        self.get.assert_not_called()

    def test_rejects_invalid_currency_format_before_request(self):
        output = self.run_menu("1", "U1D", "2", "USD", "ЮСД", "0")
        self.assertEqual(output.count("Ошибка: Код валюты должен состоять"), 2)
        self.get.assert_not_called()

    def test_reports_unknown_base_currency(self):
        self.respond({"result": "error", "error-type": "unsupported-code"})
        output = self.run_menu("1", "zzz", "0")
        self.assertIn("Ошибка: Валюта ZZZ не поддерживается", output)
        self.assertFalse(self.path.exists())

    def test_reports_unknown_target_currency(self):
        output = self.run_menu("2", "USD", "ZZZ", "10", "0")
        self.assertIn("Ошибка: Валюта ZZZ отсутствует", output)
        self.assertNotIn("10 USD =", output)

    def test_shows_rates_update_date_and_sorted_currencies(self):
        output = self.run_menu("1", "usd", "3", "0")
        for fragment in (
            "1 USD = 91.234567 RUB",
            "1 USD = 0.92 EUR",
            "1 USD = 0.8 GBP",
            self.usd["time_last_update_utc"],
            "EUR, GBP, RUB, USD",
            "Источник данных: API",
            "Источник данных: локальный кэш",
            "https://www.exchangerate-api.com",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, output)
        self.get.assert_called_once()

    def test_network_error_without_cache_returns_to_menu(self):
        self.get.side_effect = requests.exceptions.ConnectionError
        output = self.run_menu("1", "USD", "0")
        self.assertIn("Ошибка: Не удалось подключиться", output)
        self.assertEqual(output.count("0 — Выход"), 2)
        self.assertFalse(self.path.exists())

    def test_failed_request_preserves_cache_without_showing_stale_rates(self):
        storage.save_to_file(self.usd, self.path)
        self.expire_cache()
        previous = self.path.read_bytes()
        before = self.path.stat().st_mtime_ns
        self.get.side_effect = requests.exceptions.Timeout
        output = self.run_menu("1", "USD", "0")
        self.assertIn("Ошибка: Сервис курсов валют не ответил вовремя", output)
        self.assertNotIn("1 USD =", output)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_write_error_returns_to_menu_and_preserves_cache(self):
        storage.save_to_file(self.usd, self.path)
        before = self.path.stat().st_mtime_ns
        self.respond(self.eur)
        with patch("storage.Path.replace", side_effect=PermissionError("Нет доступа")):
            output = self.run_menu("4", "EUR", "0")
        self.assertIn("Ошибка: Не удалось записать файл кэша", output)
        self.assertEqual(output.count("0 — Выход"), 2)
        self.assertEqual(storage.read_from_file(self.path), self.usd)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_invalid_rate_in_api_response_does_not_replace_valid_cache(self):
        storage.save_to_file(self.usd, self.path)
        self.respond({**self.usd, "rates": {**self.usd["rates"], "RUB": -1}})
        output = self.run_menu("4", "USD", "0")
        actual = ("Ошибка:" in output, storage.read_from_file(self.path)["rates"]["RUB"])
        self.assertEqual(actual, (True, self.usd["rates"]["RUB"]), output)

    def test_invalid_menu_choice_then_exit(self):
        output = self.run_menu("9", "0")
        self.assertIn("Выберите один из пунктов меню.", output)
        self.assertEqual(output.count("0 — Выход"), 2)
        self.assertTrue(output.endswith("До свидания!\n"))
        self.get.assert_not_called()

    def test_exit_immediately(self):
        output = self.run_menu("0")
        self.assertEqual(output.count("0 — Выход"), 1)
        self.assertTrue(output.endswith("До свидания!\n"))
        self.get.assert_not_called()

    def test_entry_point_and_compatible_imports(self):
        self.assertIs(currency.get_currency_rates, api_client.get_currency_rates)
        self.assertIs(currency.save_to_file, storage.save_to_file)
        self.assertIs(currency.read_from_file, storage.read_from_file)
        with patch.object(cli, "main") as main:
            runpy.run_path(currency.__file__, run_name="__main__")
        main.assert_called_once_with()
