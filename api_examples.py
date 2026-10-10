"""Прямые HTTP-запросы Bot API и явная учебная рассылка известным чатам.

Никакие команды не выполняются при импорте. Рассылка требует --confirm.
getUpdates нельзя запускать одновременно с main.py для того же токена.
"""

import argparse
import asyncio
import json
import logging
from typing import Any

import aiohttp

from config import ConfigurationError, load_settings
from logging_setup import configure_logging
from services import valid_https_url
from storage import ChatStore

log = logging.getLogger(__name__)


class DirectApiError(Exception):
    def __init__(self, code: int, *, retry_after: int = 0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram Bot API: ошибка {code}.")


class DirectBotAPI:
    def __init__(self, session: aiohttp.ClientSession, token: str,
                 base_url: str = "https://api.telegram.org"):
        self.session = session
        self._url = f"{base_url.rstrip('/')}/bot{token}"

    async def call(self, method: str, payload: dict[str, Any] | None = None,
                   *, http_method: str = "POST") -> Any:
        if method not in {"getUpdates", "sendMessage", "sendPhoto"}:
            raise ValueError("Unsupported demonstration method")
        kwargs = {"params": payload} if http_method == "GET" else {"json": payload}
        try:
            async with self.session.request(http_method, f"{self._url}/{method}", **kwargs) as response:
                try:
                    body = await response.json()
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise DirectApiError(502) from exc
                if not isinstance(body, dict):
                    raise DirectApiError(502)
                if response.status != 200 or body.get("ok") is not True:
                    code = body.get("error_code", response.status)
                    code = code if isinstance(code, int) else response.status
                    parameters = body.get("parameters")
                    retry_after = parameters.get("retry_after", 0) if isinstance(parameters, dict) else 0
                    retry_after = retry_after if isinstance(retry_after, int) and 0 < retry_after <= 30 else 0
                    raise DirectApiError(code, retry_after=retry_after)
                if "result" not in body:
                    raise DirectApiError(502)
                return body["result"]
        except DirectApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise DirectApiError(503) from exc

    async def get_updates(self, offset: int | None = None) -> list[dict]:
        payload: dict[str, Any] = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload, http_method="GET")
        if not isinstance(result, list):
            raise DirectApiError(502)
        return result

    async def send_message(self, chat_id: int, text: str) -> Any:
        return await self.call("sendMessage", {"chat_id": chat_id, "text": text})

    async def send_photo(self, chat_id: int, photo_url: str, caption: str = "") -> Any:
        if not valid_https_url(photo_url):
            raise ValueError("Изображение должно иметь корректный HTTPS URL.")
        return await self.call("sendPhoto", {"chat_id": chat_id, "photo": photo_url, "caption": caption})


def remember_updates(updates: list[dict], store: ChatStore) -> int | None:
    """Сохраняет только личные чаты и возвращает offset следующего обновления."""
    max_update: int | None = None
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update = update_id if max_update is None else max(max_update, update_id)
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if isinstance(chat, dict) and isinstance(chat.get("id"), int):
            store.remember(chat["id"], chat.get("type", ""))
    return max_update + 1 if max_update is not None else None


async def broadcast(api: DirectBotAPI, store: ChatStore, text: str, photo_url: str,
                    *, interval: float = 0.1) -> list[dict]:
    if not valid_https_url(photo_url):
        raise ValueError("Изображение должно иметь корректный HTTPS URL.")
    results = []
    for chat_id in store.active_ids():
        sent_steps = []
        try:
            for method in ("message", "photo"):
                for attempt in range(2):
                    try:
                        if method == "message":
                            await api.send_message(chat_id, text)
                        else:
                            await api.send_photo(chat_id, photo_url, "Учебная рассылка: изображение.")
                        sent_steps.append(method)
                        break
                    except DirectApiError as exc:
                        if exc.code == 429 and exc.retry_after and attempt == 0:
                            await asyncio.sleep(exc.retry_after)
                            continue
                        raise
            results.append({"chat_id": chat_id, "status": "sent", "sent_steps": sent_steps})
            log.info("broadcast_recipient status=sent")
        except DirectApiError as exc:
            if exc.code == 403:
                store.deactivate(chat_id)
            results.append({"chat_id": chat_id, "status": "failed", "code": exc.code, "sent_steps": sent_steps})
            log.warning("broadcast_recipient status=failed code=%s", exc.code)
        if interval:
            await asyncio.sleep(interval)
    return results


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    updates = sub.add_parser("get-updates", help="Прочитать очередь и сохранить известные личные chat_id")
    updates.add_argument("--offset", type=int)
    message = sub.add_parser("send-message", help="Отправить одному известному личному чату")
    message.add_argument("chat_id", type=int)
    message.add_argument("text")
    photo = sub.add_parser("send-photo", help="Отправить изображение одному известному личному чату")
    photo.add_argument("chat_id", type=int)
    photo.add_argument("photo_url")
    bulk = sub.add_parser("broadcast", help="Приветствие и изображение всем известным личным чатам")
    bulk.add_argument("--text", default="Привет! Это учебная проверка рассылки CTF-календаря.")
    bulk.add_argument("--photo-url", required=True)
    bulk.add_argument("--confirm", action="store_true", help="Явно разрешить эту рассылку")
    return parser


async def run_cli(args: argparse.Namespace) -> None:
    settings = load_settings()
    configure_logging(settings)
    store = ChatStore(settings.db_path)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.timeout_seconds),
                                     trust_env=True) as session:
        api = DirectBotAPI(session, settings.telegram_token)
        if args.command == "get-updates":
            updates = await api.get_updates(args.offset)
            next_offset = remember_updates(updates, store)
            # Тексты сообщений и токен не печатаются. Поля result показывает локальный fixture.
            print(json.dumps({"received": len(updates), "known_private_chat_ids": store.active_ids(),
                              "next_offset": next_offset}, ensure_ascii=False, indent=2))
        elif args.command == "broadcast":
            result = await broadcast(api, store, args.text, args.photo_url)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if args.chat_id not in store.active_ids():
                raise ConfigurationError("Сначала пользователь должен написать боту; получите его chat_id через get-updates.")
            if args.command == "send-message":
                result = await api.send_message(args.chat_id, args.text)
            else:
                result = await api.send_photo(args.chat_id, args.photo_url)
            message_id = result.get("message_id") if isinstance(result, dict) else None
            print(json.dumps({"ok": True, "message_id": message_id}, ensure_ascii=False))


def main() -> None:
    parser = argument_parser()
    args = parser.parse_args()
    if args.command == "broadcast" and not args.confirm:
        parser.error("Рассылка не выполнена. Для явного запуска добавьте --confirm.")
    try:
        asyncio.run(run_cli(args))
    except (ConfigurationError, DirectApiError, ValueError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
