СТАТУС И ПРОИСХОЖДЕНИЕ ДОКАЗАТЕЛЬСТВ

test_results.json — машинно-читаемый результат реально выполненного run_local_checks.py:
44 unit/integration проверки, 0 failures, 0 errors. Внутри есть версии зависимостей,
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

Сети Telegram, CTFtime, OpenWeatherMap и TheCatAPI в этих прогонах не вызывались.
BotFather, два живых аккаунта, настоящие изображения и PythonAnywhere остаются
отдельными ручными проверками из MANUAL_CHECKLIST.md. Подлинные результаты
локального исполнения не должны выдаваться за подтверждение этих внешних действий.
