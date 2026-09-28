import asyncio
from html import escape

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType, DiceEmoji
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommandScopeChatMember, CallbackQuery, ChatMemberUpdated, Message, User

from app import events, game, texts
from app.commands import GROUP_ADMIN_COMMANDS
from app.config import ADMIN_IDS
from app.emoji import em
from app.game import SpinResult
from app.settings import get as S
from app.ui import fmt_secs, hearts, mention, parse_duration, points_word, temp_reply, try_delete, user_name

GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}

router = Router()
router.message.filter(F.chat.type.in_(GROUPS))


class GroupGuard(BaseMiddleware):
    """Запоминает чаты и удаляет сообщения тех, кто сейчас в муте ивента."""

    def __init__(self):
        self.titles: dict[int, str] = {}

    async def __call__(self, handler, event: Message, data):
        chat = event.chat
        if chat.type in GROUPS:
            if self.titles.get(chat.id) != chat.title:
                game.upsert_chat(chat.id, chat.title or "")
                self.titles[chat.id] = chat.title
            user = event.from_user
            if (user and not user.is_bot and game.event_active(chat.id)
                    and game.mute_left(chat.id, user.id) > 0):
                await try_delete(event)
                return None
        return await handler(event, data)


def is_bot_admin(user_id: int) -> bool:
    """Управлять ивентом (/game, /change, /event_start…) могут только админы бота из .env."""
    return user_id in ADMIN_IDS


# ─── Прокрут ───────────────────────────────────────────────────────────────

DENY_TEXT = {
    "out": f"{em('skull')} <b>Ты выбыл.</b> Смотри со стороны.",
    "muted": f"{em('mute')} <b>Ты в муте.</b>",
}


def score_text(points: int) -> str:
    return f"<b>{points}</b>" if S("unlimited") else f"<b>{points}</b>/{S('target')}"


def result_text(user: User, result: SpinResult) -> str:
    who = f"{em('user')} {mention(user.id, user_name(user))}"
    total = f"{em('coin')} Всего очков : {score_text(result.points)}"
    if not result.combo:
        return f"{em('slot')} <b>Мимо</b>\n\n{who} ничего не выпало\n<blockquote>{total}</blockquote>"
    return (
        f"{texts.combo_symbols(result.combo)} <b>{texts.COMBO_TITLE[result.combo]}</b>\n\n"
        f"{who} тебе выпало {texts.COMBO_DROP[result.combo]}\n"
        f"<blockquote>{total} <b>+{result.gained}</b></blockquote>"
    )


async def finish_spin(bot: Bot, dice_message: Message, user: User) -> None:
    chat_id, reply = dice_message.chat.id, dice_message.message_id
    game.set_last_msg(chat_id, user.id, reply)
    await asyncio.sleep(S("slot_delay"))  # не спойлерим, пока крутится барабан
    result = game.apply_spin(chat_id, user.id, dice_message.dice.value)
    if result is None:
        return
    if result.won:
        if result.combo == "seven" and S("jackpot_win"):
            reason = f"выбил {texts.combo_symbols('seven')} 777 и забрал победу!"
        else:
            reason = f"первым набрал <b>{points_word(result.points)}</b>!"
        await events.announce_winner(
            bot, chat_id, user.id, user_name(user), result.points, reason, nft=result.nft, reply=reply,
        )
        return
    if result.combo or S("reply_empty"):
        await dice_message.reply(result_text(user, result))
    if result.nft:
        await events.announce_nft(bot, chat_id, user.id, user_name(user), reply)


async def deny(message: Message, status: str) -> None:
    if status == "paused":
        left = fmt_secs(game.pause_left(message.chat.id))
        text = f"{em('pause')} <b>Перемена.</b> Продолжим через {left}"
        await temp_reply(message, text, delay=S("warn_delay"), delete_original=True)
    elif status in DENY_TEXT and S("deny_msgs"):
        await temp_reply(message, DENY_TEXT[status], delay=S("warn_delay"), delete_original=True)
    elif status != "cooldown" or S("delete_cooldown"):
        await try_delete(message)


@router.message(F.dice.emoji == DiceEmoji.SLOT_MACHINE)
async def on_slot(message: Message, bot: Bot):
    if message.via_bot or not message.from_user:
        return
    if message.forward_origin and not S("allow_forwarded"):
        return
    user = message.from_user
    status = game.try_spin(message.chat.id, user.id, user_name(user), user.username or "")
    if status == "no_event":
        return
    if status != "ok":
        await deny(message, status)
        return
    await finish_spin(bot, message, user)


@router.message(Command("spin"))
async def cmd_spin(message: Message, bot: Bot):
    if not S("spin_command"):
        await temp_reply(message, f"{em('slot')} Крути, отправляя 🎰 в чат.", delay=S("warn_delay"))
        return
    user = message.from_user
    status = game.try_spin(message.chat.id, user.id, user_name(user), user.username or "")
    if status == "no_event":
        await temp_reply(message, f"{em('timer')} <b>Ивент не идёт.</b>")
        return
    if status != "ok":
        await deny(message, status)
        return
    dice_message = await message.reply_dice(emoji=DiceEmoji.SLOT_MACHINE)
    await finish_spin(bot, dice_message, user)


# ─── Информация ───────────────────────────────────────────────────────────

@router.message(Command("lives"))
async def cmd_lives(message: Message):
    chat_id, user = message.chat.id, message.from_user
    player = game.get_player(chat_id, user.id)
    who = f"{em('user')} {mention(user.id, user_name(user))}"
    if not player:
        await message.reply(f"{who}\n<blockquote>{hearts(0)} {S('lives')}/{S('lives')} — ты ещё не крутил</blockquote>")
        return
    if player["alive"]:
        status = f"{hearts(player['deaths'])} {S('lives') - player['deaths']}/{S('lives')}"
    else:
        status = f"{em('skull')} выбыл"
    muted = game.mute_left(chat_id, user.id)
    extra = f"\n{em('mute')} мут ещё {fmt_secs(muted)}" if muted else ""
    await message.reply(f"{who}\n<blockquote>{status}{extra}</blockquote>")


@router.message(Command("me"))
async def cmd_me(message: Message):
    chat_id, user = message.chat.id, message.from_user
    player = game.get_player(chat_id, user.id)
    who = f"{em('user')} {mention(user.id, user_name(user))}"
    if not player:
        await message.reply(f"{who}\n<blockquote>{em('slot')} Ещё не крутил — отправь 🎰 или /spin</blockquote>")
        return
    legend = f" {em('crown')}" if game.is_legend(user.id) else ""
    await message.reply(
        f"{who}{legend}\n<blockquote>"
        f"{em('coin')} Всего очков : {score_text(player['points'])}\n"
        f"{em('chart')} Место: <b>#{game.place(chat_id, user.id)}</b>\n"
        f"{hearts(player['deaths'])} Жизни: {max(0, S('lives') - player['deaths'])}/{S('lives')}\n"
        f"{em('slot')} Прокрутов: {player['spins']} · джекпотов: {player['jackpots']}"
        f"</blockquote>"
    )


@router.message(Command("top"))
async def cmd_top(message: Message):
    chat_id = message.chat.id
    state = events.time_left_text(chat_id) if game.event_active(chat_id) else "ивент не идёт"
    if game.is_paused(chat_id):
        state = f"перемена ещё {fmt_secs(game.pause_left(chat_id))}"
    await message.reply(f"{em('chart')} <b>ТОП ИВЕНТА</b>\n{em('timer')} {state}\n{events.top_text(chat_id)}")


@router.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.reply(texts.rules_text())


# ─── Управление ивентом из чата ───────────────────────────────────────────

@router.message(Command("event_start"))
async def cmd_event_start(message: Message, bot: Bot):
    if not is_bot_admin(message.from_user.id):
        await temp_reply(message, f"{em('warn')} Только для админов бота.")
        return
    error = await events.start_event(bot, message.chat.id, message.message_id)
    if error:
        await temp_reply(message, f"{em('info')} {error}.")


GAME_HELP = (
    f"{em('timer')} <b>Запуск ивента на время</b>\n\n"
    "<code>/game 20h</code> — на 20 часов\n"
    "<code>/game 1h30m</code> — на 1,5 часа\n"
    "<code>/game 45m</code> — на 45 минут\n"
    "<code>/game 90s</code> — на 90 секунд\n"
    "<code>/game off</code> — без ограничения по времени\n\n"
    "h — часы, m — минуты, s — секунды, d — дни.\n"
    "Если ивент уже идёт, команда меняет оставшееся время."
)


@router.message(Command("game"))
async def cmd_game(message: Message, bot: Bot, command: CommandObject):
    chat_id = message.chat.id
    arg = (command.args or "").strip()
    if not arg:
        status = events.time_left_text(chat_id) if game.event_active(chat_id) else "ивент не идёт"
        await message.reply(f"{GAME_HELP}\n\nСейчас: <b>{status}</b>")
        return
    if not is_bot_admin(message.from_user.id):
        await temp_reply(message, f"{em('warn')} Только для админов бота.")
        return
    if arg.lower() in {"off", "0", "inf", "∞"}:
        duration = None
    else:
        duration = parse_duration(arg)
        if duration is None:
            await message.reply(f"{em('warn')} Не понял время «{escape(arg[:20])}».\n\n{GAME_HELP}")
            return
    if game.event_active(chat_id):
        error = await events.set_duration(bot, chat_id, duration, message.message_id)
    else:
        error = await events.start_event(bot, chat_id, message.message_id, duration)
    if error:
        await temp_reply(message, f"{em('info')} {error}.")


CHANGE_HELP = (
    f"{em('pause')} <b>Перемена</b>\n"
    "<blockquote><code>/change 10m</code> — перемена на 10 минут\n"
    "<code>/change 1h</code> · <code>/change 90s</code> · <code>/change 1h30m</code>\n"
    "<code>/change</code> — на время по умолчанию\n"
    "<code>/changestop</code> — закончить перемену сразу</blockquote>"
)


@router.message(Command("change"))
async def cmd_change(message: Message, bot: Bot, command: CommandObject):
    chat_id = message.chat.id
    if not is_bot_admin(message.from_user.id):
        await temp_reply(message, f"{em('warn')} Только для админов бота.")
        return
    arg = (command.args or "").strip()
    if arg in {"help", "?"}:
        await message.reply(CHANGE_HELP)
        return
    duration = parse_duration(arg) if arg else S("pause_default") * 60
    if duration is None:
        await message.reply(f"{em('warn')} Не понял время «{escape(arg[:20])}».\n\n{CHANGE_HELP}")
        return
    error = await events.pause_event(bot, chat_id, duration, message.message_id)
    if error:
        await temp_reply(message, f"{em('info')} {error}.")


@router.message(Command("changestop"))
async def cmd_changestop(message: Message, bot: Bot):
    if not is_bot_admin(message.from_user.id):
        await temp_reply(message, f"{em('warn')} Только для админов бота.")
        return
    error = await events.resume_event(bot, message.chat.id, message.message_id)
    if error:
        await temp_reply(message, f"{em('info')} {error}.")


@router.message(Command("event_stop"))
async def cmd_event_stop(message: Message, bot: Bot):
    if not is_bot_admin(message.from_user.id):
        await temp_reply(message, f"{em('warn')} Только для админов бота.")
        return
    error = await events.stop_event(bot, message.chat.id, message.message_id)
    if error:
        await temp_reply(message, f"{em('info')} {error}.")


async def set_admin_commands(bot: Bot, chat_id: int) -> None:
    """Команды управления ивентом видны в меню только админам бота."""
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(GROUP_ADMIN_COMMANDS, scope=BotCommandScopeChatMember(chat_id=chat_id, user_id=admin_id))
        except TelegramAPIError:
            pass  # админа нет в этом чате


@router.my_chat_member()
async def on_bot_added(update: ChatMemberUpdated, bot: Bot):
    if update.chat.type in GROUPS:
        present = update.new_chat_member.status in {
            ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED,
        }
        game.upsert_chat(update.chat.id, update.chat.title or "", present)
        if present:
            await set_admin_commands(bot, update.chat.id)


# ─── Кнопки киллера и крысы ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("k:") | F.data.startswith("r:"))
async def on_choice(call: CallbackQuery, bot: Bot):
    prefix, token, index = call.data.split(":")
    pending = events.PENDING.get(token)
    if not pending:
        await call.answer("Уже неактуально.")
        return
    if call.from_user.id != pending.target_id:
        await call.answer("Это не тебе. Смотри и молись, чтобы не пришли за тобой.", show_alert=True)
        return
    await call.answer()
    await events.RESOLVERS[pending.kind](bot, token, int(index))


@router.callback_query(F.data.startswith("rr:"))
async def on_raid_catch(call: CallbackQuery, bot: Bot):
    token = call.data.split(":")[1]
    pending = events.PENDING.get(token)
    if not pending:
        await call.answer("Крыса уже ушла.")
        return
    player = game.get_player(pending.chat_id, call.from_user.id)
    if not player or not player["alive"]:
        await call.answer("Ловить крысу могут только участники ивента.", show_alert=True)
        return
    if game.mute_left(pending.chat_id, call.from_user.id) > 0:
        await call.answer("Ты в муте.", show_alert=True)
        return
    await call.answer("Попалась!")
    await events.resolve_raid(bot, token, call.from_user.id)
