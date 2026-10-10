"""Команды, reply-клавиатура, геолокация и inline-навигация по CTF."""

import logging
import secrets

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, Update)
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from services import ApiServices, ServiceError, avatar_url, ctf_text
from storage import ChatStore

log = logging.getLogger(__name__)
MOSCOW = (55.7558, 37.6173)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["Фото котика", "Мой аватар"],
        ["Мой ID", "CTF-соревнования"],
        ["Погода", "Помощь"],
    ], resize_keyboard=True)


def location_menu(private: bool = True) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton("Отправить координаты", request_location=True)]] if private else []
    return ReplyKeyboardMarkup(rows + [["Погода в Москве", "В меню"]],
                               resize_keyboard=True, one_time_keyboard=True)


def services(context: ContextTypes.DEFAULT_TYPE) -> ApiServices:
    return context.bot_data["services"]


async def remember_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat:
        store: ChatStore = context.bot_data["store"]
        store.remember(chat.id, chat.type)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name if user else "пользователь"
    await update.effective_message.reply_text(
        f"Привет, {name}! Я учебный CTF-календарь.\n"
        "Показываю ближайшие соревнования, погоду, фото котиков и персональный аватар.\n"
        "Выберите кнопку ниже. Команды: /help, /id, /ctf, /weather.",
        reply_markup=main_menu(),
    )
    log.info("command_start processed")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "/start — приветствие и меню\n/help — справка\n/id — ID пользователя и чата\n"
        "/ctf или /showctf — ближайшие CTF из CTFtime\n/weather — запрос геолокации\n\n"
        "Фото котика — случайное фото выбранной породы.\n"
        "Мой аватар — робот RoboHash по ID и имени.\n"
        "Погода — текущие данные OpenWeatherMap. Можно отправить координаты "
        "или явно выбрать Москву. Геолокация не сохраняется.\n"
        "Кнопки ◀ и ▶ переключают карточки CTF; время указано по Москве.",
        reply_markup=main_menu(),
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, chat = update.effective_user, update.effective_chat
    await update.effective_message.reply_text(
        f"Ваш ID: {user.id if user else 'не определён'}\nID чата: {chat.id}",
        reply_markup=main_menu(),
    )


async def report_service_error(update: Update, error: ServiceError) -> None:
    # Дополнение: журнал сохраняет код ошибки, но не API-ключ, URL или данные пользователя.
    log.warning("external_api_failed service=%s code=%s", error.service, error.code)
    await update.effective_message.reply_text(error.public_message, reply_markup=main_menu())


async def cat_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        url = await services(context).cat_url()
        await update.effective_message.reply_photo(
            photo=url,
            caption=f"Случайный котик. Порода: {services(context).settings.cat_breed}. Источник: TheCatAPI.",
            reply_markup=main_menu(),
        )
    except ServiceError as exc:
        await report_service_error(update, exc)
    except BadRequest:
        await update.effective_message.reply_text(
            "Telegram не смог загрузить изображение котика. Попробуйте ещё раз.", reply_markup=main_menu())


async def my_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        await update.effective_message.reply_text("Не удалось определить пользователя.", reply_markup=main_menu())
        return
    try:
        await update.effective_message.reply_photo(
            photo=avatar_url(user.id, user.username, user.first_name),
            caption=f"{user.first_name}, ваш робот. При неизменных ID и имени аватар повторяется. Источник: RoboHash.",
            reply_markup=main_menu(),
        )
    except BadRequest:
        await update.effective_message.reply_text(
            "Telegram не смог загрузить аватар. Попробуйте позже.", reply_markup=main_menu())


async def request_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    private = update.effective_chat.type == ChatType.PRIVATE
    note = ("Отправьте геолокацию кнопкой ниже. " if private else
            "Кнопка геолокации доступна в личном чате с ботом. ")
    await update.effective_message.reply_text(
        note + "Можно выбрать «Погода в Москве» или вернуться в меню. "
        "Москва — отдельный вариант, а не определение вашего местоположения.",
        reply_markup=location_menu(private),
    )


async def send_weather(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       latitude: object, longitude: object, *, fallback: bool = False) -> None:
    try:
        weather = await services(context).weather(latitude, longitude)
        heading = ("Москва — выбранный запасной город; это не ваша геолокация.\n\n" if fallback else
                   "Погода по переданным координатам.\n\n")
        await update.effective_message.reply_text(heading + weather.text(), reply_markup=main_menu())
    except ServiceError as exc:
        await report_service_error(update, exc)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    location = update.effective_message.location
    if location is None:
        await update.effective_message.reply_text(
            "Координаты не получены. Отправьте геолокацию или выберите погоду в Москве.",
            reply_markup=location_menu(update.effective_chat.type == ChatType.PRIVATE),
        )
        return
    await send_weather(update, context, location.latitude, location.longitude)


def ctf_keyboard(snapshot_id: str, page: int, total: int, event_url: str) -> InlineKeyboardMarkup:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀", callback_data=f"ctf:{snapshot_id}:{page - 1}"))
    row.append(InlineKeyboardButton(f"{page + 1} / {total}", callback_data=f"ctf:{snapshot_id}:{page}"))
    if page + 1 < total:
        row.append(InlineKeyboardButton("▶", callback_data=f"ctf:{snapshot_id}:{page + 1}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Открыть CTFtime", url=event_url)]])


async def show_ctf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        events = await services(context).ctf_events()
        if not events:
            await update.effective_message.reply_text(
                "Ближайшие CTF в выбранном периоде не найдены.", reply_markup=main_menu())
            return
        # Дополнение: личный снимок списка не меняется между нажатиями inline-кнопок.
        snapshots = context.user_data.setdefault("ctf_snapshots", {})
        snapshot_id = secrets.token_hex(4)
        snapshots[snapshot_id] = events
        while len(snapshots) > 5:
            del snapshots[next(iter(snapshots))]
        await update.effective_message.reply_text(
            ctf_text(events[0], f"CTF-соревнование 1 из {len(events)}\n\n"),
            reply_markup=ctf_keyboard(snapshot_id, 0, len(events), events[0].url),
        )
        log.info("ctf_list loaded count=%s", len(events))
    except ServiceError as exc:
        await report_service_error(update, exc)


async def ctf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    try:
        prefix, snapshot_id, page_text = str(query.data).split(":")
        page = int(page_text)
        snapshots = context.user_data.get("ctf_snapshots", {})
        events = snapshots.get(snapshot_id)
        if prefix != "ctf" or not events or not 0 <= page < len(events):
            raise ValueError
    except (ValueError, TypeError):
        await query.answer("Список устарел или кнопка некорректна. Откройте /ctf.", show_alert=True)
        return
    await query.answer()
    try:
        await query.edit_message_text(
            text=ctf_text(events[page], f"CTF-соревнование {page + 1} из {len(events)}\n\n"),
            reply_markup=ctf_keyboard(snapshot_id, page, len(events), events[page].url),
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        log.warning("ctf_callback failed reason=telegram_bad_request")
        if update.effective_message:
            await update.effective_message.reply_text("Не удалось обновить карточку. Откройте /ctf.")


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text
    routes = {
        "Фото котика": cat_photo, "Мой аватар": my_avatar, "Сгенери аватар": my_avatar,
        "Мой ID": id_command, "CTF-соревнования": show_ctf,
        "Погода": request_location, "Погода сегодня": request_location, "Помощь": help_command,
    }
    if text in routes:
        await routes[text](update, context)
    elif text == "Погода в Москве":
        await send_weather(update, context, *MOSCOW, fallback=True)
    elif text == "В меню":
        await update.effective_message.reply_text("Главное меню.", reply_markup=main_menu())
    else:
        await unknown_command(update, context)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Не распознала команду. Выберите кнопку меню или откройте /help.", reply_markup=main_menu())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    log.error("telegram_update_failed type=%s", type(error).__name__)
    if not isinstance(update, Update) or not update.effective_chat:
        return
    if isinstance(error, Forbidden):
        context.bot_data["store"].deactivate(update.effective_chat.id)
        return
    if isinstance(error, RetryAfter):
        return  # Не создаём ещё один запрос в уже ограниченный Telegram.
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Не удалось выполнить действие. Попробуйте позже или откройте /help.", reply_markup=main_menu())
        except TelegramError:
            log.warning("error_notice not_delivered")
