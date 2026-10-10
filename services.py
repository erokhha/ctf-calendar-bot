"""Асинхронные JSON API и форматирование карточки CTF.

Форма ctf_text адаптирована из Wyndace/CTF-Calendar-BOT;
точный источник и границы переработки указаны в PROVENANCE.md.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import math
from urllib.parse import urlencode, urlsplit

import aiohttp

from config import Settings

log = logging.getLogger(__name__)
MSK = timezone(timedelta(hours=3))
DEFAULT_ENDPOINTS = {
    "cat": "https://api.thecatapi.com/v1/images/search",
    "weather": "https://api.openweathermap.org/data/2.5/weather",
    "ctf": "https://ctftime.org/api/v1/events/",
}


class ServiceError(Exception):
    def __init__(self, service: str, code: str, public_message: str):
        self.service = service
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


def valid_https_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and
                parsed.username is None and parsed.password is None and
                parsed.port in (None, 443) and not any(c.isspace() for c in value))
    except ValueError:
        return False


def avatar_url(user_id: int, username: str | None, first_name: str) -> str:
    # Дополнение: структурированная стабильная строка вместо timestamp.
    # SHA-256 не отправляет имя/ID открытым текстом стороннему генератору.
    seed = f"ctf-student-v1|id={user_id}|name={username or first_name}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"https://robohash.org/{digest}.png?" + urlencode({
        "set": "set1", "bgset": "bg1", "size": "400x400",
    })


def coordinates(lat: object, lon: object) -> tuple[float, float]:
    try:
        if isinstance(lat, bool) or isinstance(lon, bool):
            raise ValueError
        latitude, longitude = float(lat), float(lon)
        if not all(map(math.isfinite, (latitude, longitude))):
            raise ValueError
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError
        return latitude, longitude
    except (ValueError, TypeError) as exc:
        raise ServiceError("weather", "invalid_coordinates", "Координаты некорректны. Отправьте геолокацию ещё раз.") from exc


def finite_number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean instead of number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


@dataclass(frozen=True)
class Weather:
    city: str
    description: str
    temperature: float
    feels_like: float
    wind_speed: float

    def text(self) -> str:
        if self.wind_speed < 5:
            wind_note = "Слабый ветер."
        elif self.wind_speed < 10:
            wind_note = "Умеренный ветер."
        elif self.wind_speed < 20:
            wind_note = "Сильный ветер."
        else:
            wind_note = "Очень сильный ветер."
        return (f"Погода сейчас: {self.city}\n{self.description.capitalize()}\n"
                f"Температура: {self.temperature:g} °C (ощущается как {self.feels_like:g} °C)\n"
                f"Ветер: {self.wind_speed:g} м/с. {wind_note}\nИсточник: OpenWeatherMap.")


@dataclass(frozen=True)
class CTFEvent:
    event_id: int
    title: str
    format: str
    starts: datetime
    ends: datetime
    onsite: bool
    location: str
    url: str


def ctf_text(ctf: CTFEvent, first_text: str = "") -> str:
    """Сохранена структура карточки исходного бота; даты теперь из JSON, UTC+3."""
    if not ctf.onsite:
        place = "Будет проходить в онлайн-режиме."
    elif ctf.location:
        place = f"Будет проходить в {ctf.location}."
    else:
        place = "Место очного соревнования пока не указано."
    return (f"{first_text}Имя: {ctf.title}\nТип: {ctf.format}\n"
            f"Начало: {ctf.starts.astimezone(MSK):%d.%m.%Y в %H:%M}\n"
            f"Конец: {ctf.ends.astimezone(MSK):%d.%m.%Y в %H:%M}\n"
            f"Время: Москва (UTC+3).\n{place}\n"
            f"Ссылка на страницу CTFtime: {ctf.url}")


def parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing datetime")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt


class ApiServices:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings,
                 endpoints: dict[str, str] | None = None):
        self.session = session
        self.settings = settings
        # Подмена адресов используется только тестами с локальным HTTP-сервером.
        self.endpoints = dict(DEFAULT_ENDPOINTS if endpoints is None else endpoints)

    async def _json(self, service: str, *, params: dict | None = None,
                    headers: dict | None = None) -> object:
        try:
            async with self.session.get(self.endpoints[service], params=params, headers=headers) as response:
                if response.status in (401, 403):
                    raise ServiceError(service, "unauthorized", "Сервис сейчас недоступен. Попробуйте позже.")
                if response.status == 429:
                    raise ServiceError(service, "rate_limit", "Сервис ограничил частоту запросов. Повторите позже.")
                if response.status != 200:
                    raise ServiceError(service, f"http_{response.status}", "Внешний сервис временно недоступен. Повторите позже.")
                try:
                    return await response.json()
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise ServiceError(service, "invalid_json", "Сервис вернул некорректный JSON. Повторите позже.") from exc
        except ServiceError:
            raise
        except asyncio.TimeoutError as exc:
            raise ServiceError(service, "timeout", "Внешний сервис не ответил вовремя. Повторите позже.") from exc
        except (aiohttp.ClientError, ValueError, KeyError) as exc:
            raise ServiceError(service, "network", "Не удалось подключиться к внешнему сервису. Повторите позже.") from exc

    async def cat_url(self) -> str:
        # Дополнение: случайное фото только заданной породы; JSON разбирает aiohttp.
        data = await self._json("cat", params={
            "limit": 1, "breed_ids": self.settings.cat_breed, "order": "RAND",
            "mime_types": "jpg,png", "has_breeds": 1,
        }, headers={"x-api-key": self.settings.cat_api_key} if self.settings.cat_api_key else {})
        if not isinstance(data, list) or not data:
            raise ServiceError("cat", "empty", "Фотографии выбранной породы не найдены. Попробуйте позже.")
        item = data[0]
        if not isinstance(item, dict) or not valid_https_url(item.get("url")):
            raise ServiceError("cat", "invalid_url", "Сервис котиков вернул некорректную ссылку на изображение.")
        return item["url"]

    async def weather(self, lat: object, lon: object) -> Weather:
        latitude, longitude = coordinates(lat, lon)
        if not self.settings.weather_api_key:
            raise ServiceError("weather", "missing_key", "Погода пока недоступна. Попробуйте позже.")
        data = await self._json("weather", params={
            "lat": latitude, "lon": longitude, "appid": self.settings.weather_api_key,
            "units": "metric", "lang": "ru",
        })
        try:
            if not isinstance(data, dict):
                raise ValueError
            description = data["weather"][0]["description"]
            city = data.get("name") or "переданные координаты"
            if not isinstance(description, str) or not isinstance(city, str):
                raise ValueError
            wind = finite_number(data["wind"]["speed"])
            if wind < 0:
                raise ValueError
            return Weather(city[:120], description[:160], finite_number(data["main"]["temp"]),
                           finite_number(data["main"]["feels_like"]), wind)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ServiceError("weather", "invalid_schema", "В ответе погоды не хватает корректных данных. Повторите позже.") from exc

    async def ctf_events(self, now: datetime | None = None) -> list[CTFEvent]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must contain timezone")
        start = int(now.timestamp())
        finish = int((now + timedelta(days=self.settings.ctf_days)).timestamp())
        data = await self._json("ctf", params={
            "limit": self.settings.ctf_limit, "start": start, "finish": finish,
        }, headers={"User-Agent": "CTF-Calendar-Student/1.0 (educational bot)"})
        if not isinstance(data, list):
            raise ServiceError("ctf", "invalid_schema", "CTFtime вернул ответ неожиданного формата.")
        events: list[CTFEvent] = []
        seen: set[int] = set()
        for item in data:
            try:
                if not isinstance(item, dict):
                    raise ValueError
                event_id = item["id"]
                if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
                    raise ValueError
                title, event_format = item["title"], item["format"]
                location = item.get("location") or ""
                onsite = item["onsite"]
                if (not isinstance(title, str) or not title.strip() or not isinstance(event_format, str)
                        or not isinstance(location, str) or not isinstance(onsite, bool)):
                    raise ValueError
                starts, ends = parse_datetime(item["start"]), parse_datetime(item["finish"])
                if ends <= starts:
                    raise ValueError
                if not start <= starts.timestamp() <= finish or event_id in seen:
                    continue
                seen.add(event_id)
                events.append(CTFEvent(event_id, title[:180], event_format[:100], starts, ends,
                                       onsite, location[:180], f"https://ctftime.org/event/{event_id}/"))
            except (KeyError, TypeError, ValueError):
                log.warning("ctf_record_skipped reason=invalid_schema")
        if data and not events:
            raise ServiceError("ctf", "no_valid_events", "В ответе CTFtime нет корректных ближайших соревнований.")
        return sorted(events, key=lambda event: event.starts)[:self.settings.ctf_limit]
