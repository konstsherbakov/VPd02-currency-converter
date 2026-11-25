"""Точка входа конвертера и совместимые импорты для базового задания."""

from api_client import get_currency_rates
from cli import main
from storage import read_from_file, save_to_file

__all__ = ["get_currency_rates", "main", "read_from_file", "save_to_file"]


if __name__ == "__main__":
    main()
