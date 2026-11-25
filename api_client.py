"""Получение курсов валют из открытого ExchangeRate-API."""

import math

import requests


class CurrencyAPIError(RuntimeError):
    """Ошибка запроса к сервису курсов валют или обработки его ответа."""


def get_currency_rates(base: str) -> dict:
    """Вернуть полный ответ API с курсами для базовой валюты base.

    ValueError означает неверный формат кода валюты.
    CurrencyAPIError означает сбой запроса или ошибку в ответе сервиса.
    """
    base = base.strip()
    # Проверяем латиницу до upper(): некоторые символы Юникода меняются при смене регистра.
    if len(base) != 3 or not base.isascii() or not base.isalpha():
        raise ValueError("Код валюты должен состоять из трёх латинских букв, например USD.")
    base = base.upper()

    url = f"https://open.er-api.com/v6/latest/{base}"
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.Timeout as error:
        raise CurrencyAPIError("Сервис курсов валют не ответил вовремя.") from error
    except requests.exceptions.ConnectionError as error:
        raise CurrencyAPIError("Не удалось подключиться к сервису курсов валют.") from error
    except requests.exceptions.RequestException as error:
        raise CurrencyAPIError("Не удалось выполнить запрос к сервису курсов валют.") from error

    status_ok = response.status_code == 200
    http_status = f"HTTP {response.status_code}"
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise CurrencyAPIError(
            f"Сервис курсов валют вернул некорректный JSON ({http_status})."
        ) from error

    # Читаем ошибку из тела ответа при любом HTTP-статусе.
    if isinstance(data, dict) and data.get("result") == "error":
        error_type = data.get("error-type") or "тип ошибки не указан"
        if error_type == "unsupported-code":
            raise CurrencyAPIError(f"Валюта {base} не поддерживается сервисом ({http_status}).")
        raise CurrencyAPIError(f"Сервис курсов валют сообщил об ошибке ({http_status}): {error_type}.")

    if not status_ok:
        raise CurrencyAPIError(f"Сервис курсов валют вернул статус {http_status}.")
    if not isinstance(data, dict) or data.get("result") != "success":
        raise CurrencyAPIError("Сервис курсов валют не подтвердил успешное получение данных.")

    rates = data.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise CurrencyAPIError("В ответе сервиса отсутствует непустой словарь курсов rates.")
    if data.get("base_code") != base:
        raise CurrencyAPIError(f"Код базовой валюты в ответе сервиса не совпадает с {base}.")

    for code, rate in rates.items():
        # Проверка точного типа исключает bool. Целые числа конечны без преобразования во float.
        if (
            type(rate) not in (int, float)
            or rate <= 0
            or (type(rate) is float and not math.isfinite(rate))
        ):
            raise CurrencyAPIError(
                f"Сервис курсов валют вернул некорректный курс для {code}."
            )

    return data
