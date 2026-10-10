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

live_telegram_single_account_2026-10-10.json — реальная проверка одного личного аккаунта:
/start, /help, /myid, неизвестная команда, reply-клавиатура, CTFtime 1/10 → 2/10,
RoboHash и TheCatAPI. При остановленном polling также выполнены getUpdates с offset,
sendMessage и sendPhoto. Токен, user ID и chat ID в файл не включены.

screenshots/live_start_help_2026-10-10.jpg — профиль бота, /start и /help.
screenshots/live_ctftime_card_2_of_10_2026-10-10.jpg — вторая карточка CTFtime и кнопки.
Снимок сделан до финального упрощения подписей карточки: он подтверждает живой запрос
и навигацию, но точный текущий текст карточки проверяется тестами и local_transcript.
screenshots/live_media_robohash_catapi_2026-10-10.jpg — реально доставленные изображения.
screenshots/live_direct_bot_api_sendmessage_sendphoto_2026-10-10.jpg — сообщения,
отправленные прямыми методами sendMessage и sendPhoto.

В локальных transcript/test-прогонах сети Telegram, CTFtime, OpenWeatherMap и TheCatAPI
не вызывались. BotFather, публичные API и один личный Telegram-аккаунт проверены отдельно
живыми запросами. Второй аккаунт, рассылка двум адресатам, OpenWeatherMap с ключом и
PythonAnywhere остаются ручными проверками из MANUAL_CHECKLIST.md. Проект опубликован
как самостоятельный публичный репозиторий https://github.com/erokhha/ctf-calendar-bot;
это не fork. Локальные результаты нельзя выдавать за подтверждение ещё не выполненных
внешних действий.
