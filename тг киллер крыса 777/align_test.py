"""Прислать админам варианты выравнивания номеров в топе — чтобы выбрать, где ровнее."""
import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import db, settings, texts
from app.config import ADMIN_IDS, DB_PATH, TOKEN

NAMES = ["s7", "theme", "Вася", "Петя", "Коля", "Маша", "Дима", "Лена", "Артём", "Кира", "Макс", "Оля"]
VARIANTS = {
    "A": "",           # без добивки
    "B": " ",     # очень узкий пробел
    "C": " ",     # узкий пробел
    "D": " ",     # четверть
    "E": " ",     # треть
    "F": " ",     # половина
}


def sample(pad: str) -> str:
    lines = [f"{texts.place_icon(i, pad)} {name} — <b>{40 - i * 3}</b>" for i, name in enumerate(NAMES, 1)]
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


async def main() -> None:
    db.init(DB_PATH)
    settings.load()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, "<b>Выбери вариант, где номера и имена стоят ровнее всего:</b>")
                for name, pad in VARIANTS.items():
                    await bot.send_message(admin_id, f"<b>Вариант {name}</b>\n{sample(pad)}")
                print("Отправлено:", admin_id)
            except Exception as error:
                print("Не отправлено", admin_id, error)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
