"""Живые события ивента: киллер, крыса, муты, старт/стоп и победа."""
import asyncio
import json
import logging
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ChatPermissions, ReplyParameters

from app import game, texts
from app.config import ADMIN_IDS
from app.emoji import em
from app.settings import get as S
from app.ui import btn, fmt_secs, hearts, kb, mention, points_word

log = logging.getLogger(__name__)

NO_RIGHTS = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
    can_add_web_page_previews=False,
)
ALL_RIGHTS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True,
)


def reply_to(message_id: int | None) -> ReplyParameters | None:
    """Всё, что пишет бот, — ответом. Если сообщение удалено, отправится без ответа."""
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True) if message_id else None


# ─── Муты ──────────────────────────────────────────────────────────────────

async def mute(bot: Bot, chat_id: int, user_id: int, seconds: int, *, eliminated: bool = False) -> None:
    until = time.time() + seconds
    restricted = False
    if S("tg_mute") and seconds > 0:
        try:
            # Telegram считает мут короче 30 секунд вечным, поэтому короткие муты
            # снимает сам бот, а длинные ещё и страхуются until_date.
            await bot.restrict_chat_member(
                chat_id, user_id, NO_RIGHTS,
                use_independent_chat_permissions=True,
                until_date=int(until) + 1 if seconds >= 40 else None,
            )
            restricted = True
        except TelegramAPIError as error:
            log.info("Не удалось замутить %s в %s: %s", user_id, chat_id, error)
    game.set_mute(chat_id, user_id, until, restricted, eliminated)


async def release(bot: Bot, row) -> None:
    chat_id, user_id = row["chat_id"], row["user_id"]
    game.delete_mute(chat_id, user_id)
    if row["restricted"]:
        try:
            chat = await bot.get_chat(chat_id)
            await bot.restrict_chat_member(
                chat_id, user_id, chat.permissions or ALL_RIGHTS,
                use_independent_chat_permissions=True,
            )
        except TelegramAPIError as error:
            log.info("Не удалось снять мут %s в %s: %s", user_id, chat_id, error)
    if row["eliminated"] and S("elim_return") and game.event_active(chat_id):
        player = game.get_player(chat_id, user_id)
        if player and not player["alive"]:
            game.revive(chat_id, user_id)
            await bot.send_message(
                chat_id,
                f"{em('fire')} {mention(user_id, player['name'])} вернулся в игру! "
                f"{hearts(0)} · {points_word(player['points'])}",
                reply_parameters=reply_to(player["last_msg"]),
            )


async def lift_all_mutes(bot: Bot, chat_id: int) -> None:
    for row in game.chat_mutes(chat_id):
        await release(bot, row)


# ─── Интерактивы (двери киллера, игры крысы) ──────────────────────────────
# Киллер и крыса ждут ответа сколько угодно. За deadline_min минут до конца ивента
# всё неотвеченное засчитывается как проигрыш. Ожидания лежат в базе и переживают перезапуск.

@dataclass
class Pending:
    kind: str                 # killer | cups | quiz | raid
    chat_id: int
    target_id: int = 0
    answer: int = -1
    options: list[str] = field(default_factory=list)
    header: str = ""
    message_id: int = 0


PENDING: dict[str, Pending] = {}


def load_pending() -> None:
    PENDING.clear()
    for row in game.all_pending():
        PENDING[row["token"]] = Pending(
            kind=row["kind"], chat_id=row["chat_id"], target_id=row["target_id"], answer=row["answer"],
            options=json.loads(row["options"]), header=row["header"], message_id=row["message_id"],
        )


def _add(token: str, pending: Pending) -> None:
    PENDING[token] = pending
    game.save_pending(
        token, pending.kind, pending.chat_id, pending.target_id, pending.answer,
        pending.options, pending.header, pending.message_id,
    )


def _take(token: str) -> Pending | None:
    """Забирает ожидание ровно один раз — повторный клик получит None."""
    pending = PENDING.pop(token, None)
    if pending:
        game.delete_pending(token)
    return pending


def _hooked(chat_id: int) -> set[int]:
    """Игроки, которые уже ждут ответа киллеру или крысе, — к ним новые не приходят."""
    return {p.target_id for p in PENDING.values() if p.chat_id == chat_id and p.kind != "raid"}


def _raid_running(chat_id: int) -> bool:
    return any(p.chat_id == chat_id and p.kind == "raid" for p in PENDING.values())


def _wait_line(chat_id: int, loss: str, lead: str = "Нет ответа") -> str:
    if game.time_left(chat_id) is None:
        return f"{em('timer')} Жду ответа."
    return f"{em('timer')} {lead} за {S('deadline_min')} мин до конца — {loss}."


async def _finish_message(bot: Bot, pending: Pending, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=pending.chat_id, message_id=pending.message_id, reply_markup=None)
    except TelegramBadRequest as error:
        log.info("Не удалось обновить сообщение события: %s", error)


async def _outcome(bot: Bot, pending: Pending, reveal: str, verdict: str) -> None:
    """Закрывает сообщение события (без кнопок, с раскрытием) и отвечает на него итогом."""
    await _finish_message(bot, pending, f"{pending.header}\n<blockquote>{reveal}</blockquote>")
    await bot.send_message(pending.chat_id, verdict, reply_parameters=reply_to(pending.message_id))


async def _still_playable(bot: Bot, pending: Pending):
    """Игрок-цель ещё в игре? Если нет — закрываем сообщение и возвращаем None."""
    if not game.event_active(pending.chat_id):
        await _finish_message(bot, pending, pending.header + "\n\n<i>Ивент завершён.</i>")
        return None
    player = game.get_player(pending.chat_id, pending.target_id)
    if not player or not player["alive"]:
        await _finish_message(bot, pending, pending.header + "\n\n<i>Цель выбыла.</i>")
        return None
    return player


def _say(base: list[str], kind: str, **fields) -> str:
    """Фраза персонажа. Иногда — фраза, которую придумал чемпион прошлых ивентов."""
    custom = game.legend_phrases(kind) if S("legend_phrases") else []
    icon_key = "killer" if kind == "killer" else "rat"
    if custom and random.random() < 0.3:
        author, phrase = random.choice(custom)
        return f"<blockquote>{em(icon_key)} «{escape(phrase)}»\n<i>— фраза чемпиона {escape(author)}</i></blockquote>"
    return f"<blockquote>{em(icon_key)} «{texts.pick(base, **fields)}»</blockquote>"


async def cancel_chat(bot: Bot, chat_id: int) -> None:
    for token, pending in list(PENDING.items()):
        if pending.chat_id == chat_id and _take(token):
            await _finish_message(bot, pending, pending.header + "\n\n<i>Ивент завершён.</i>")


async def expire_chat(bot: Bot, chat_id: int) -> None:
    """Последние минуты ивента: всё неотвеченное засчитывается как проигрыш."""
    for token, pending in list(PENDING.items()):
        if pending.chat_id == chat_id:
            await RESOLVERS[pending.kind](bot, token, None)


# ─── Киллер ────────────────────────────────────────────────────────────────

async def summon_killer(bot: Bot, chat_id: int) -> str | None:
    """Запускает киллера. Возвращает причину отказа или None, если он вышел на охоту."""
    if not game.event_active(chat_id):
        return "Ивент не запущен"
    if game.is_paused(chat_id):
        return "Идёт перемена"
    if game.in_final_window(chat_id):
        return "Идут последние минуты ивента"
    active = game.active_targets(chat_id)
    if len(active) < S("min_players"):
        return f"Мало активных игроков (нужно {S('min_players')})"
    hooked = _hooked(chat_id)
    targets = [
        t for t in active
        if t["user_id"] not in hooked
        and not (S("killer_needs_points") and t["points"] <= 0)
        and not (S("killer_spare_legend") and game.is_legend(t["user_id"]))
    ]
    if not targets:
        return "Нет подходящих игроков"

    target = random.choice(targets)
    rooms = S("killer_rooms")
    deadly = min(S("killer_deadly"), rooms - 1)
    marks = ["x"] * deadly + ["o"] * (rooms - deadly)
    random.shuffle(marks)
    stakes = [f"−{S('killer_steal')}% очков"] if S("killer_steal") else []
    if S("killer_takes_life"):
        stakes.append("−1 жизнь")
    champion = f"\n{em('crown')} Чемпион? Без скидок." if game.is_legend(target["user_id"]) else ""
    header = f"{em('killer')} <b>Киллер пришёл за {mention(target['user_id'], target['name'])}</b>{champion}"
    odds = (
        f"{texts.doors_text(rooms)}: пустых — {rooms - deadly}, со мной — {deadly}"
        if rooms > 2 else "За одной пусто, за другой — я"
    )
    text = (
        f"{header}\n\nВыбери дверь. {odds}.\n"
        f"<blockquote>{em('skull')} Не та дверь: {', '.join(stakes) or 'только испуг'}\n"
        f"{_wait_line(chat_id, 'выстрелю сам')}</blockquote>"
    )

    token = secrets.token_hex(4)
    buttons = [btn(str(i + 1), f"k:{token}:{i}", emoji="door", style="primary") for i in range(rooms)]
    message = await bot.send_message(
        chat_id, text, reply_markup=kb(buttons), reply_parameters=reply_to(target["last_msg"]),
    )
    game.log_inc(chat_id, "killer_visits")
    _add(token, Pending(
        kind="killer", chat_id=chat_id, target_id=target["user_id"], answer=marks.index("x"),
        options=marks, header=header, message_id=message.message_id,
    ))
    return None


def _deadly_doors(pending: Pending) -> set[int]:
    """Опасные двери: отмечены «x». У старых ожиданий опасная одна — в answer."""
    if "x" in pending.options:
        return {i for i, mark in enumerate(pending.options) if mark == "x"}
    return {pending.answer}


def _doors_reveal(pending: Pending, choice: int | None) -> str:
    deadly = _deadly_doors(pending)
    cells = []
    for i in range(len(pending.options)):
        mark = em("skull") if i in deadly else em("safe")
        cells.append(f"{em('door')}{i + 1} {mark}" + (" ← ты" if i == choice else ""))
    return "  ".join(cells)


async def resolve_killer(bot: Bot, token: str, choice: int | None) -> None:
    pending = _take(token)
    if not pending:
        return
    player = await _still_playable(bot, pending)
    if not player:
        return

    chat_id, user_id = pending.chat_id, pending.target_id
    name = mention(user_id, player["name"])
    reveal = _doors_reveal(pending, choice)

    if choice is not None and choice not in _deadly_doors(pending):
        verdict = f"{em('safe')} <b>Пусто!</b> {name} живёт.\n{_say(texts.KILLER_MISS, 'killer')}"
        await _outcome(bot, pending, reveal, verdict)
        return

    game.log_inc(chat_id, "killer_hits")
    losses = []
    stolen = game.steal(chat_id, user_id, S("killer_steal"))
    if stolen:
        losses.append(f"{em('money')} −{points_word(stolen)}")
    if S("killer_takes_life"):
        death = game.register_death(chat_id, user_id)
        await mute(bot, chat_id, user_id, death.mute, eliminated=death.eliminated)
        losses.append(hearts(death.deaths))
        if death.eliminated:
            losses.append(f"{em('skull')} вылет · мут {fmt_secs(death.mute)}")
        elif death.mute:
            losses.append(f"{em('mute')} мут {fmt_secs(death.mute)}")

    head = f"{em('timer')} <b>Время вышло!</b>" if choice is None else f"{em('skull')} <b>Попал!</b>"
    verdict = f"{head} {name}\n{_say(texts.KILLER_HIT, 'killer')}" + (f"\n{' · '.join(losses)}" if losses else "")
    await _outcome(bot, pending, reveal, verdict)


# ─── Крыса ─────────────────────────────────────────────────────────────────

def _rat_mode() -> str | None:
    if S("rat_raid") and random.random() * 100 < S("rat_raid_chance"):
        return "raid"
    single = [mode for mode, key in (("cups", "rat_cups"), ("quiz", "rat_quiz")) if S(key)]
    if single:
        return random.choice(single)
    return "raid" if S("rat_raid") else None


async def summon_rat(bot: Bot, chat_id: int, mode: str | None = None) -> str | None:
    """Выпускает крысу. Возвращает причину отказа или None."""
    if not game.event_active(chat_id):
        return "Ивент не запущен"
    if game.is_paused(chat_id):
        return "Идёт перемена"
    if game.in_final_window(chat_id):
        return "Идут последние минуты ивента"
    if len(game.active_targets(chat_id)) < max(1, S("min_players")):
        return f"Мало активных игроков (нужно {S('min_players')})"
    mode = mode or _rat_mode()
    if mode is None:
        return "Все режимы крысы выключены"
    if mode == "raid":
        return await _start_raid(bot, chat_id)

    hooked = _hooked(chat_id)
    victims = [p for p in game.active_targets(chat_id) if p["points"] > 0 and p["user_id"] not in hooked]
    if not victims:
        return "Не у кого воровать"
    target = random.choice(victims)
    name = mention(target["user_id"], target["name"])

    if S("legend_immunity") and game.is_legend(target["user_id"]):
        await bot.send_message(
            chat_id,
            f"{em('rat')} <b>Крыса полезла к {name}</b>\n{em('crown')} Чемпион — карман на замке. Ушла ни с чем.",
            reply_parameters=reply_to(target["last_msg"]),
        )
        return None

    token = secrets.token_hex(4)
    if mode == "cups":
        options = [str(i + 1) for i in range(S("rat_cups_count"))]
        answer = random.randrange(len(options))
        markup = kb([btn(o, f"r:{token}:{i}", emoji="cup", style="primary") for i, o in enumerate(options)])
        header = f"{em('rat')} <b>Крыса у {name}</b>\n\nПод каким стаканом твои очки?"
    else:
        question, correct, *wrong = random.choice(texts.QUIZ)
        options = [correct, *wrong]
        random.shuffle(options)
        answer = options.index(correct)
        markup = kb(*[[btn(o, f"r:{token}:{i}", style="primary")] for i, o in enumerate(options)])
        header = f"{em('rat')} <b>Крыса у {name}</b>\n\n{em('question')} <b>{escape(question)}</b>"

    text = (
        f"{header}\n<blockquote>{em('safe')} Угадаешь — отстану.\n"
        f"{em('money')} Ошибёшься — −{S('rat_steal')}% очков.\n"
        f"{_wait_line(chat_id, 'заберу сама')}</blockquote>"
    )
    message = await bot.send_message(
        chat_id, text, reply_markup=markup, reply_parameters=reply_to(target["last_msg"]),
    )
    game.log_inc(chat_id, "rat_visits")
    _add(token, Pending(
        kind=mode, chat_id=chat_id, target_id=target["user_id"], answer=answer,
        options=options, header=header, message_id=message.message_id,
    ))
    return None


async def resolve_rat(bot: Bot, token: str, choice: int | None) -> None:
    pending = _take(token)
    if not pending:
        return
    player = await _still_playable(bot, pending)
    if not player:
        return

    name = mention(pending.target_id, player["name"])
    if pending.kind == "cups":
        reveal = "  ".join(
            f"{em('cup')}{i + 1}" + (f" {em('money')}" if i == pending.answer else "") + (" ← ты" if i == choice else "")
            for i in range(len(pending.options))
        )
    else:
        reveal = f"{em('safe')} Ответ: <b>{escape(pending.options[pending.answer])}</b>"

    if choice == pending.answer:
        verdict = f"{em('safe')} <b>Верно!</b> {name} отбился.\n{_say(texts.RAT_ESCAPED, 'rat')}"
    else:
        stolen = game.steal(pending.chat_id, pending.target_id, S("rat_steal"))
        game.log_inc(pending.chat_id, "rat_stolen", stolen)
        head = f"{em('timer')} <b>Время вышло!</b>" if choice is None else f"{em('money')} <b>Мимо!</b>"
        verdict = f"{head} −{points_word(stolen)} у {name}\n{_say(texts.RAT_STOLE, 'rat')}"
    await _outcome(bot, pending, reveal, verdict)


async def _start_raid(bot: Bot, chat_id: int) -> str | None:
    if _raid_running(chat_id):
        return "Налёт уже идёт"
    if not game.raid_victims(chat_id):
        return "Не у кого воровать"
    token = secrets.token_hex(4)
    header = f"{em('rat')} <b>Налёт крысы!</b>"
    text = (
        f"{header}\n\nЖми кнопку первым — поймаешь крысу.\n"
        f"<blockquote>{em('trap')} Поймал: +{points_word(S('rat_catch_bonus'))}\n"
        f"{em('money')} Никто не поймал: −{S('rat_raid_steal')}% у всех\n"
        f"{_wait_line(chat_id, 'заберу у всех', 'Не поймаете')}</blockquote>"
    )
    markup = kb([btn("Поймать крысу", f"rr:{token}", emoji="trap", style="success")])
    message = await bot.send_message(
        chat_id, text, reply_markup=markup, reply_parameters=reply_to(game.last_chat_msg(chat_id)),
    )
    game.log_inc(chat_id, "rat_visits")
    _add(token, Pending(kind="raid", chat_id=chat_id, header=header, message_id=message.message_id))
    return None


async def resolve_raid(bot: Bot, token: str, catcher_id: int | None) -> None:
    pending = _take(token)
    if not pending:
        return
    chat_id = pending.chat_id
    if not game.event_active(chat_id):
        await _finish_message(bot, pending, pending.header + "\n\n<i>Ивент завершён.</i>")
        return

    if catcher_id is not None:
        catcher = game.get_player(chat_id, catcher_id)
        bonus = S("rat_catch_bonus")
        game.add_points(chat_id, catcher_id, bonus)
        game.log_inc(chat_id, "rat_caught")
        name = mention(catcher_id, catcher["name"])
        verdict = (
            f"{em('trap')} <b>Поймал!</b> {name} +{points_word(bonus)}\n{_say(texts.RAT_RAID_CAUGHT, 'rat')}"
        )
        await _outcome(bot, pending, f"{em('trap')} Крыса поймана", verdict)
        return

    lines, total = [], 0
    for victim in game.raid_victims(chat_id):
        vname = mention(victim["user_id"], victim["name"])
        if S("legend_immunity") and game.is_legend(victim["user_id"]):
            lines.append(f"{em('crown')} {vname} — не тронута")
            continue
        stolen = game.steal(chat_id, victim["user_id"], S("rat_raid_steal"))
        if stolen:
            total += stolen
            lines.append(f"{vname} −{stolen}")
    game.log_inc(chat_id, "rat_stolen", total)
    shown = lines[:15]
    if len(lines) > 15:
        shown.append(f"…и ещё {len(lines) - 15}")
    verdict = (
        f"{em('money')} <b>Никто не поймал!</b> Унесено {points_word(total)}\n"
        + (f"<blockquote>" + "\n".join(shown) + "</blockquote>\n" if shown else "")
        + _say(texts.RAT_RAID_DONE, "rat")
    )
    await _outcome(bot, pending, f"{em('rat')} Крыса ушла с добычей", verdict)


RESOLVERS = {"killer": resolve_killer, "cups": resolve_rat, "quiz": resolve_rat, "raid": resolve_raid}


# ─── Старт, стоп, победа ──────────────────────────────────────────────────


NEXT: dict[int, dict[str, float]] = {}


def top_text(chat_id: int, limit: int | None = None) -> str:
    rows = game.top(chat_id, limit or S("top_size"))
    if not rows:
        return "<i>Пока никто не крутил.</i>"
    lines = []
    for i, row in enumerate(rows):
        place = texts.place_icon(i + 1)
        status = (hearts(row["deaths"]) if S("top_hearts") else "") if row["alive"] else em("skull")
        lines.append(f"{place} {mention(row['user_id'], row['name'])} — <b>{row['points']}</b> {status}")
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


RESULTS_BUDGET = 3300  # видимых символов на сообщение (лимит Telegram — 4096)


def _visible_len(html: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html))


def _result_line(place: int, row, prizes: dict) -> str:
    who = mention(row["user_id"], row["name"])  # ник — ссылка на профиль, человек получает отметку
    status = f" {em('skull')}" if not row["alive"] else ""
    shown = S("prizes_in_top") and place in prizes and row["points"] > 0
    prize = f" · {texts.prize_short(prizes[place])}" if shown else ""
    return f"{texts.place_icon(place)} {who} — <b>{points_word(row['points'])}</b>{status}{prize}"


def results_parts(chat_id: int) -> list[str]:
    """Итоги ивента: все участники одним списком. Если их очень много — продолжение следующими сообщениями."""
    rows = game.ranked(chat_id)
    if not rows:
        return ["<blockquote><i>Никто не играл.</i></blockquote>"]
    prizes = game.prizes()
    lines = [_result_line(i, row, prizes) for i, row in enumerate(rows, 1)]
    chunks: list[list[str]] = [[]]
    for line in lines:
        if chunks[-1] and _visible_len("\n".join(chunks[-1] + [line])) > RESULTS_BUDGET:
            chunks.append([])
        chunks[-1].append(line)
    first = "<blockquote>" + "\n".join(chunks[0]) + "</blockquote>"
    extra = [
        f"{em('chart')} <b>Топ игроков, продолжение</b>\n<blockquote>" + "\n".join(c) + "</blockquote>"
        for c in chunks[1:]
    ]
    return [first, *extra]


def event_summary(chat_id: int) -> str:
    chat = game.get_chat(chat_id)
    row = game.get_event(chat["current_event"]) if chat and chat["current_event"] else None
    if not row:
        return ""
    return (
        f"<blockquote>{em('players')} Игроков: <b>{row['players']}</b> · "
        f"{em('slot')} прокрутов: <b>{row['spins']}</b> · джекпотов: <b>{row['jackpots']}</b>\n"
        f"{em('timer')} Ивент шёл: <b>{fmt_secs(game.event_duration(row))}</b></blockquote>"
    )


def results_texts(chat_id: int, head: str) -> list[str]:
    """Сообщения с итогами: первое — заголовок + пьедестал + все, дальше — продолжения."""
    parts = results_parts(chat_id)
    first = f"{head}\n\n{em('chart')} <b>Топ игроков</b>\n{parts[0]}"
    summary = prize_summary(chat_id)
    if summary:
        first += f"\n\n{summary}"
    return [first, *parts[1:]]


def prize_summary(chat_id: int) -> str:
    """«Итоги» под топом: кто какой приз получил. Пусто, если призов нет."""
    prizes = game.prizes()
    if not prizes or not S("show_prizes"):
        return ""
    rows = game.ranked(chat_id)
    lines = [
        f"{texts.place_title(place)} — {mention(rows[place - 1]['user_id'], rows[place - 1]['name'])}"
        f" — {texts.prize_short(prize)}"
        for place, prize in prizes.items()
        if place <= len(rows) and rows[place - 1]["points"] > 0
    ]
    if not lines:
        return ""
    return f"{em('winner')} <b>Итоги</b>\n" + "\n".join(lines)


async def send_results(bot: Bot, chat_id: int, head: str, reply: int | None):
    """Отправляет итоги (и продолжения, если участников много). Возвращает первое сообщение."""
    first_text, *rest = results_texts(chat_id, head)
    first = await bot.send_message(chat_id, first_text, reply_parameters=reply_to(reply))
    for extra in rest:
        await bot.send_message(chat_id, extra, reply_parameters=reply_to(first.message_id))
    return first


def time_left_text(chat_id: int) -> str:
    left = game.time_left(chat_id)
    if left is None:
        return "без лимита времени"
    return f"осталось {fmt_secs(left)}"


async def notify_admins(bot: Bot, text: str) -> None:
    if not S("notify_admins"):
        return
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            log.info("Админ %s не открыл личку с ботом", admin_id)


async def _pin(bot: Bot, chat_id: int, message_id: int) -> None:
    """Закрепляет сообщение и снимает предыдущий закреп бота."""
    chat = game.get_chat(chat_id)
    old = chat["pin_msg"] if chat else 0
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=S("pin_silent"))
    except TelegramAPIError as error:
        log.info("Не удалось закрепить в %s: %s", chat_id, error)
        return
    game.set_pin(chat_id, message_id)
    if old and old != message_id and S("unpin_old"):
        try:
            await bot.unpin_chat_message(chat_id, message_id=old)
        except TelegramAPIError:
            pass


def start_text(chat_id: int) -> str:
    duration = game.planned_duration(chat_id)
    length = fmt_secs(duration) if duration else "без лимита"
    return texts.rules_text("ИВЕНТ НАЧАЛСЯ!", f"{em('timer')} Длительность: <b>{length}</b>")


# ─── Настройки применяются сразу ──────────────────────────────────────────

_refresh_at = 0.0
INTERVAL_KEYS = {"killer_min": "killer", "killer_max": "killer", "rat_min": "rat", "rat_max": "rat"}


def settings_changed(key: str) -> None:
    """Вызывается после любого изменения в админке."""
    global _refresh_at
    now = time.time()
    for schedule in NEXT.values():
        if key in INTERVAL_KEYS:
            kind = INTERVAL_KEYS[key]
            schedule[kind] = now + _interval(kind)
        elif key == "pin_every":
            schedule["pin"] = now + S("pin_every") * 60
    # правка сообщения о старте — одна, через 2 сек после последнего нажатия
    _refresh_at = now + 2


async def _refresh_start_messages(bot: Bot) -> None:
    for chat_id in game.active_chats():
        chat = game.get_chat(chat_id)
        if not chat or not chat["start_msg"]:
            continue
        try:
            await bot.edit_message_text(start_text(chat_id), chat_id=chat_id, message_id=chat["start_msg"])
        except TelegramBadRequest as error:
            if "not modified" not in str(error):
                log.info("Не удалось обновить сообщение о старте в %s: %s", chat_id, error)


async def start_event(bot: Bot, chat_id: int, reply: int | None = None, duration: int | None = None) -> str | None:
    if game.event_active(chat_id):
        return "Ивент уже идёт"
    await cancel_chat(bot, chat_id)
    await lift_all_mutes(bot, chat_id)
    game.start_event(chat_id, duration)
    NEXT.pop(chat_id, None)
    message = await bot.send_message(chat_id, start_text(chat_id), reply_parameters=reply_to(reply))
    game.set_start_msg(chat_id, message.message_id)
    if S("pin_start"):
        await _pin(bot, chat_id, message.message_id)
    return None


async def set_duration(bot: Bot, chat_id: int, duration: int | None, reply: int | None = None) -> str | None:
    """Меняет время идущего ивента: duration — сколько останется с этого момента."""
    if not game.event_active(chat_id):
        return "Ивент не запущен"
    game.set_event_end(chat_id, duration)
    text = f"до конца <b>{fmt_secs(duration)}</b>" if duration else "<b>без лимита времени</b>"
    await bot.send_message(
        chat_id, f"{em('timer')} <b>Время изменено</b>\n<blockquote>{text}</blockquote>",
        reply_parameters=reply_to(reply or game.last_chat_msg(chat_id)),
    )
    return None


async def stop_event(bot: Bot, chat_id: int, reply: int | None = None) -> str | None:
    if not game.event_active(chat_id):
        return "Ивент не запущен"
    reply = reply or game.last_chat_msg(chat_id)
    game.stop_event(chat_id)
    NEXT.pop(chat_id, None)
    await cancel_chat(bot, chat_id)
    await lift_all_mutes(bot, chat_id)
    leader = game.top(chat_id, 1)
    line = (
        f"{em('crown')} {mention(leader[0]['user_id'], leader[0]['name'])} набрал больше всех очков!"
        if leader and leader[0]["points"] > 0 else "Никто не набрал очков."
    )
    await send_results(bot, chat_id, end_head(f"{line}\n<i>Ивент остановил админ.</i>"), reply)
    return None


def top_pin_text(chat_id: int) -> str:
    prizes = texts.prizes_block()
    return (
        f"{em('pin')} <b>ТОП ИВЕНТА</b>\n{em('timer')} {time_left_text(chat_id)}\n{top_text(chat_id)}"
        + (f"\n{prizes}" if prizes else "")
    )


async def pin_top(bot: Bot, chat_id: int) -> None:
    message = await bot.send_message(
        chat_id, top_pin_text(chat_id), reply_parameters=reply_to(game.last_chat_msg(chat_id)),
    )
    await _pin(bot, chat_id, message.message_id)


async def pause_event(bot: Bot, chat_id: int, duration: int, reply: int | None = None) -> str | None:
    if not game.event_active(chat_id):
        return "Ивент не запущен"
    game.pause(chat_id, duration)
    NEXT.pop(chat_id, None)
    ends = time_left_text(chat_id) if game.time_left(chat_id) is not None else ""
    frozen = "Время ивента стоит." if S("pause_freeze_time") and ends else ""
    top = f"\n\n{em('chart')} <b>Топ сейчас</b>\n{top_text(chat_id)}" if S("pause_top") else ""
    message = await bot.send_message(
        chat_id,
        f"{em('pause')} <b>ПЕРЕМЕНА!</b>\n"
        f"{em('timer')} Продолжим через <b>{fmt_secs(duration)}</b>{top}\n"
        f"<blockquote>{em('slot')} Слоты, {em('killer')} киллер и {em('rat')} крыса отдыхают. {frozen}</blockquote>",
        reply_parameters=reply_to(reply or game.last_chat_msg(chat_id)),
    )
    if S("pause_pin"):
        await _pin(bot, chat_id, message.message_id)
    return None


async def resume_event(bot: Bot, chat_id: int, reply: int | None = None) -> str | None:
    if not game.is_paused(chat_id):
        return "Перемены нет"
    game.resume(chat_id)
    NEXT.pop(chat_id, None)
    if S("pause_resume_msg"):
        left = f"\n<blockquote>{em('timer')} До конца ивента {time_left_text(chat_id)}</blockquote>" \
            if game.time_left(chat_id) is not None else ""
        await bot.send_message(
            chat_id,
            f"{em('fire')} <b>Перемена окончена! Крутим</b> {em('slot')}{left}",
            reply_parameters=reply_to(reply or game.last_chat_msg(chat_id)),
        )
    return None


async def final_alert(bot: Bot, chat_id: int) -> None:
    left = game.time_left(chat_id) or 0
    await bot.send_message(
        chat_id,
        f"{em('timer')} <b>Осталось {fmt_secs(left)}!</b>\n\n"
        f"{em('chart')} <b>Топ сейчас</b>\n{top_text(chat_id)}\n"
        f"<blockquote>{em('killer')} {em('rat')} Кто не ответил киллеру и крысе — уже потерял очки.\n"
        f"Новые не придут. Крути до конца!</blockquote>",
        reply_parameters=reply_to(game.last_chat_msg(chat_id)),
    )


async def finish_by_time(bot: Bot, chat_id: int) -> None:
    leader = game.top(chat_id, 1)
    has_winner = bool(leader and leader[0]["points"] > 0)
    game.stop_event(chat_id, "time", leader[0]["user_id"] if has_winner else None)
    if leader and leader[0]["points"] > 0:
        row = leader[0]
        await announce_winner(
            bot, chat_id, row["user_id"], row["name"], row["points"],
            "набрал больше всех очков!",
            reply=game.last_chat_msg(chat_id),
        )
        return
    NEXT.pop(chat_id, None)
    await cancel_chat(bot, chat_id)
    await lift_all_mutes(bot, chat_id)
    await send_results(
        bot, chat_id, end_head("Никто не набрал очков — победителя нет."),
        game.last_chat_msg(chat_id),
    )


async def announce_nft(bot: Bot, chat_id: int, user_id: int, name: str, reply: int | None = None) -> None:
    game.log_inc(chat_id, "nfts")
    await bot.send_message(
        chat_id,
        f"{em('gift')} <b>NFT!</b> {mention(user_id, name)}\n<blockquote>Джекпот принёс NFT. Админы свяжутся.</blockquote>",
        reply_parameters=reply_to(reply),
    )
    chat = game.get_chat(chat_id)
    await notify_admins(
        bot,
        f"{em('gift')} <b>Выдай NFT</b>\n<blockquote>{mention(user_id, name)} · <code>{user_id}</code>\n"
        f"Чат: {escape(chat['title'] if chat else str(chat_id))}</blockquote>",
    )


def end_head(line: str = "") -> str:
    """Шапка итогов: «ИВЕНТ ОКОНЧЕН!» и строка о победителе."""
    return f"{em('winner')} <b>ИВЕНТ ОКОНЧЕН!</b> {em('party')}" + (f"\n{line}" if line else "")


def winner_head(who: str, reason: str, nft: bool = False) -> str:
    bonus = f"\n{em('gift')} + NFT за джекпот" if nft else ""
    return end_head(f"{em('crown')} {who} {reason}{bonus}")


async def announce_winner(
    bot: Bot, chat_id: int, user_id: int, name: str, points: int, reason: str,
    *, nft: bool = False, reply: int | None = None,
) -> None:
    game.record_win(chat_id, user_id, name, points)
    if nft:
        game.log_inc(chat_id, "nfts")
    NEXT.pop(chat_id, None)
    await cancel_chat(bot, chat_id)
    await lift_all_mutes(bot, chat_id)

    who = mention(user_id, name)
    prizes = game.prizes()
    prize = f"{em('gift')} Приз: {texts.prize_html(prizes[1])}\n" if 1 in prizes else ""
    victory = await send_results(bot, chat_id, winner_head(who, reason, nft), reply)
    if S("pin_winner"):
        await _pin(bot, chat_id, victory.message_id)

    if S("congrats"):
        for icon_key, pool in (("killer", texts.KILLER_CONGRATS), ("rat", texts.RAT_CONGRATS)):
            await asyncio.sleep(2)
            await bot.send_message(
                chat_id, f"<blockquote>{em(icon_key)} «{texts.pick(pool, name=who)}»</blockquote>",
                reply_parameters=reply_to(victory.message_id),
            )

    your_prize = prize or f"{em('gift')} Приз — админы свяжутся\n"
    try:
        await bot.send_message(
            user_id,
            f"{em('winner')} <b>Ты чемпион 777!</b>\n"
            f"<blockquote>{your_prize}"
            f"{em('crown')} Крыса тебя больше не тронет\n"
            f"{em('edit')} Придумай свои фразы киллеру и крысе</blockquote>\n"
            f"Жми /reward",
        )
    except TelegramAPIError:
        pass


# ─── Фоновый цикл ─────────────────────────────────────────────────────────

def _interval(kind: str) -> float:
    low, high = sorted((S(f"{kind}_min"), S(f"{kind}_max")))
    return random.uniform(low, high)


async def _tick(bot: Bot) -> None:
    global _refresh_at
    if _refresh_at and time.time() >= _refresh_at:
        _refresh_at = 0.0
        await _refresh_start_messages(bot)

    for row in game.due_mutes():
        await release(bot, row)

    for chat_id in game.expired_chats():
        try:
            await finish_by_time(bot, chat_id)
        except TelegramAPIError as error:
            log.warning("Не удалось завершить ивент в %s: %s", chat_id, error)

    for chat_id in game.due_resumes():
        try:
            await resume_event(bot, chat_id)
        except TelegramAPIError as error:
            log.warning("Не удалось закончить перемену в %s: %s", chat_id, error)

    for chat_id in {p.chat_id for p in PENDING.values()}:
        if game.in_final_window(chat_id) and not game.is_paused(chat_id):
            try:
                await expire_chat(bot, chat_id)
            except TelegramAPIError as error:
                log.warning("Не удалось закрыть ожидания в %s: %s", chat_id, error)

    now = time.time()
    active = game.active_chats()
    for chat_id in list(NEXT):
        if chat_id not in active:
            NEXT.pop(chat_id)
    for chat_id in active:
        if game.is_paused(chat_id):
            continue
        schedule = NEXT.setdefault(chat_id, {
            "killer": now + _interval("killer"),
            "rat": now + _interval("rat"),
            "pin": now + S("pin_every") * 60,
        })
        if S("final_alert") and not schedule.get("final") and game.in_final_window(chat_id):
            schedule["final"] = 1
            try:
                await final_alert(bot, chat_id)
            except TelegramAPIError as error:
                log.warning("Не удалось предупредить о конце в %s: %s", chat_id, error)
        if now >= schedule["pin"]:
            schedule["pin"] = now + S("pin_every") * 60
            if S("pin_top"):
                try:
                    await pin_top(bot, chat_id)
                except TelegramAPIError as error:
                    log.warning("Не удалось отправить топ в %s: %s", chat_id, error)
        for kind, summon in (("killer", summon_killer), ("rat", summon_rat)):
            if now < schedule[kind]:
                continue
            schedule[kind] = now + _interval(kind)
            if S(f"{kind}_on") and random.random() * 100 < S(f"{kind}_chance"):
                try:
                    await summon(bot, chat_id)
                except TelegramAPIError as error:
                    log.warning("%s не смог выйти в чат %s: %s", kind, chat_id, error)


async def game_loop(bot: Bot) -> None:
    while True:
        try:
            await _tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в игровом цикле")
        await asyncio.sleep(1)
