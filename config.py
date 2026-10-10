"""Конфигурация учебного проекта. Импорт модуля не запускает сеть или бота."""

from dataclasses import dataclass
import math
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent


class ConfigurationError(ValueError):
    """Сообщение этой ошибки можно показывать без раскрытия секретов."""


@dataclass(frozen=True)
class Settings:
    telegram_token: str = ""
    weather_api_key: str = ""
    cat_api_key: str = ""
    cat_breed: str = "beng"
    timeout_seconds: float = 12.0
    ctf_limit: int = 10
    ctf_days: int = 90
    db_path: Path = Path("data/chats.sqlite3")
    log_path: Path = Path("logs/bot.log")
    log_level: str = "INFO"
    telegram_proxy: str | None = None


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


def load_settings(*, require_token: bool = True, env_file: str | Path = ".env") -> Settings:
    # Дополнение: секреты читаются из .env; переменные процесса имеют приоритет.
    load_dotenv(project_path(env_file), override=False)
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN", "")).strip()
    if require_token and (not token or ":" not in token or "replace" in token.lower()):
        raise ConfigurationError("Заполните TELEGRAM_BOT_TOKEN в .env токеном BotFather.")
    try:
        timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12"))
        limit = int(os.getenv("CTF_LIMIT", "10"))
        days = int(os.getenv("CTF_DAYS", "90"))
    except ValueError as exc:
        raise ConfigurationError("HTTP_TIMEOUT_SECONDS, CTF_LIMIT и CTF_DAYS должны быть числами.") from exc
    if not math.isfinite(timeout) or not 0.01 <= timeout <= 60:
        raise ConfigurationError("HTTP_TIMEOUT_SECONDS должен быть от 0.01 до 60.")
    if not 1 <= limit <= 100 or not 1 <= days <= 366:
        raise ConfigurationError("CTF_LIMIT: 1–100; CTF_DAYS: 1–366.")
    breed = os.getenv("CAT_BREED", "beng").strip()
    if not breed.isascii() or not breed.isalpha() or not 2 <= len(breed) <= 8:
        raise ConfigurationError("CAT_BREED должен содержать код породы, например beng.")
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("LOG_LEVEL должен быть DEBUG, INFO, WARNING, ERROR или CRITICAL.")
    return Settings(
        telegram_token=token,
        weather_api_key=(os.getenv("WEATHER_API_KEY") or os.getenv("TOKEN_WEATHER", "")).strip(),
        cat_api_key=os.getenv("CAT_API_KEY", "").strip(),
        cat_breed=breed,
        timeout_seconds=timeout,
        ctf_limit=limit,
        ctf_days=days,
        db_path=project_path(os.getenv("DATABASE_PATH", "data/chats.sqlite3")),
        log_path=project_path(os.getenv("LOG_PATH", "logs/bot.log")),
        log_level=level,
        telegram_proxy=os.getenv("TELEGRAM_PROXY_URL") or None,
    )
