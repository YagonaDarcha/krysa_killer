"""Разослать админам образцы сообщений бота (для проверки правок).

Запуск: python send_preview.py            — все образцы
        python send_preview.py Отчёт      — только образцы, в названии которых есть «Отчёт»
Работает параллельно с запущенным ботом — только отправляет сообщения, не читает обновления.
"""
import asyncio
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from app import db, preview, settings
from app.config import ADMIN_IDS, DB_PATH, TOKEN


async def main() -> None:
    db.init(DB_PATH)
    settings.load()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    try:
        for admin_id in ADMIN_IDS:
            try:
                await preview.send_previews(bot, admin_id, " ".join(sys.argv[1:]) or None)
                print(f"Отправлено: {admin_id}")
            except TelegramAPIError as error:
                print(f"Не отправлено {admin_id}: {error}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
