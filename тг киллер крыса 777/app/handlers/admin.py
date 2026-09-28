import random
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import events, game, preview, settings, texts
from app.config import ADMIN_IDS
from app.emoji import em
from app.settings import EXTRA_SECTIONS, HINTS, NUMS, SECTIONS, SHORT, TOGGLES, get as S
from app.ui import btn, fmt_secs, kb, parse_duration, plural, points_word, safe_edit, temp_reply, try_delete

router = Router()
is_admin = F.from_user.id.in_(ADMIN_IDS)


class AdminInput(StatesGroup):
    value = State()
    duration = State()
    prize = State()


PRESETS = [(3600, "1ч"), (3 * 3600, "3ч"), (6 * 3600, "6ч"), (12 * 3600, "12ч"), (20 * 3600, "20ч"), (24 * 3600, "24ч")]


def on_off(value: bool) -> str:
    return "ВКЛ" if value else "ВЫКЛ"


def toggle_btn(key: str, cb: str | None = None):
    value = S(key)
    return btn(
        TOGGLES[key].label, cb or f"a:t:{key}",
        emoji="on" if value else "off", style="success" if value else "danger",
    )


# ─── Главная ───────────────────────────────────────────────────────────────

def home_view() -> tuple[str, InlineKeyboardMarkup]:
    chats = game.all_chats()
    running = sum(1 for chat in chats if chat["event_active"])
    text = (
        f"{em('slot')} <b>Панель управления · 777</b>\n\n"
        f"{em('chat')} Чатов: <b>{len(chats)}</b> · идёт ивентов: <b>{running}</b>\n"
        f"{em('killer')} Киллер: <b>{on_off(S('killer_on'))}</b>\n"
        f"{em('rat')} Крыса: <b>{on_off(S('rat_on'))}</b>\n"
        f"{em('crown')} Чемпионов: <b>{len(game.legends())}</b>\n\n"
        f"<blockquote>{em('on')} зелёная — включено\n{em('off')} красная — выключено\n"
        f"Нажми на настройку, чтобы изменить её.</blockquote>"
    )
    sections = [
        btn(title, f"a:s:{key}", emoji=icon, style="primary")
        for key, (title, icon) in SECTIONS.items() if key not in EXTRA_SECTIONS
    ]
    markup = kb(
        [btn("Чаты и ивенты", "a:chats", emoji="chat", style="primary")],
        [btn("Призы", "a:pz", emoji="gift", style="primary")],
        *pairs(sections),
        [btn("Ещё настройки", "a:more", emoji="settings", style="primary")],
        [short_toggle("killer_on", "a:th:killer_on"), short_toggle("rat_on", "a:th:rat_on")],
        [btn("Предпросмотр", "a:preview", emoji="info", style="primary"),
         btn("Чемпионы", "a:legends", emoji="crown", style="primary")],
        [btn("Обновить", "a:home", emoji="refresh")],
    )
    return text, markup


def more_view() -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"{em('settings')} <b>Ещё настройки</b>", ""]
    for key in EXTRA_SECTIONS:
        title, icon = SECTIONS[key]
        lines.append(f"{em(icon)} <b>{title}</b> — {SECTION_NOTES[key]}")
    rows = [[btn(SECTIONS[key][0], f"a:s:{key}", emoji=SECTIONS[key][1], style="primary")] for key in EXTRA_SECTIONS]
    rows.append([btn("Назад", "a:home", emoji="back", style="primary")])
    return "\n".join(lines), kb(*rows)


# ─── Разделы настроек ─────────────────────────────────────────────────────

SECTION_NOTES = {
    "event": "Длительность ивента задаётся в «Чаты и ивенты» или командой /game 20h в чате.",
    "slots": "Сколько очков дают комбинации и как часто можно крутить.",
    "killer": "Киллер приходит к активному игроку и ждёт, пока тот выберет дверь.",
    "rat": "Крыса приходит к активному игроку или устраивает налёт на всех.",
    "rewards": "Что получает победитель ивента.",
    "top": "Как часто бот присылает топ, что закрепляет и как.",
    "chat": "Команды, предупреждения и скорость ответов бота.",
    "pause": "Пауза в ивенте: /change 10m в чате или кнопка в карточке чата.",
}


def section_view(section: str) -> tuple[str, InlineKeyboardMarkup]:
    title, icon = SECTIONS[section]
    toggles = [key for key, spec in TOGGLES.items() if spec.section == section]
    nums = [key for key, spec in NUMS.items() if spec.section == section]

    lines = [f"{em(icon)} <b>{title}</b>", f"<i>{SECTION_NOTES[section]}</i>", ""]
    if toggles:
        lines.append("<blockquote>" + "\n".join(
            f"{em('on') if S(key) else em('off')} {TOGGLES[key].label}" for key in toggles
        ) + "</blockquote>")
    if nums:
        lines.append("<blockquote>" + "\n".join(
            f"{NUMS[key].label} — <b>{settings.fmt(key)}</b>" for key in nums
        ) + "</blockquote>")

    main = [key for key in toggles if key in ("killer_on", "rat_on")]
    rest = [key for key in toggles if key not in main]
    toggle_buttons = [short_toggle(key) for key in rest]
    num_buttons = [btn(f"{SHORT[key]} · {settings.fmt_short(key)}", f"a:e:{key}") for key in nums]

    rows = [[short_toggle(key)] for key in main]
    rows += pairs(toggle_buttons) + pairs(num_buttons)
    back = "a:more" if section in EXTRA_SECTIONS else "a:home"
    rows.append([btn("Назад", back, emoji="back", style="primary")])
    return "\n".join(lines), kb(*rows)


def short_toggle(key: str, cb: str | None = None):
    value = S(key)
    return btn(
        SHORT[key], cb or f"a:t:{key}", emoji="on" if value else "off", style="success" if value else "danger",
    )


def pairs(buttons: list) -> list[list]:
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def editor_view(key: str) -> tuple[str, InlineKeyboardMarkup]:
    spec = NUMS[key]
    title, icon = SECTIONS[spec.section]
    current = S(key)
    text = (
        f"{em(icon)} {title} › <b>{spec.label}</b>\n\n"
        f"Сейчас: <b>{settings.fmt(key)}</b>\n"
        f"<blockquote>{HINTS.get(key, '')}</blockquote>"
    )
    presets = [
        btn(settings.fmt(key, value), f"a:v:{key}:{value}", style="success" if value == current else "primary")
        for value in settings.PRESETS.get(key, ()) if spec.min <= value <= spec.max
    ]
    rows = [presets[i:i + 3] for i in range(0, len(presets), 3)]
    rows.append([
        btn(f"−{settings.fmt(key, spec.step)}", f"a:n:{key}:-", style="danger"),
        btn(f"+{settings.fmt(key, spec.step)}", f"a:n:{key}:+", style="success"),
    ])
    rows.append([btn("Своё число", f"a:i:{key}", emoji="edit")])
    rows.append([btn("Назад", f"a:s:{spec.section}", emoji="back", style="primary")])
    return text, kb(*rows)


# ─── Чаты ──────────────────────────────────────────────────────────────────

def chats_view() -> tuple[str, InlineKeyboardMarkup]:
    chats = game.all_chats()
    present = [chat for chat in chats if chat["bot_in"]]
    gone = [chat for chat in chats if not chat["bot_in"]]
    running = sum(1 for chat in present if chat["event_active"])

    rows = []
    for chat in present:
        title = (chat["title"] or str(chat["chat_id"]))[:28]
        count = game.chat_events_count(chat["chat_id"])
        active = bool(chat["event_active"])
        rows.append([btn(
            f"{title} · {count} {plural(count, 'ивент', 'ивента', 'ивентов')}", f"a:c:{chat['chat_id']}",
            emoji="play" if active else "stop", style="success" if active else "danger",
        )])
    for chat in gone:
        title = (chat["title"] or str(chat["chat_id"]))[:28]
        rows.append([btn(f"{title} · бота нет", f"a:c:{chat['chat_id']}", emoji="trash")])
    rows.append([btn("Обновить", "a:chats", emoji="refresh"), btn("Назад", "a:home", emoji="back", style="primary")])

    if not chats:
        text = (
            f"{em('chat')} <b>Чаты</b>\n\n<blockquote>Пока пусто. Добавь бота в группу админом "
            f"(право мутить, удалять и закреплять) и напиши там что-нибудь.</blockquote>"
        )
    else:
        text = (
            f"{em('chat')} <b>Чаты с ботом: {len(present)}</b>\n"
            f"<blockquote>{em('play')} ивент идёт: {running}\n"
            f"{em('stop')} без ивента: {len(present) - running}"
            + (f"\n{em('trash')} бота удалили: {len(gone)}" if gone else "")
            + "</blockquote>\nНажми на чат — там управление и история."
        )
    return text, kb(*rows)


async def chat_view(bot: Bot, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    chat = game.get_chat(chat_id)
    if not chat:
        return chats_view()
    active = bool(chat["event_active"])
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        rights_ok = me.status == ChatMemberStatus.ADMINISTRATOR and me.can_restrict_members and me.can_delete_messages
    except TelegramAPIError:
        rights_ok = False
    warning = "" if rights_ok else (
        f"\n{em('warn')} <b>Боту не хватает прав.</b> Дай админку с правом ограничивать и удалять сообщения, "
        f"иначе мут работать не будет.\n"
    )
    text = (
        f"{em('chat')} <b>{escape(chat['title'] or str(chat_id))}</b>\n"
        f"<code>{chat_id}</code>\n{warning}\n"
        f"Ивент: <b>{('идёт · ' + events.time_left_text(chat_id)) if active else 'не запущен'}</b>\n"
        f"Игроков: <b>{game.players_count(chat_id)}</b>\n\n"
        f"{em('chart')} <b>Топ</b>\n{events.top_text(chat_id)}"
    )
    if active:
        rows = [
            [btn("Ивент идёт — остановить", f"a:cx:{chat_id}", emoji="on", style="success")],
            [btn("Изменить время", f"a:cd:{chat_id}", emoji="timer", style="primary")],
            [btn(f"Перемена идёт — продолжить ({fmt_secs(game.pause_left(chat_id))})", f"a:cres:{chat_id}",
                 emoji="pause", style="danger")]
            if game.is_paused(chat_id) else
            [btn("Перемена", f"a:cp:{chat_id}", emoji="pause", style="primary")],
        ]
    else:
        rows = [[btn("Ивент выключен — запустить", f"a:cd:{chat_id}", emoji="off", style="danger")]]
    if active:
        rows.append([
            btn("Киллер сейчас", f"a:ck:{chat_id}", emoji="killer", style="primary"),
            btn("Крыса сейчас", f"a:cr:{chat_id}", emoji="rat", style="primary"),
        ])
        rows.append([btn("Налёт крысы на всех", f"a:crr:{chat_id}", emoji="trap", style="primary")])
    count = game.chat_events_count(chat_id)
    rows.append([btn(f"История · {count}", f"a:h:{chat_id}:0", emoji="history", style="primary")])
    rows.append([btn("Обновить", f"a:c:{chat_id}", emoji="refresh"), btn("Убрать из списка", f"a:cdel:{chat_id}", emoji="trash", style="danger")])
    rows.append([btn("К чатам", "a:chats", emoji="back", style="primary")])
    return text, kb(*rows)


# ─── Призы ─────────────────────────────────────────────────────────────────

STARS_PRESETS = (50, 100, 250, 500, 1000, 2500)


def prizes_view() -> tuple[str, InlineKeyboardMarkup]:
    places = S("prize_places")
    prizes = game.prizes()
    lines = [
        f"{texts.place_title(place)} — "
        + (texts.prize_html(prizes[place]) if place in prizes else "<i>не задан</i>")
        for place in range(1, places + 1)
    ]
    shown = "показываются в чате" if S("show_prizes") else "скрыты в чате"
    text = (
        f"{em('gift')} <b>Призы</b> · {places} {plural(places, 'место', 'места', 'мест')}\n"
        f"<blockquote>" + "\n".join(lines) + "</blockquote>\n"
        f"<i>Видны в старте ивента, в закрепе топа и в итогах ({shown}).</i>"
    )
    rows = [
        [btn(f"{place} место · {texts.prize_plain(prizes.get(place))}", f"a:pe:{place}",
             emoji=texts.PLACE_ICONS.get(place, "gift"), style="success" if place in prizes else None)]
        for place in range(1, places + 1)
    ]
    rows.append([
        btn("Убрать место", "a:pp:-", emoji="minus", style="danger"),
        btn("Добавить место", "a:pp:+", emoji="plus", style="success"),
    ])
    rows.append([short_toggle("show_prizes", "a:pshow")])
    rows.append([btn("Назад", "a:home", emoji="back", style="primary")])
    return text, kb(*rows)


def prize_edit_view(place: int) -> tuple[str, InlineKeyboardMarkup]:
    prize = game.prizes().get(place)
    current = texts.prize_html(prize) if prize else "<i>не задан</i>"
    text = (
        f"{texts.place_title(place)}\n\n"
        f"Сейчас: {current}\n"
        f"<blockquote>Выбери, что получит игрок на этом месте.</blockquote>"
    )
    rows = [
        [btn("NFT", f"a:pnft:{place}", emoji="gift", style="primary"),
         btn("Stars", f"a:pst:{place}", emoji="star", style="primary")],
    ]
    if prize:
        rows.append([btn("Убрать приз", f"a:pdel:{place}", emoji="trash", style="danger")])
    rows.append([btn("К призам", "a:pz", emoji="back", style="primary")])
    return text, kb(*rows)


def stars_view(place: int) -> tuple[str, InlineKeyboardMarkup]:
    prize = game.prizes().get(place)
    current = int(prize["value"]) if prize and prize["kind"] == "stars" else None
    presets = [
        btn(f"{amount}", f"a:psv:{place}:{amount}", emoji="star", style="success" if amount == current else "primary")
        for amount in STARS_PRESETS
    ]
    text = f"{em('star')} <b>Stars за {place} место</b>\n<blockquote>Выбери сумму или впиши свою.</blockquote>"
    return text, kb(
        presets[:3], presets[3:],
        [btn("Своё число", f"a:psi:{place}", emoji="edit")],
        [btn("Назад", f"a:pe:{place}", emoji="back", style="primary")],
    )


# ─── История ивентов ──────────────────────────────────────────────────────

HISTORY_PAGE = 5
REASONS = {
    "winner": ("winner", "набрал цель"),
    "time": ("end", "время вышло"),
    "stopped": ("stop", "остановил админ"),
    "": ("play", "идёт сейчас"),
}


def fmt_date(ts: float) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))


def history_view(chat_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    chat = game.get_chat(chat_id)
    title = escape(chat["title"] or str(chat_id)) if chat else str(chat_id)
    stats = game.chat_stats(chat_id)
    total = stats["events"]
    head = f"{em('history')} <b>История</b> · {title}"
    if not total:
        return (
            f"{head}\n\n<blockquote>Здесь ещё не было ивентов.</blockquote>",
            kb([btn("Назад", f"a:c:{chat_id}", emoji="back", style="primary")]),
        )

    average = stats["total_time"] / stats["finished"] if stats["finished"] else 0
    champions = game.chat_champions(chat_id)
    champs = ", ".join(f"{escape(c['name'])} ({c['wins']})" for c in champions) or "пока нет"
    text = (
        f"{head}\n\n<blockquote>"
        f"{em('game')} Ивентов: <b>{total}</b>\n"
        f"{em('timer')} Всего шли: <b>{fmt_secs(stats['total_time'])}</b>"
        + (f" · в среднем <b>{fmt_secs(average)}</b>" if average else "") + "\n"
        f"{em('slot')} Прокрутов: <b>{stats['spins']}</b> · джекпотов: <b>{stats['jackpots']}</b>\n"
        f"{em('players')} Рекорд игроков: <b>{stats['max_players']}</b>\n"
        f"{em('gift')} NFT выпало: <b>{stats['nfts']}</b>\n"
        f"{em('crown')} Чаще побеждали: {champs}"
        f"</blockquote>\n{em('calendar')} <b>Ивенты</b> — нажми, чтобы открыть:"
    )

    pages = (total + HISTORY_PAGE - 1) // HISTORY_PAGE
    page = max(0, min(page, pages - 1))
    rows = []
    for row in game.chat_events(chat_id, HISTORY_PAGE, page * HISTORY_PAGE):
        icon_key, _ = REASONS.get(row["reason"], REASONS["stopped"])
        who = f" · {row['winner_name'][:14]}" if row["winner_name"] else ""
        label = f"#{game.event_number(row)} · {time.strftime('%d.%m %H:%M', time.localtime(row['started']))}{who}"
        rows.append([btn(label, f"a:he:{row['id']}:{page}", emoji=icon_key)])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("Новее", f"a:h:{chat_id}:{page - 1}", emoji="back", style="primary"))
        nav.append(btn(f"{page + 1}/{pages}", f"a:h:{chat_id}:{page}"))
        if page < pages - 1:
            nav.append(btn("Старее", f"a:h:{chat_id}:{page + 1}", emoji="next", style="primary"))
        rows.append(nav)
    rows.append([btn("Назад", f"a:c:{chat_id}", emoji="back", style="primary")])
    return text, kb(*rows)


def event_view(event_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    row = game.get_event(event_id)
    if not row:
        return f"{em('warn')} Ивент не найден.", kb([btn("К чатам", "a:chats", emoji="back", style="primary")])
    chat = game.get_chat(row["chat_id"])
    title = escape(chat["title"] or str(row["chat_id"])) if chat else str(row["chat_id"])
    icon_key, reason = REASONS.get(row["reason"], REASONS["stopped"])

    ended = f"{fmt_date(row['ended'])} · {reason}" if row["ended"] else reason
    planned = f" · план {fmt_secs(row['planned'])}" if row["planned"] else " · без лимита"
    pauses = f"\n{em('pause')} Перемен: <b>{row['pauses']}</b> · {fmt_secs(row['paused'])}" if row["pauses"] else ""
    if row["winner_id"]:
        winner = f"{em('winner')} Победитель: <b>{escape(row['winner_name'])}</b> — {points_word(row['winner_points'])}"
    else:
        winner = f"{em('winner')} Победителя нет" if row["ended"] else f"{em('winner')} Победитель ещё не определён"

    # у идущего ивента цифры по игрокам берём вживую
    if not row["ended"] and chat and chat["current_event"] == row["id"]:
        live = game.db.one(
            "SELECT COUNT(*) AS players, COALESCE(SUM(spins), 0) AS spins, COALESCE(SUM(jackpots), 0) AS jackpots, "
            "COALESCE(SUM(points), 0) AS points FROM players WHERE chat_id = ?", row["chat_id"],
        )
        players, spins, jackpots, points = live["players"], live["spins"], live["jackpots"], live["points"]
    else:
        players, spins, jackpots, points = row["players"], row["spins"], row["jackpots"], row["points_total"]

    text = (
        f"{em('game')} <b>Ивент #{game.event_number(row)}</b> · {title}\n\n"
        f"<blockquote>{em('calendar')} Старт: <b>{fmt_date(row['started'])}</b>\n"
        f"{em(icon_key)} Конец: <b>{ended}</b>\n"
        f"{em('timer')} Шёл: <b>{fmt_secs(game.event_duration(row))}</b>{planned}{pauses}</blockquote>\n"
        f"<blockquote>{winner}\n"
        f"{em('players')} Игроков: <b>{players}</b>\n"
        f"{em('slot')} Прокрутов: <b>{spins}</b> · джекпотов: <b>{jackpots}</b>\n"
        f"{em('coin')} Очков набрано: <b>{points}</b>\n"
        f"{em('gift')} NFT: <b>{row['nfts']}</b></blockquote>\n"
        f"<blockquote>{em('killer')} Киллер: приходил <b>{row['killer_visits']}</b>, попал <b>{row['killer_hits']}</b>\n"
        f"{em('rat')} Крыса: приходила <b>{row['rat_visits']}</b>, украла <b>{points_word(row['rat_stolen'])}</b>, "
        f"поймали <b>{row['rat_caught']}</b></blockquote>"
    )
    return text, kb([btn("К истории", f"a:h:{row['chat_id']}:{page}", emoji="back", style="primary")])


def duration_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    chat = game.get_chat(chat_id)
    title = escape(chat["title"] or str(chat_id)) if chat else str(chat_id)
    active = game.event_active(chat_id)
    if active:
        head = f"{em('timer')} <b>Изменить время ивента</b>\n«{title}» · {events.time_left_text(chat_id)}"
        hint = "Выбранное время отсчитается заново с этого момента."
    else:
        head = f"{em('play')} <b>Запуск ивента</b>\n«{title}»"
        hint = "Выбери, сколько будет идти ивент. Когда время выйдет, победит тот, у кого больше всех баллов."
    presets = [btn(label, f"a:go:{chat_id}:{secs}", style="success") for secs, label in PRESETS]
    markup = kb(
        presets[:3],
        presets[3:],
        [btn("Без ограничения по времени", f"a:go:{chat_id}:0", emoji="play", style="primary")],
        [btn("Своё время", f"a:cin:{chat_id}", emoji="edit", style="primary")],
        [btn("Назад", f"a:c:{chat_id}", emoji="back", style="primary")],
    )
    return f"{head}\n\n<blockquote>{hint}</blockquote>", markup


PAUSE_PRESETS = [(300, "5м"), (600, "10м"), (900, "15м"), (1800, "30м"), (3600, "1ч"), (7200, "2ч")]


def pause_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    chat = game.get_chat(chat_id)
    title = escape(chat["title"] or str(chat_id)) if chat else str(chat_id)
    status = (
        f"Сейчас перемена, ещё {fmt_secs(game.pause_left(chat_id))}. Новое время заменит текущее."
        if game.is_paused(chat_id) else "Слоты, киллер и крыса остановятся, потом ивент продолжится сам."
    )
    presets = [btn(label, f"a:pgo:{chat_id}:{secs}", style="primary") for secs, label in PAUSE_PRESETS]
    markup = kb(
        presets[:3],
        presets[3:],
        [btn("Своё время", f"a:pin:{chat_id}", emoji="edit", style="primary")],
        [btn("Назад", f"a:c:{chat_id}", emoji="back", style="primary")],
    )
    return f"{em('pause')} <b>Перемена</b>\n«{title}»\n\n<blockquote>{status}</blockquote>", markup


async def launch(bot: Bot, chat_id: int, duration: int | None) -> str | None:
    """Запускает ивент на время или меняет время уже идущего."""
    if game.event_active(chat_id):
        return await events.set_duration(bot, chat_id, duration)
    return await events.start_event(bot, chat_id, duration=duration)


# ─── Чемпионы ──────────────────────────────────────────────────────────────

def legends_view() -> tuple[str, InlineKeyboardMarkup]:
    rows = game.legends()
    lines = [f"{em('crown')} <b>Чемпионы</b>\n"]
    for row in rows[:30]:
        lines.append(f"{em('winner')} <b>{escape(row['name'])}</b> — побед: {row['wins']}")
        if row["killer_phrase"]:
            lines.append(f"   {em('killer')} «{escape(row['killer_phrase'])}»")
        if row["rat_phrase"]:
            lines.append(f"   {em('rat')} «{escape(row['rat_phrase'])}»")
    if not rows:
        lines.append("<i>Пока никто не побеждал.</i>")
    markup = kb(
        [btn("Очистить фразы чемпионов", "a:lclr", emoji="trash", style="danger")] if rows else [],
        [btn("Назад", "a:home", emoji="back", style="primary")],
    )
    return "\n".join(lines), markup


# ─── Обработчики ──────────────────────────────────────────────────────────

@router.message(Command("admin"), F.chat.type == ChatType.PRIVATE, is_admin)
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    text, markup = home_view()
    await message.reply(text, reply_markup=markup)


@router.message(Command("preview"), F.chat.type == ChatType.PRIVATE, is_admin)
async def cmd_preview(message: Message, bot: Bot):
    await preview.send_previews(bot, message.chat.id)


@router.callback_query(F.data.startswith("a:"), ~is_admin)
async def not_admin(call: CallbackQuery):
    await call.answer("Нет доступа.", show_alert=True)


@router.callback_query(F.data.startswith("a:"), is_admin)
async def on_admin(call: CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    action, arg = parts[1], parts[2] if len(parts) > 2 else ""
    message = call.message
    if action not in ("i", "cin", "pin", "pnft", "psi"):
        await state.clear()

    notice = None
    if action == "home":
        view = home_view()
    elif action == "s":
        view = section_view(arg)
    elif action == "more":
        view = more_view()
    elif action == "preview":
        await call.answer("Отправляю образцы…")
        await preview.send_previews(bot, call.from_user.id)
        return
    elif action == "pz":
        view = prizes_view()
    elif action == "pp":
        settings.put("prize_places", S("prize_places") + (1 if arg == "+" else -1))
        events.settings_changed("prize_places")
        notice = f"Призовых мест: {S('prize_places')}"
        view = prizes_view()
    elif action == "pshow":
        settings.put("show_prizes", not S("show_prizes")); events.settings_changed("show_prizes")
        view = prizes_view()
    elif action == "pe":
        view = prize_edit_view(int(arg))
    elif action == "pst":
        view = stars_view(int(arg))
    elif action == "psv":
        game.set_prize(int(arg), "stars", parts[3]); events.settings_changed("prizes")
        notice = f"{arg} место: {parts[3]} Stars"
        view = prizes_view()
    elif action == "pdel":
        game.clear_prize(int(arg)); events.settings_changed("prizes")
        notice = f"{arg} место: приз убран"
        view = prizes_view()
    elif action in ("pnft", "psi"):
        place = int(arg)
        kind = "nft" if action == "pnft" else "stars"
        await state.set_state(AdminInput.prize)
        await state.update_data(place=place, kind=kind, panel_id=message.message_id)
        ask = (
            "Пришли ссылку на NFT, например:\n<code>https://t.me/nft/PlushPepe-1234</code>"
            if kind == "nft" else "Пришли количество Stars числом, например <code>750</code>"
        )
        view = (
            f"{em('edit')} <b>{place} место</b>\n<blockquote>{ask}</blockquote>",
            kb([btn("Отмена", f"a:pe:{place}", emoji="back", style="danger")]),
        )
    elif action in ("t", "th"):
        settings.put(arg, not S(arg)); events.settings_changed(arg)
        notice = f"{TOGGLES[arg].label}: {on_off(S(arg))}"
        view = home_view() if action == "th" else section_view(TOGGLES[arg].section)
    elif action == "e":
        view = editor_view(arg)
    elif action == "v":
        settings.put(arg, int(parts[3])); events.settings_changed(arg)
        notice = f"{NUMS[arg].label}: {settings.fmt(arg)}"
        view = editor_view(arg)
    elif action == "n":
        spec = NUMS[arg]
        settings.put(arg, S(arg) + (spec.step if parts[3] == "+" else -spec.step)); events.settings_changed(arg)
        notice = f"{spec.label}: {settings.fmt(arg)}"
        view = editor_view(arg)
    elif action == "i":
        spec = NUMS[arg]
        await state.set_state(AdminInput.value)
        await state.update_data(key=arg, panel_id=message.message_id)
        view = (
            f"{em('edit')} <b>{spec.label}</b>\n\nСейчас: <b>{settings.fmt(arg)}</b>\n"
            f"<blockquote>Отправь число от {spec.min} до {spec.max} ({spec.unit})</blockquote>",
            kb([btn("Отмена", f"a:e:{arg}", emoji="back", style="danger")]),
        )
    elif action == "chats":
        view = chats_view()
    elif action == "h":
        view = history_view(int(arg), int(parts[3]))
    elif action == "he":
        view = event_view(int(arg), int(parts[3]))
    elif action == "c":
        view = await chat_view(bot, int(arg))
    elif action == "cd":
        view = duration_view(int(arg))
    elif action == "cp":
        view = pause_view(int(arg))
    elif action == "pin":
        chat_id = int(arg)
        await state.set_state(AdminInput.duration)
        await state.update_data(chat_id=chat_id, panel_id=message.message_id, mode="pause")
        view = (
            f"{em('edit')} <b>Своё время перемены</b>\n\n"
            f"<blockquote>Например: <code>10m</code> · <code>1h</code> · <code>90s</code> · <code>1h30m</code></blockquote>",
            kb([btn("Отмена", f"a:cp:{chat_id}", emoji="back", style="danger")]),
        )
    elif action == "cin":
        chat_id = int(arg)
        await state.set_state(AdminInput.duration)
        await state.update_data(chat_id=chat_id, panel_id=message.message_id, mode="launch")
        view = (
            f"{em('edit')} <b>Своё время</b>\n\nОтправь длительность, например:\n"
            f"<code>20h</code> · <code>1h30m</code> · <code>45m</code> · <code>90s</code> · <code>2d</code>",
            kb([btn("Отмена", f"a:cd:{chat_id}", emoji="back", style="danger")]),
        )
    elif action in ("go", "pgo", "cres", "cx", "ck", "cr", "crr"):
        chat_id = int(arg)
        runner = {
            "pgo": lambda: events.pause_event(bot, chat_id, int(parts[3])),
            "cres": lambda: events.resume_event(bot, chat_id),
            "go": lambda: launch(bot, chat_id, int(parts[3]) or None),
            "cx": lambda: events.stop_event(bot, chat_id),
            "ck": lambda: events.summon_killer(bot, chat_id),
            "cr": lambda: events.summon_rat(bot, chat_id, random.choice(("cups", "quiz"))),
            "crr": lambda: events.summon_rat(bot, chat_id, "raid"),
        }[action]
        try:
            error = await runner()
        except TelegramAPIError as exc:
            error = f"Telegram: {exc.message}"
        notice = error or "Готово"
        view = await chat_view(bot, chat_id)
    elif action == "cdel":
        chat_id = int(arg)
        if game.event_active(chat_id):
            await events.stop_event(bot, chat_id)
        game.forget_chat(chat_id)
        notice = "Чат убран из списка"
        view = chats_view()
    elif action == "legends":
        view = legends_view()
    elif action == "lclr":
        game.clear_legend_phrases()
        notice = "Фразы чемпионов очищены"
        view = legends_view()
    else:
        await call.answer()
        return

    await call.answer(notice or None)
    await safe_edit(message, *view)


@router.message(AdminInput.value, F.chat.type == ChatType.PRIVATE, is_admin)
async def on_admin_input(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    spec = NUMS[data["key"]]
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit() or not spec.min <= int(raw) <= spec.max:
        await temp_reply(
            message, f"{em('warn')} Нужно целое число от {spec.min} до {spec.max}.", delay=5, delete_original=True,
        )
        return
    await try_delete(message)
    settings.put(data["key"], int(raw)); events.settings_changed(data["key"])
    await state.clear()
    text, markup = editor_view(data["key"])
    try:
        await bot.edit_message_text(text, chat_id=message.chat.id, message_id=data["panel_id"], reply_markup=markup)
    except TelegramAPIError:
        await message.answer(text, reply_markup=markup)


@router.message(AdminInput.duration, F.chat.type == ChatType.PRIVATE, is_admin)
async def on_duration_input(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    duration = parse_duration(message.text or "")
    if duration is None:
        await temp_reply(
            message, f"{em('warn')} Не понял. Пример: 20h, 1h30m, 45m, 90s.", delay=5, delete_original=True,
        )
        return
    await try_delete(message)
    await state.clear()
    chat_id = data["chat_id"]
    try:
        if data.get("mode") == "pause":
            error = await events.pause_event(bot, chat_id, duration)
        else:
            error = await launch(bot, chat_id, duration)
    except TelegramAPIError as exc:
        error = f"Telegram: {exc.message}"
    text, markup = await chat_view(bot, chat_id)
    if error:
        text = f"{em('warn')} {error}\n\n{text}"
    try:
        await bot.edit_message_text(text, chat_id=message.chat.id, message_id=data["panel_id"], reply_markup=markup)
    except TelegramAPIError:
        await message.answer(text, reply_markup=markup)


@router.message(Command("game"), F.chat.type == ChatType.PRIVATE, is_admin)
async def cmd_game_private(message: Message, command: CommandObject, state: FSMContext):
    """/game — выбрать чат и время; /game 20h — сразу выбрать чат для запуска на 20 часов."""
    await state.clear()
    arg = (command.args or "").strip()
    duration = parse_duration(arg) if arg else None
    if arg and duration is None:
        await message.reply(f"{em('warn')} Не понял время. Пример: <code>/game 20h</code>, <code>/game 1h30m</code>.")
        return
    chats = game.all_chats()
    if not chats:
        await message.reply(*chats_view())
        return
    rows = []
    for chat in chats:
        title = (chat["title"] or str(chat["chat_id"]))[:40]
        cb = f"a:go:{chat['chat_id']}:{duration}" if duration else f"a:cd:{chat['chat_id']}"
        active = bool(chat["event_active"])
        rows.append([btn(title, cb, emoji="play" if active else "stop", style="success" if active else "danger")])
    head = f"на <b>{fmt_secs(duration)}</b>" if duration else ""
    await message.reply(
        f"{em('timer')} <b>Запуск ивента</b> {head}\n\nВыбери чат. Если там ивент уже идёт — изменится его время.",
        reply_markup=kb(*rows),
    )



@router.message(AdminInput.prize, F.chat.type == ChatType.PRIVATE, is_admin)
async def on_prize_input(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    raw = (message.text or "").strip()
    if data["kind"] == "nft":
        value = texts.normalize_nft_link(raw)
        error = "Нужна ссылка вида https://t.me/nft/PlushPepe-1234"
    else:
        value = raw if raw.isdigit() and 0 < int(raw) <= 1_000_000 else None
        error = "Нужно число Stars от 1 до 1 000 000"
    if value is None:
        await temp_reply(message, f"{em('warn')} {error}", delay=6, delete_original=True)
        return
    await try_delete(message)
    await state.clear()
    game.set_prize(data["place"], data["kind"], value)
    events.settings_changed("prizes")
    text, markup = prizes_view()
    try:
        await bot.edit_message_text(text, chat_id=message.chat.id, message_id=data["panel_id"], reply_markup=markup)
    except TelegramAPIError:
        await message.answer(text, reply_markup=markup)
