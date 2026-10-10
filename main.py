"""Запуск: python main.py. Импорт этого файла не делает запросов к Telegram."""

from bot import run_bot
from config import ConfigurationError


if __name__ == "__main__":
    try:
        run_bot()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
