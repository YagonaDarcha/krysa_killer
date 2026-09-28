"""Меню команд бота для разных чатов и ролей."""
from aiogram.types import BotCommand

GROUP_COMMANDS = [
    BotCommand(command="spin", description="Крутить слот 🎰"),
    BotCommand(command="lives", description="Мои жизни"),
    BotCommand(command="me", description="Мои очки"),
    BotCommand(command="top", description="Топ ивента"),
    BotCommand(command="rules", description="Правила"),
]
# видят только админы бота из .env
GROUP_ADMIN_COMMANDS = GROUP_COMMANDS + [
    BotCommand(command="game", description="Ивент на время: /game 20h"),
    BotCommand(command="change", description="Перемена: /change 10m"),
    BotCommand(command="changestop", description="Закончить перемену"),
    BotCommand(command="event_start", description="Запустить ивент"),
    BotCommand(command="event_stop", description="Остановить ивент"),
]
PRIVATE_COMMANDS = [
    BotCommand(command="start", description="О боте"),
    BotCommand(command="reward", description="Награда чемпиона"),
    BotCommand(command="rules", description="Правила"),
    BotCommand(command="id", description="Мой ID"),
]
ADMIN_PRIVATE_COMMANDS = PRIVATE_COMMANDS + [
    BotCommand(command="admin", description="Админ-панель"),
    BotCommand(command="game", description="Запустить ивент на время"),
    BotCommand(command="preview", description="Образцы сообщений"),
]
