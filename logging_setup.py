"""Журнал в консоли и файле; HTTP URL и значения ключей не раскрываются."""

import logging
from logging.handlers import RotatingFileHandler
import re

from config import Settings


class SecretFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", message)
        record.msg, record.args = message, ()
        # Не выводим непроверенные traceback/исключения библиотек: URL может содержать токен.
        record.exc_info = None
        record.exc_text = None
        return True


def configure_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    secret_filter = SecretFilter((settings.telegram_token, settings.weather_api_key, settings.cat_api_key))
    handlers = [logging.StreamHandler(),
                RotatingFileHandler(settings.log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(secret_filter)
    root = logging.getLogger()
    for old in root.handlers[:]:
        root.removeHandler(old)
        old.close()
    root.setLevel(settings.log_level)
    for handler in handlers:
        root.addHandler(handler)
    # HTTPX INFO содержит URL Telegram с токеном; выводится только WARNING+.
    for name in ("httpx", "httpcore", "aiohttp", "telegram"):
        logging.getLogger(name).setLevel(logging.WARNING)
