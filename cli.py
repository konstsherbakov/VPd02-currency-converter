"""Русскоязычное консольное меню конвертера валют."""

import re
from decimal import Decimal, localcontext
from math import inf

from api_client import CurrencyAPIError, get_currency_rates
from storage import is_cache_valid, read_from_file, save_to_file


CACHE_PATH = "currency_rate.json"
MENU = """\n1 — Посмотреть курсы валют
2 — Конвертировать сумму
3 — Список доступных валют
4 — Обновить курсы принудительно
0 — Выход"""


def normalize_currency(code: str) -> str:
    """Проверить формат кода валюты и привести его к верхнему регистру."""
    code = code.strip()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError("Код валюты должен состоять из трёх латинских букв, например USD.")
    return code.upper()


def parse_amount(text: str) -> Decimal:
    """Прочитать неотрицательную десятичную сумму с точкой или запятой."""
    text = text.strip()
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)", text):
        raise ValueError("Введите конечную числовую сумму, например 12,50 или 12.50.")
    amount = Decimal(text.replace(",", "."))
    if amount < 0:
        raise ValueError("Сумма не может быть отрицательной.")
    return amount if amount else Decimal(0)


def get_rates_with_cache(base: str, force_refresh: bool = False) -> tuple[dict, str]:
    """Вернуть полный ответ с курсами и название источника данных."""
    base = normalize_currency(base)
    if not force_refresh and is_cache_valid(base, CACHE_PATH):
        try:
            data = read_from_file(CACHE_PATH)
        except (OSError, ValueError):
            # Файл мог исчезнуть или повредиться после проверки.
            pass
        else:
            # Другая копия программы могла записать кэш для другой валюты.
            if data.get("base_code") == base:
                return data, "локальный кэш"

    data = get_currency_rates(base)
    save_to_file(data, CACHE_PATH)
    return data, "API"


def show_rates() -> None:
    """Показать курсы RUB, EUR и GBP, дату обновления и источник."""
    base = normalize_currency(input("Базовая валюта (например USD): "))
    data, source = get_rates_with_cache(base)
    for code in ("RUB", "EUR", "GBP"):
        rate = data["rates"].get(code)
        if rate is None:
            print(f"{code}: нет данных")
        else:
            print(f"1 {base} = {rate} {code}")
    updated = data.get("time_last_update_utc") or "дата не указана"
    print(f"Последнее обновление: {updated}")
    print(f"Источник данных: {source}")


def convert_currency() -> None:
    """Запросить валюты и сумму, затем показать результат конвертации."""
    base = normalize_currency(input("Исходная валюта: "))
    target = normalize_currency(input("Целевая валюта: "))
    amount = parse_amount(input("Сумма: "))
    data, source = get_rates_with_cache(base)

    rates = data["rates"]
    if target != base and target not in rates:
        raise ValueError(f"Валюта {target} отсутствует в списке доступных валют.")
    rate = 1 if target == base else rates[target]
    if type(rate) not in (int, float) or not 0 < rate < inf:
        raise ValueError(f"Для валюты {target} получен некорректный курс.")

    decimal_rate = Decimal(str(rate))
    with localcontext() as context:
        # Суммы длин двух множителей достаточно для точного произведения.
        context.prec = len(amount.as_tuple().digits) + len(decimal_rate.as_tuple().digits)
        result = amount * decimal_rate
    print(f"{amount:f} {base} = {result:.4f} {target}")
    print(f"Источник данных: {source}")


def list_currencies() -> None:
    """Показать отсортированные коды из ответа API для базовой валюты USD."""
    data, source = get_rates_with_cache("USD")
    print("Доступные валюты:")
    print(", ".join(sorted(data["rates"].keys())))
    print(f"Источник данных: {source}")


def refresh_rates() -> None:
    """Запросить новые курсы для выбранной базовой валюты и обновить кэш."""
    base = normalize_currency(input("Базовая валюта для обновления: "))
    _, source = get_rates_with_cache(base, force_refresh=True)
    print(f"Курсы для {base} обновлены.")
    print(f"Источник данных: {source}")


def main() -> None:
    """Показывать меню, выполнять операции и сообщать об ошибках."""
    actions = {
        "1": show_rates,
        "2": convert_currency,
        "3": list_currencies,
        "4": refresh_rates,
    }
    print("Курсы предоставляет ExchangeRate-API — https://www.exchangerate-api.com")
    while True:
        print(MENU)
        try:
            choice = input("Выберите действие: ").strip()
            if choice == "0":
                print("До свидания!")
                return
            action = actions.get(choice)
            if action is None:
                print("Выберите один из пунктов меню.")
                continue
            action()
        except (CurrencyAPIError, ValueError, OSError) as error:
            print(f"Ошибка: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            return
