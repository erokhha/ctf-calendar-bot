"""Реальные вызовы к localhost + проверки обработчиков с AsyncMock Telegram.

Этот набор не вызывает Telegram, TheCatAPI, OpenWeatherMap или CTFtime.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from telegram import Chat, Update, User
from telegram.error import BadRequest, Forbidden

from api_examples import DirectApiError, DirectBotAPI, broadcast, remember_updates
from bot import build_application, post_init, post_shutdown
from config import ConfigurationError, Settings, load_settings
import handlers
from logging_setup import SecretFilter
from services import ApiServices, ServiceError, avatar_url, ctf_text, valid_https_url
from storage import ChatStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "tests/fixtures/api_responses.json").read_text())
FIXED_NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def fake_update(index: int = 0, text: str = "/start", location=None, callback=None):
    user = User(**FIXTURES["users"][index])
    chat = Chat(user.id, "private")
    message = SimpleNamespace(text=text, location=location, reply_text=AsyncMock(), reply_photo=AsyncMock())
    return SimpleNamespace(effective_user=user, effective_chat=chat, effective_message=message,
                           message=message, callback_query=callback)


class LocalServerCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = "ok"
        self.requests = []
        self.responses = deepcopy(FIXTURES)
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Path(self.tmp.name) / "chats.sqlite3")
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.respond)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        address = self.runner.addresses[0]
        self.base = f"http://127.0.0.1:{address[1]}"
        self.settings = Settings(weather_api_key="FIXTURE_WEATHER_KEY_NOT_REAL", cat_api_key="FIXTURE_CAT_KEY_NOT_REAL",
                                 timeout_seconds=0.1)
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.1), trust_env=False)
        self.api = ApiServices(self.session, self.settings, {key: f"{self.base}/{key}" for key in ("cat", "weather", "ctf")})

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        self.tmp.cleanup()

    async def respond(self, request):
        payload = await request.json() if request.method == "POST" else dict(request.query)
        self.requests.append({"path": request.path, "method": request.method, "payload": payload,
                              "cat_key_present": request.headers.get("x-api-key") == self.settings.cat_api_key})
        if self.mode.startswith("http_"):
            return web.json_response({"error": "fixture"}, status=int(self.mode.split("_")[1]))
        if self.mode == "bad_json":
            return web.Response(text="{", content_type="application/json")
        if self.mode == "html":
            return web.Response(text="<html>fixture</html>", content_type="text/html")
        if self.mode == "timeout":
            import asyncio
            await asyncio.sleep(0.2)
        key = request.path.rsplit("/", 1)[-1]
        if key == "getUpdates":
            return web.json_response({"ok": True, "result": self.responses["updates"]})
        if key in ("sendMessage", "sendPhoto"):
            if self.mode == "blocked_first" and payload["chat_id"] == 900000001:
                return web.json_response({"ok": False, "error_code": 403, "description": "fixture blocked"}, status=403)
            return web.json_response({"ok": True, "result": {"message_id": len(self.requests), "chat": {"id": payload["chat_id"]}}})
        return web.json_response(self.responses.get(key, {}))

    async def expect_service_error(self, awaitable, code):
        with self.assertRaises(ServiceError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)


class ServiceTests(LocalServerCase):
    async def test_cat_breed_random_params_and_api_key(self):
        self.assertEqual(await self.api.cat_url(), FIXTURES["cat"][0]["url"])
        request = self.requests[-1]
        self.assertEqual(request["payload"]["breed_ids"], "beng")
        self.assertEqual(request["payload"]["order"], "RAND")
        self.assertTrue(request["cat_key_present"])

    async def test_cat_empty_list(self):
        self.responses["cat"] = []
        await self.expect_service_error(self.api.cat_url(), "empty")

    async def test_cat_empty_and_unsafe_urls(self):
        for url in ("", "file:///etc/passwd", "http://example.org/cat.jpg", "https://name:pass@example.org/a", None):
            with self.subTest(url=url):
                self.responses["cat"] = [{"url": url}]
                await self.expect_service_error(self.api.cat_url(), "invalid_url")

    async def test_http_401_403_429_500(self):
        for status, code in ((401, "unauthorized"), (403, "unauthorized"), (429, "rate_limit"), (500, "http_500")):
            with self.subTest(status=status):
                self.mode = f"http_{status}"
                await self.expect_service_error(self.api.cat_url(), code)

    async def test_invalid_json_and_content_type(self):
        for mode in ("bad_json", "html"):
            with self.subTest(mode=mode):
                self.mode = mode
                await self.expect_service_error(self.api.cat_url(), "invalid_json")

    async def test_timeout(self):
        self.mode = "timeout"
        await self.expect_service_error(self.api.cat_url(), "timeout")

    async def test_invalid_request_url(self):
        self.api.endpoints["cat"] = ""
        await self.expect_service_error(self.api.cat_url(), "network")

    async def test_network_failure(self):
        await self.site.stop()
        await self.expect_service_error(self.api.cat_url(), "network")

    async def test_weather_coordinates_units_and_fields(self):
        weather = await self.api.weather(55.7558, 37.6173)
        self.assertEqual(weather.temperature, 8.5)
        self.assertIn("8.5 °C", weather.text())
        self.assertIn("3.2 м/с", weather.text())
        params = self.requests[-1]["payload"]
        self.assertEqual((params["units"], params["lang"]), ("metric", "ru"))
        self.assertEqual(float(params["lat"]), 55.7558)

    async def test_weather_missing_key_no_http(self):
        self.api.settings = replace(self.settings, weather_api_key="")
        await self.expect_service_error(self.api.weather(55, 37), "missing_key")
        self.assertEqual(self.requests, [])

    async def test_weather_invalid_coordinates_no_http(self):
        for lat, lon in ((91, 0), (0, 181), (None, 0), (float("nan"), 0), (0, float("inf")), (True, 2)):
            with self.subTest(latitude=lat, longitude=lon):
                await self.expect_service_error(self.api.weather(lat, lon), "invalid_coordinates")
        self.assertEqual(self.requests, [])

    async def test_weather_incomplete_and_invalid_schema(self):
        for data in ({}, {"weather": []}, [], {"weather": [{"description": "ясно"}],
                                                "main": {"temp": None, "feels_like": 1}, "wind": {"speed": 1}}):
            with self.subTest(data=data):
                self.responses["weather"] = data
                await self.expect_service_error(self.api.weather(55, 37), "invalid_schema")

    async def test_ctf_dynamic_window_and_card(self):
        events = await self.api.ctf_events(FIXED_NOW)
        self.assertEqual(len(events), 2)
        params = self.requests[-1]["payload"]
        self.assertEqual(int(params["start"]), int(FIXED_NOW.timestamp()))
        self.assertEqual(int(params["finish"]) - int(params["start"]), 90 * 86400)
        self.assertEqual(params["limit"], "10")
        text = ctf_text(events[0])
        self.assertIn("10.10.2026 в 13:00", text)
        self.assertIn("онлайн-режиме", text)
        self.assertIn("Учебная аудитория", ctf_text(events[1]))

    async def test_ctf_empty_and_invalid_response(self):
        self.responses["ctf"] = []
        self.assertEqual(await self.api.ctf_events(FIXED_NOW), [])
        self.responses["ctf"] = {}
        await self.expect_service_error(self.api.ctf_events(FIXED_NOW), "invalid_schema")

    async def test_ctf_partial_bad_records_are_skipped(self):
        self.responses["ctf"].append({"title": "broken fixture"})
        self.assertEqual(len(await self.api.ctf_events(FIXED_NOW)), 2)

    async def test_ctf_all_bad_records_have_friendly_error(self):
        self.responses["ctf"] = [{"title": "broken fixture"}]
        await self.expect_service_error(self.api.ctf_events(FIXED_NOW), "no_valid_events")

    async def test_ctf_end_before_start_is_rejected(self):
        item = deepcopy(FIXTURES["ctf"][0])
        item["finish"] = "2026-10-01T12:00:00Z"
        self.responses["ctf"] = [item]
        await self.expect_service_error(self.api.ctf_events(FIXED_NOW), "no_valid_events")


class HandlerTests(LocalServerCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.context = SimpleNamespace(bot_data={"services": self.api, "store": self.store}, user_data={})

    async def test_personalized_start_for_two_synthetic_users(self):
        for index in (0, 1):
            update = fake_update(index)
            await handlers.remember_update(update, self.context)
            await handlers.start(update, self.context)
            result = update.message.reply_text.call_args
            self.assertIn(FIXTURES["users"][index]["first_name"], result.args[0])
            self.assertTrue(result.kwargs["reply_markup"].resize_keyboard)
        self.assertEqual(self.store.active_ids(), [900000001, 900000002])

    async def test_id_user_and_chat_for_two_synthetic_users(self):
        for index in (0, 1):
            update = fake_update(index)
            await handlers.id_command(update, self.context)
            self.assertIn(f"Ваш ID: {900000001 + index}", update.message.reply_text.call_args.args[0])
            self.assertIn(f"ID чата: {900000001 + index}", update.message.reply_text.call_args.args[0])

    async def test_photo_and_avatar_are_send_photo_calls(self):
        update = fake_update()
        await handlers.cat_photo(update, self.context)
        self.assertEqual(update.message.reply_photo.call_args.kwargs["photo"], FIXTURES["cat"][0]["url"])
        await handlers.my_avatar(update, self.context)
        self.assertIn("set=set1&bgset=bg1", update.message.reply_photo.call_args.kwargs["photo"])

    async def test_telegram_photo_bad_request_returns_menu(self):
        update = fake_update()
        update.message.reply_photo.side_effect = BadRequest("fixture image unavailable")
        await handlers.cat_photo(update, self.context)
        self.assertIn("не смог загрузить", update.message.reply_text.call_args.args[0])
        self.assertIn("reply_markup", update.message.reply_text.call_args.kwargs)

    async def test_location_button_and_weather_return_menu(self):
        update = fake_update(location=SimpleNamespace(latitude=55.7558, longitude=37.6173))
        await handlers.request_location(update, self.context)
        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        self.assertTrue(markup.keyboard[0][0].request_location)
        await handlers.handle_location(update, self.context)
        response = update.message.reply_text.call_args
        self.assertIn("по переданным координатам", response.args[0])
        self.assertEqual(response.kwargs["reply_markup"], handlers.main_menu())

    async def test_missing_location_is_handled_without_http(self):
        update = fake_update(location=None)
        await handlers.handle_location(update, self.context)
        self.assertIn("Координаты не получены", update.message.reply_text.call_args.args[0])
        self.assertEqual(self.requests, [])

    async def test_moscow_is_explicit_fallback(self):
        update = fake_update(text="Погода в Москве")
        await handlers.text_message(update, self.context)
        self.assertIn("это не ваша геолокация", update.message.reply_text.call_args.args[0])
        self.assertEqual(float(self.requests[-1]["payload"]["lat"]), 55.7558)

    async def test_weather_failure_restores_menu(self):
        update = fake_update(location=SimpleNamespace(latitude=55, longitude=37))
        self.mode = "http_401"
        await handlers.handle_location(update, self.context)
        result = update.message.reply_text.call_args
        self.assertIn("Сервис сейчас недоступен", result.args[0])
        self.assertEqual(result.kwargs["reply_markup"], handlers.main_menu())

    async def test_unknown_input_has_help_and_keyboard(self):
        for text in ("/unknown", "неизвестный текст"):
            update = fake_update(text=text)
            await handlers.text_message(update, self.context)
            self.assertIn("/help", update.message.reply_text.call_args.args[0])

    async def test_ctf_inline_snapshot_navigation_and_stale_callback(self):
        self.api.ctf_events = AsyncMock(return_value=await self.api.ctf_events(FIXED_NOW))
        update = fake_update()
        await handlers.show_ctf(update, self.context)
        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        next_data = markup.inline_keyboard[0][-1].callback_data
        query = SimpleNamespace(data=next_data, answer=AsyncMock(), edit_message_text=AsyncMock())
        update.callback_query = query
        await handlers.ctf_callback(update, self.context)
        self.assertIn("CTF Beta", query.edit_message_text.call_args.kwargs["text"])
        self.assertEqual(self.api.ctf_events.await_count, 1)
        query.data = "ctf:expired:0"
        await handlers.ctf_callback(update, self.context)
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_ctf_callbacks_reject_bad_index_and_other_users_snapshot(self):
        update = fake_update(callback=SimpleNamespace(data="ctf:any:-1", answer=AsyncMock(), edit_message_text=AsyncMock()))
        for data in ("ctf:any:-1", "ctf:any:9999", "ctf:any:NaN", "ctf:any:0:extra"):
            update.callback_query.data = data
            await handlers.ctf_callback(update, self.context)
        self.assertEqual(update.callback_query.edit_message_text.await_count, 0)

    async def test_ctf_same_page_bad_request_does_not_crash(self):
        events = await self.api.ctf_events(FIXED_NOW)
        self.context.user_data["ctf_snapshots"] = {"fixed": events}
        query = SimpleNamespace(data="ctf:fixed:0", answer=AsyncMock(), edit_message_text=AsyncMock(side_effect=BadRequest("Message is not modified")))
        await handlers.ctf_callback(fake_update(callback=query), self.context)
        query.answer.assert_awaited_once()


class DirectAPITests(LocalServerCase):
    async def test_broadcast_rejects_empty_recipient_list(self):
        api = DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base)
        with self.assertRaises(ConfigurationError):
            await broadcast(
                api, self.store, "Привет [фикстура]", "https://example.org/FIXTURE.jpg", interval=0
            )
        self.assertEqual(self.requests, [])

    async def test_get_updates_extracts_only_private_chat_ids(self):
        api = DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base)
        updates = await api.get_updates()
        self.assertEqual(remember_updates(updates, self.store), 1004)
        self.assertEqual(self.store.active_ids(), [900000001, 900000002])
        self.assertEqual(self.requests[0]["method"], "GET")

    async def test_direct_send_message_and_photo(self):
        api = DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base)
        result = await api.send_message(900000001, "Привет [фикстура]")
        self.assertIn("message_id", result)
        await api.send_photo(900000001, "https://example.org/FIXTURE.jpg")
        self.assertTrue(self.requests[-1]["path"].endswith("/sendPhoto"))
        self.assertEqual(self.requests[-1]["payload"]["chat_id"], 900000001)

    async def test_broadcast_hello_and_photo_to_two_fixtures(self):
        remember_updates(FIXTURES["updates"], self.store)
        api = DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base)
        results = await broadcast(api, self.store, "Привет [фикстура]", "https://example.org/FIXTURE.jpg", interval=0)
        self.assertEqual([r["status"] for r in results], ["sent", "sent"])
        self.assertEqual(len(self.requests), 4)
        self.assertEqual([r["sent_steps"] for r in results], [["message", "photo"], ["message", "photo"]])

    async def test_broadcast_blocked_first_continues_second(self):
        remember_updates(FIXTURES["updates"], self.store)
        self.mode = "blocked_first"
        results = await broadcast(DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base), self.store,
                                  "Привет [фикстура]", "https://example.org/FIXTURE.jpg", interval=0)
        self.assertEqual([r["status"] for r in results], ["failed", "sent"])
        self.assertEqual(self.store.active_ids(), [900000002])

    async def test_direct_malformed_json_and_timeout(self):
        api = DirectBotAPI(self.session, "FIXTURE_TOKEN", self.base)
        for mode in ("bad_json", "timeout"):
            self.mode = mode
            with self.assertRaises(DirectApiError):
                await api.get_updates()


class ConfigurationAndStructureTests(unittest.TestCase):
    def test_missing_required_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError):
                load_settings(env_file="/nonexistent/fixture.env")

    def test_invalid_numeric_configuration(self):
        for value in ("oops", "NaN", "-1", "999"):
            with patch.dict(os.environ, {"HTTP_TIMEOUT_SECONDS": value}, clear=True):
                with self.assertRaises(ConfigurationError):
                    load_settings(require_token=False, env_file="/nonexistent/fixture.env")

    def test_dotenv_reads_local_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "test.env"
            env_file.write_text("TELEGRAM_BOT_TOKEN=123456:FIXTURE_ONLY_NOT_REAL\nCAT_BREED=beng\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(env_file=str(env_file))
                self.assertEqual(settings.cat_breed, "beng")
                self.assertTrue(settings.telegram_token.endswith("NOT_REAL"))

    def test_empty_primary_names_fall_back_to_legacy_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "test.env"
            env_file.write_text(
                "TELEGRAM_BOT_TOKEN=\nTOKEN=123456:LEGACY_FIXTURE_ONLY\n"
                "WEATHER_API_KEY=\nTOKEN_WEATHER=LEGACY_WEATHER_FIXTURE\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(env_file=env_file)
            self.assertEqual(settings.telegram_token, "123456:LEGACY_FIXTURE_ONLY")
            self.assertEqual(settings.weather_api_key, "LEGACY_WEATHER_FIXTURE")

    def test_relative_runtime_paths_resolve_from_project_directory(self):
        with patch.dict(
            os.environ,
            {"DATABASE_PATH": "state/chats.sqlite3", "LOG_PATH": "state/bot.log"},
            clear=True,
        ):
            settings = load_settings(require_token=False, env_file="missing-fixture.env")
        self.assertEqual(settings.db_path, ROOT / "state/chats.sqlite3")
        self.assertEqual(settings.log_path, ROOT / "state/bot.log")

    def test_avatar_is_deterministic_and_user_specific(self):
        first = avatar_url(900000001, "fixture_erokhina", "fixture")
        self.assertEqual(first, avatar_url(900000001, "fixture_erokhina", "fixture"))
        self.assertNotEqual(first, avatar_url(900000002, "fixture_peer", "fixture"))
        self.assertNotIn("900000001", first)
        self.assertNotIn("fixture_erokhina", first)
        self.assertIn("set=set1&bgset=bg1", first)

    def test_url_validation(self):
        self.assertTrue(valid_https_url("https://example.org/p.png"))
        for value in ("", "javascript:alert(1)", "https://host:invalid/a", None, "https://host/a b"):
            self.assertFalse(valid_https_url(value))

    def test_secret_filter_removes_token_and_api_key(self):
        record = logging.LogRecord("fixture", logging.ERROR, "", 1,
                                   "bot123456:FIXTURE_TOKEN appid=%s", ("FIXTURE_WEATHER",), None)
        SecretFilter(("FIXTURE_TOKEN", "FIXTURE_WEATHER")).filter(record)
        self.assertNotIn("FIXTURE_TOKEN", record.getMessage())
        self.assertNotIn("FIXTURE_WEATHER", record.getMessage())

    def test_broadcast_requires_confirm_before_token_or_network(self):
        result = subprocess.run([sys.executable, "api_examples.py", "broadcast", "--photo-url", "https://example.org/FIXTURE.jpg"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Рассылка не выполнена", result.stderr)

    def test_import_main_has_no_network_or_polling(self):
        result = subprocess.run([sys.executable, "-c", "import main; print('IMPORT_OK_NO_POLLING')"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("IMPORT_OK_NO_POLLING", result.stdout)

    def test_application_registers_commands_and_callbacks_without_network(self):
        # Изоляция от служебных SOCKS-прокси хост-машины; сетевых запросов здесь нет.
        with patch.dict(os.environ, {}, clear=True):
            app = build_application(Settings(telegram_token="123456:FIXTURE_ONLY_NOT_REAL"))
        names = {type(handler).__name__ for group in app.handlers.values() for handler in group}
        self.assertTrue({"TypeHandler", "CommandHandler", "CallbackQueryHandler", "MessageHandler"}.issubset(names))
        self.assertIs(app.post_shutdown, post_shutdown)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_created_and_closed_in_application_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = SimpleNamespace(bot_data={"settings": Settings(db_path=Path(tmp) / "chats.sqlite3")},
                                  bot=SimpleNamespace(set_my_commands=AsyncMock()))
            await post_init(app)
            session = app.bot_data["session"]
            self.assertFalse(session.closed)
            self.assertTrue(session.trust_env)
            await post_shutdown(app)
            self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
