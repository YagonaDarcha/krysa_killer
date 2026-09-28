import asyncio
import re
from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.emoji import em, icon, plain

_background: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Фоновая задача, на которую держим ссылку, чтобы её не съел сборщик мусора."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def user_name(user) -> str:
    name = user.full_name or (f"@{user.username}" if user.username else f"id{user.id}")
    return name[:32]


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def hearts(deaths: int) -> str:
    from app.settings import get  # settings сам импортирует ui, поэтому здесь
    lives = get("lives")
    deaths = max(0, min(lives, deaths))
    return em("heart") * (lives - deaths) + em("heart_dead") * deaths


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def points_word(n: int) -> str:
    return f"{n} {plural(n, 'очко', 'очка', 'очков')}"


def fmt_secs(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} сек"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин" + (f" {sec} сек" if sec else "")
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч" + (f" {minutes} мин" if minutes else "")


DURATION_UNITS = {"d": 86400, "д": 86400, "h": 3600, "ч": 3600, "m": 60, "м": 60, "s": 1, "с": 1}
MAX_DURATION = 30 * 86400


def parse_duration(text: str) -> int | None:
    """«20h», «1h30m», «45m», «90s», «2ч 15м» → секунды. None, если формат неверный."""
    text = text.lower().replace(" ", "")
    parts = re.findall(r"(\d+)([dдhчmмsс])", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    seconds = sum(int(n) * DURATION_UNITS[u] for n, u in parts)
    return seconds if 0 < seconds <= MAX_DURATION else None


def btn(text: str, cb: str | None = None, *, emoji: str | None = None,
        style: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    """Кнопка с премиум-эмодзи (если задан ID) или обычным эмодзи в тексте.

    style: "success" — зелёная, "danger" — красная, "primary" — синяя.
    """
    icon_id = icon(emoji) if emoji else None
    if emoji and not icon_id:
        text = f"{plain(emoji)} {text}"
    return InlineKeyboardButton(
        text=text, callback_data=cb, url=url,
        icon_custom_emoji_id=icon_id, style=style,
    )


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(row) for row in rows if row])


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


async def delete_later(message: Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def temp_reply(message: Message, text: str, delay: float = 6, *, delete_original: bool = False) -> None:
    """Временный ответ. С delete_original исходное сообщение удаляется вместе с ответом."""
    try:
        sent = await message.reply(text)
    except TelegramBadRequest:
        sent = await message.answer(text)
    spawn(delete_later(sent, delay))
    if delete_original:
        spawn(delete_later(message, delay))


async def try_delete(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
