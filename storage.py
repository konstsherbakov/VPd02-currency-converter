"""Сохранение, чтение и проверка кэша курсов валют."""

import json
from math import inf
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time


def save_to_file(data: dict, path: str | Path = "currency_rate.json") -> None:
    """Сохранить полный словарь ответа API в JSON-файл с кодировкой UTF-8."""
    if not isinstance(data, dict):
        raise TypeError("Для сохранения кэша нужен словарь.")

    target = Path(path)
    try:
        # Заменяем старый файл только после того, как новый записан целиком.
        with TemporaryDirectory(dir=target.parent) as directory:
            draft = Path(directory) / target.name
            with draft.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4, allow_nan=False)
            draft.replace(target)
    except OSError as error:
        raise OSError(f"Не удалось записать файл кэша «{path}».") from error
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(f"Не удалось преобразовать данные кэша «{path}» в JSON.") from error


def _reject_json_constant(value: str) -> None:
    """Отклонить специальные значения NaN и Infinity, которых нет в JSON."""
    raise ValueError(f"Недопустимое значение в JSON: {value}.")


def read_from_file(path: str | Path = "currency_rate.json") -> dict:
    """Прочитать JSON-файл в UTF-8 и вернуть сохранённый словарь."""
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            data = json.load(file, parse_constant=_reject_json_constant)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Файл кэша «{path}» не найден.") from error
    except OSError as error:
        raise OSError(f"Не удалось прочитать файл кэша «{path}».") from error
    except (ValueError, RecursionError) as error:
        raise ValueError(f"Файл кэша «{path}» содержит повреждённый JSON или неверную кодировку.") from error

    if not isinstance(data, dict):
        raise ValueError(f"Файл кэша «{path}» должен содержать словарь.")
    return data


def is_cache_valid(
    base: str,
    path: str | Path = "currency_rate.json",
    max_age_hours: float = 24,
) -> bool:
    """Проверить возраст файла, базовую валюту и курсы в сохранённом ответе."""
    try:
        age_seconds = time() - Path(path).stat().st_mtime
        # Возраст ровно на границе уже означает, что кэш устарел.
        if not 0 <= age_seconds < max_age_hours * 3600:
            return False
        data = read_from_file(path)
    except (OSError, ValueError):
        return False

    if data.get("result") != "success" or data.get("base_code") != base.strip().upper():
        return False

    rates = data.get("rates")
    if not isinstance(rates, dict) or not rates:
        return False

    # Точное сравнение типов исключает True и False, которые Python считает разновидностью int.
    return all(type(rate) in (int, float) and 0 < rate < inf for rate in rates.values())
