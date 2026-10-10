"""Сборка приложения и управление жизненным циклом HTTP-сессии."""

import logging

import aiohttp
from telegram import BotCommand, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          MessageHandler, TypeHandler, filters)
from telegram.request import HTTPXRequest

from config import Settings, load_settings
from handlers import (ctf_callback, error_handler, handle_location, help_command,
                      id_command, remember_update, request_location, show_ctf,
                      start, text_message, unknown_command)
from logging_setup import configure_logging
from services import ApiServices
from storage import ChatStore

log = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=settings.timeout_seconds),
        trust_env=True,  # В том числе HTTP(S)_PROXY в PythonAnywhere.
    )
    app.bot_data["session"] = session
    app.bot_data["services"] = ApiServices(session, settings)
    app.bot_data["store"] = ChatStore(settings.db_path)
    await app.bot.set_my_commands([
        BotCommand("start", "Открыть меню"), BotCommand("help", "Справка"),
        BotCommand("id", "Мой ID и ID чата"), BotCommand("ctf", "Ближайшие CTF"),
        BotCommand("weather", "Погода по геолокации"),
    ])
    log.info("bot_ready mode=polling")


async def post_shutdown(app: Application) -> None:
    session = app.bot_data.get("session")
    if session is not None and not session.closed:
        await session.close()
    log.info("bot_stopped session_closed=true")


def build_application(settings: Settings) -> Application:
    def request(read_timeout: float) -> HTTPXRequest:
        return HTTPXRequest(read_timeout=read_timeout,
                            connect_timeout=settings.timeout_seconds,
                            proxy=settings.telegram_proxy,
                            httpx_kwargs={"trust_env": True})
    app = (Application.builder().token(settings.telegram_token)
           .request(request(settings.timeout_seconds))
           .get_updates_request(request(35))
           .concurrent_updates(False)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.bot_data["settings"] = settings
    app.add_handler(TypeHandler(Update, remember_update), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler(["id", "myid"], id_command))
    app.add_handler(CommandHandler(["ctf", "showctf"], show_ctf))
    app.add_handler(CommandHandler("weather", request_location))
    app.add_handler(CallbackQueryHandler(ctf_callback, pattern=r"^ctf:"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    return app


def run_bot() -> None:
    settings = load_settings()
    configure_logging(settings)
    app = build_application(settings)
    # getUpdates обрабатывает только нужные типы. Список не сбрасывает очередь.
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=False)
