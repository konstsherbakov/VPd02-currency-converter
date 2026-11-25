"""Проверки API-клиента с подменой HTTP-запросов."""

import unittest
from unittest.mock import Mock, patch

import requests

from api_client import CurrencyAPIError, get_currency_rates


class APIClientTests(unittest.TestCase):
    def setUp(self):
        self.get = self.enterContext(patch("api_client.requests.get"))
        self.data = {
            "result": "success",
            "base_code": "USD",
            "rates": {"USD": 1, "EUR": 0.92},
            "time_last_update_utc": "25 Nov 2026 00:00:00 +0000",
        }
        self.response = Mock(spec=requests.Response, status_code=200)
        self.response.json.return_value = self.data
        self.get.return_value = self.response

    def test_returns_full_successful_response(self):
        self.assertEqual(get_currency_rates("USD"), self.data)
        self.response.json.assert_called_once_with()

    def test_accepts_positive_int_and_float_rates(self):
        # Большой int нельзя безопасно преобразовать во float для проверки конечности.
        data = {**self.data, "rates": {"USD": 1, "EUR": 0.92, "RUB": 10**400}}
        self.response.json.return_value = data
        self.assertEqual(get_currency_rates("USD"), data)

    def test_rejects_invalid_rate_values_and_reports_currency_code(self):
        for rate in (0, -1, "0.92", True, False, None, float("nan"), float("inf"), float("-inf")):
            with self.subTest(rate=rate):
                self.response.json.return_value = {**self.data, "rates": {**self.data["rates"], "RUB": rate}}
                with self.assertRaisesRegex(CurrencyAPIError, "некорректный курс для RUB"):
                    get_currency_rates("USD")

    def test_normalizes_code_and_passes_timeout(self):
        get_currency_rates("  usd \t")
        self.get.assert_called_once_with("https://open.er-api.com/v6/latest/USD", timeout=10)

    def test_rejects_invalid_codes_before_http_request(self):
        for code in ("", "US", "USDX", "U1D", "ЮСД", "ＵＳＤ", "uſd"):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "трёх латинских букв"):
                get_currency_rates(code)
        self.get.assert_not_called()

    def test_rejects_http_status_other_than_200(self):
        for status in (201, 429, 500):
            self.response.status_code = status
            with self.subTest(status=status), self.assertRaisesRegex(CurrencyAPIError, f"HTTP {status}"):
                get_currency_rates("USD")

    def test_reports_unsupported_code_for_both_http_statuses(self):
        self.response.json.return_value = {"result": "error", "error-type": "unsupported-code"}
        for status in (200, 404):
            self.response.status_code = status
            with self.subTest(status=status):
                with self.assertRaisesRegex(CurrencyAPIError, rf"Валюта ZZZ не поддерживается.*HTTP {status}"):
                    get_currency_rates("zzz")

    def test_reports_other_api_error_type(self):
        self.response.json.return_value = {"result": "error", "error-type": "invalid-key"}
        with self.assertRaisesRegex(CurrencyAPIError, "invalid-key"):
            get_currency_rates("USD")

    def test_reports_timeout(self):
        self.get.side_effect = requests.exceptions.Timeout
        with self.assertRaisesRegex(CurrencyAPIError, "не ответил вовремя"):
            get_currency_rates("USD")

    def test_reports_connection_error(self):
        self.get.side_effect = requests.exceptions.ConnectionError
        with self.assertRaisesRegex(CurrencyAPIError, "Не удалось подключиться"):
            get_currency_rates("USD")

    def test_reports_invalid_json(self):
        self.response.json.side_effect = requests.exceptions.JSONDecodeError("invalid", "{", 1)
        for status in (200, 503):
            self.response.status_code = status
            with self.subTest(status=status):
                with self.assertRaisesRegex(CurrencyAPIError, rf"некорректный JSON.*HTTP {status}"):
                    get_currency_rates("USD")

    def test_rejects_missing_or_invalid_response_fields(self):
        cases = (
            ([], "не подтвердил"),
            ({key: value for key, value in self.data.items() if key != "result"}, "не подтвердил"),
            ({**self.data, "result": "unknown"}, "не подтвердил"),
            ({key: value for key, value in self.data.items() if key != "rates"}, "словарь курсов"),
            ({**self.data, "rates": {}}, "словарь курсов"),
            ({**self.data, "rates": [1]}, "словарь курсов"),
            ({key: value for key, value in self.data.items() if key != "base_code"}, "не совпадает"),
            ({**self.data, "base_code": "EUR"}, "не совпадает"),
        )
        for payload, message in cases:
            self.response.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaisesRegex(CurrencyAPIError, message):
                get_currency_rates("USD")
