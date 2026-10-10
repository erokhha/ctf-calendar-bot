"""Исполняемый протокол двух синтетических пользователей, без реального Telegram.

Вывод содержит фактические вызовы обработчиков и localhost HTTP-сервиса.
Это не скриншоты Telegram и не доказательство запуска с живыми аккаунтами.
"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from api_examples import DirectBotAPI, broadcast, remember_updates
import handlers
from tests.test_project import FIXED_NOW, FIXTURES, LocalServerCase, fake_update

ROOT = Path(__file__).resolve().parent


def replies(update) -> list[dict]:
    output = []
    for call in update.message.reply_text.call_args_list:
        markup = call.kwargs.get("reply_markup")
        output.append({"kind": "reply_text", "text": call.args[0] if call.args else call.kwargs["text"],
                       "reply_markup": markup.to_dict() if markup else None})
    for call in update.message.reply_photo.call_args_list:
        output.append({"kind": "reply_photo_payload_only", "photo_url": call.kwargs["photo"],
                       "caption": call.kwargs.get("caption", ""), "image_downloaded": False})
    return output


async def main() -> None:
    case = LocalServerCase()
    await case.asyncSetUp()
    try:
        event_service = case.api.ctf_events

        async def fixed_ctf():
            return await event_service(FIXED_NOW)

        case.api.ctf_events = fixed_ctf
        actions = []
        for index, user in enumerate(FIXTURES["users"]):
            context = SimpleNamespace(bot_data={"services": case.api, "store": case.store}, user_data={})
            for label, callback in (("/start", handlers.start), ("/id", handlers.id_command),
                                    ("Фото котика", handlers.cat_photo), ("Мой аватар", handlers.my_avatar),
                                    ("Погода", handlers.request_location), ("Погода в Москве", handlers.text_message),
                                    ("CTF-соревнования", handlers.show_ctf), ("/unknown", handlers.unknown_command)):
                update = fake_update(index, text=label)
                await handlers.remember_update(update, context)
                await callback(update, context)
                actions.append({"fixture_user": user["first_name"], "fixture_user_id": user["id"],
                                "input": label, "output": replies(update)})
                if label == "CTF-соревнования":
                    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
                    query = SimpleNamespace(data=markup.inline_keyboard[0][-1].callback_data,
                                            answer=AsyncMock(), edit_message_text=AsyncMock())
                    update.callback_query = query
                    await handlers.ctf_callback(update, context)
                    actions.append({"fixture_user": user["first_name"], "fixture_user_id": user["id"],
                                    "input": "inline: ▶", "output": [{"kind": "edit_message_text",
                                    "text": query.edit_message_text.call_args.kwargs["text"]}]})
            update = fake_update(index, location=SimpleNamespace(latitude=55.7558, longitude=37.6173))
            await handlers.handle_location(update, context)
            actions.append({"fixture_user": user["first_name"], "fixture_user_id": user["id"],
                            "input": "location: 55.7558, 37.6173 (fixture)", "output": replies(update)})
        # Сценарий отказа API: вызывается реальный обработчик и проверяется возврат меню.
        case.mode = "http_429"
        update = fake_update(text="Фото котика")
        await handlers.cat_photo(update, context)
        actions.append({"fixture_user": FIXTURES["users"][0]["first_name"], "input": "Фото котика; HTTP 429 fixture",
                        "output": replies(update)})
        case.mode = "ok"
        api = DirectBotAPI(case.session, "FIXTURE_TOKEN_NOT_REAL", case.base)
        updates = await api.get_updates()
        next_offset = remember_updates(updates, case.store)
        broadcast_result = await broadcast(api, case.store, "Привет [фикстура]", "https://example.org/FIXTURE.jpg", interval=0)
        case.mode = "blocked_first"
        blocked_result = await broadcast(api, case.store, "Привет [фикстура]", "https://example.org/FIXTURE.jpg", interval=0)
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "kind": "ACTUAL_LOCAL_HANDLER_EXECUTION_WITH_SYNTHETIC_INPUTS",
            "telegram_transport": "AsyncMock; messages not delivered",
            "external_api_transport": "actual aiohttp requests to loopback 127.0.0.1 fixture server",
            "live_telegram": False, "live_external_apis": False,
            "actions": actions, "http_requests": case.requests,
            "get_updates_fixture_result": updates, "next_offset": next_offset,
            "broadcast_fixture_results": broadcast_result, "blocked_user_fixture_results": blocked_result,
        }
        evidence = ROOT / "evidence"
        evidence.mkdir(exist_ok=True)
        (evidence / "local_transcript.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = ["ПРОТОКОЛ ЛОКАЛЬНОГО ИСПОЛНЕНИЯ. АККАУНТЫ И ДАННЫЕ API — ФИКСТУРЫ.",
                 "Реальные сообщения Telegram не отправлялись. Изображения не загружались.", ""]
        for action in actions:
            lines.append(f"[{action['fixture_user']}] Вход: {action['input']}")
            for response in action["output"]:
                if "text" in response:
                    lines.extend((response["text"], ""))
                else:
                    lines.extend(("Вызов sendPhoto (без доставки): " + response["photo_url"], response["caption"], ""))
        lines += ["Рассылка локальным фикстурам:", json.dumps(broadcast_result, ensure_ascii=False),
                  "Один адресат заблокировал бота (локальная фикстура HTTP 403):", json.dumps(blocked_result, ensure_ascii=False)]
        transcript = "\n".join(lines) + "\n"
        (evidence / "local_transcript.txt").write_text(transcript, encoding="utf-8")
        print(transcript)
        print(f"HTTP loopback requests: {len(case.requests)}; live Telegram: false")
    finally:
        await case.asyncTearDown()


if __name__ == "__main__":
    asyncio.run(main())
