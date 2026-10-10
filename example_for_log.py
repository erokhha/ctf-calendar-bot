"""Изолированный пример пяти уровней; не обращается к Telegram."""

import logging
from pathlib import Path

from config import Settings
from logging_setup import configure_logging


def main() -> None:
    for level in ("WARNING", "INFO", "DEBUG"):
        configure_logging(Settings(log_path=Path(f"evidence/logging_{level.lower()}.log"), log_level=level))
        log = logging.getLogger("logging_demo")
        print(f"LOGGING DEMO: threshold={level}; console + file", flush=True)
        log.debug("DEMO: подробности отладки")
        log.info("DEMO: действие успешно завершено")
        log.warning("DEMO: внешняя служба отвечает медленно")
        log.error("DEMO: контролируемый пример ошибки")
        log.critical("DEMO: контролируемый пример критического события")


if __name__ == "__main__":
    main()
