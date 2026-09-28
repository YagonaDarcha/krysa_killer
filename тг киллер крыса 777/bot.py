import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from app import db, events, game, settings
from app.commands import ADMIN_PRIVATE_COMMANDS, GROUP_COMMANDS, PRIVATE_COMMANDS
from app.config import ADMIN_IDS, DB_PATH, LOG_PATH, TOKEN
from app.handlers import admin, group, private

def configure_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, logging.StreamHandler()],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def setup_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
        # админы групп больше не управляют ивентом — у них обычное меню
        await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllChatAdministrators())
        await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        for admin_id in ADMIN_IDS:
            try:
                await bot.set_my_commands(ADMIN_PRIVATE_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
            except TelegramAPIError:
                logging.info("Админ %s ещё не запускал бота в личке", admin_id)
        for chat in game.all_chats():
            if chat["bot_in"]:
                await group.set_admin_commands(bot, chat["chat_id"])
    except TelegramAPIError:
        logging.exception("Не удалось обновить меню команд")


async def main() -> None:
    configure_logging()
    if not TOKEN:
        raise SystemExit("Не задан BOT_TOKEN в файле .env")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS в .env пуст — админ-панель никому не доступна")

    db.init(DB_PATH)
    settings.load()
    game.backfill_running_events()
    events.load_pending()

    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True, allow_sending_without_reply=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(group.GroupGuard())
    dp.include_routers(admin.router, private.router, group.router)

    await setup_commands(bot)
    me = await bot.get_me()
    logging.info("Бот @%s запущен", me.username)

    loop_task = asyncio.create_task(events.game_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        loop_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as stop:
        if isinstance(stop, SystemExit) and stop.code:
            print(stop.code)
