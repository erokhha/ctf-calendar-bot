СТАТУС И ПРОИСХОЖДЕНИЕ ДОКАЗАТЕЛЬСТВ

test_results.json — машинно-читаемый результат реально выполненного run_local_checks.py:
47 unit/integration проверок, 0 failures, 0 errors. Внутри есть версии зависимостей,
время выполнения, имена проверок и SHA-256 проверенных Python-файлов.

test_output.txt — подлинный текст stdout тестового runner.

local_transcript.json / local_transcript.txt — реальные вызовы обработчиков проекта
с синтетическими входами. Сервис отвечает через настоящий aiohttp HTTP localhost;
Telegram заменён AsyncMock. Это НЕ реальные аккаунты и НЕ переписка Telegram.
Указанные фото — только URL в payload отправки, изображения не скачивались.

demo_command_output.txt — stdout/stderr выполненного demo_local.py.

logging_demo_output.txt — фактический stdout/stderr example_for_log.py:
WARNING пропускает WARNING/ERROR/CRITICAL (3 записи), INFO — 4, DEBUG — 5.
logging_warning.log, logging_info.log, logging_debug.log — соответствующие файлы.
Все сообщения помечены DEMO: строки ERROR/CRITICAL являются упражнением,
а не признаком реального падения приложения.

live_public_api_check_2026-10-10.json — реальные HTTP GET-проверки CTFtime,
TheCatAPI и RoboHash. Они подтверждают доступность ответов, но не доставку в Telegram.

live_telegram_bot_config_2026-10-10.json — реальные read-only ответы Telegram Bot API:
getMe, описание, короткое описание, семь команд, отсутствие webhook и наличие Botpic.
Значение токена и пользовательские Telegram ID в файл не включены.

В локальных transcript/test-прогонах сети Telegram, CTFtime, OpenWeatherMap и TheCatAPI
не вызывались. BotFather и публичные API проверены отдельно живыми запросами. Два живых
аккаунта, доставка сообщений и изображений, OpenWeatherMap с ключом и PythonAnywhere
остаются ручными проверками из MANUAL_CHECKLIST.md. Локальные результаты нельзя выдавать
за подтверждение этих ещё не выполненных внешних действий.
