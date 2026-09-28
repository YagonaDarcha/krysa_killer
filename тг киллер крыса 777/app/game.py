"""Игровая логика и работа с базой: чаты, игроки, баллы, смерти, муты, чемпионы."""
import json
import random
import time
from dataclasses import dataclass

from app import db
from app.settings import get as S

# Значение кубика 🎰 (1–64) → комбинация из трёх одинаковых символов
COMBOS = {64: "seven", 43: "lemon", 22: "grapes", 1: "bar"}
COMBO_POINTS = {"seven": "pts_777", "lemon": "pts_lemon", "grapes": "pts_grapes", "bar": "pts_bar"}


# ─── Чаты и ивенты ─────────────────────────────────────────────────────────

def upsert_chat(chat_id: int, title: str, bot_in: bool = True) -> None:
    db.run(
        "INSERT INTO chats(chat_id, title, bot_in) VALUES(?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, bot_in = excluded.bot_in",
        chat_id, title or "", int(bot_in),
    )


def get_chat(chat_id: int):
    return db.one("SELECT * FROM chats WHERE chat_id = ?", chat_id)


def all_chats():
    return db.all("SELECT * FROM chats ORDER BY bot_in DESC, event_active DESC, title")


def forget_chat(chat_id: int) -> None:
    db.run("DELETE FROM chats WHERE chat_id = ?", chat_id)
    db.run("DELETE FROM players WHERE chat_id = ?", chat_id)


def event_active(chat_id: int) -> bool:
    row = db.one("SELECT event_active FROM chats WHERE chat_id = ?", chat_id)
    return bool(row and row["event_active"])


def active_chats() -> list[int]:
    return [row["chat_id"] for row in db.all("SELECT chat_id FROM chats WHERE event_active = 1")]


def start_event(chat_id: int, duration: int | None = None) -> None:
    """duration — длительность в секундах, None — без ограничения по времени."""
    now = time.time()
    db.run("DELETE FROM players WHERE chat_id = ?", chat_id)
    db.run(
        "UPDATE chats SET event_active = 1, event_started = ?, event_ends = ?, "
        "paused_at = 0, paused_until = 0 WHERE chat_id = ?",
        now, now + duration if duration else 0, chat_id,
    )
    cursor = db.run("INSERT INTO events_log(chat_id, started, planned) VALUES(?, ?, ?)", chat_id, now, duration or 0)
    db.run("UPDATE chats SET current_event = ? WHERE chat_id = ?", cursor.lastrowid, chat_id)


def set_event_end(chat_id: int, duration: int | None) -> None:
    ends = time.time() + duration if duration else 0
    db.run("UPDATE chats SET event_ends = ? WHERE chat_id = ?", ends, chat_id)


def stop_event(chat_id: int, reason: str = "stopped", winner_id: int | None = None) -> None:
    """Завершает ивент. reason: winner — набрал цель, time — вышло время, stopped — остановил админ."""
    chat = get_chat(chat_id)
    if chat and chat["event_active"] and chat["current_event"]:
        now = time.time()
        paused = now - chat["paused_at"] if chat["paused_until"] else 0
        stats = db.one(
            "SELECT COUNT(*) AS players, COALESCE(SUM(spins), 0) AS spins, "
            "COALESCE(SUM(jackpots), 0) AS jackpots, COALESCE(SUM(points), 0) AS points "
            "FROM players WHERE chat_id = ?", chat_id,
        )
        winner = get_player(chat_id, winner_id) if winner_id else None
        db.run(
            "UPDATE events_log SET ended = ?, reason = ?, paused = paused + ?, players = ?, spins = ?, "
            "jackpots = ?, points_total = ?, winner_id = ?, winner_name = ?, winner_points = ? WHERE id = ?",
            now, reason, paused, stats["players"], stats["spins"], stats["jackpots"], stats["points"],
            winner["user_id"] if winner else 0, winner["name"] if winner else "",
            winner["points"] if winner else 0, chat["current_event"],
        )
    db.run(
        "UPDATE chats SET event_active = 0, event_ends = 0, paused_at = 0, paused_until = 0 WHERE chat_id = ?",
        chat_id,
    )


def time_left(chat_id: int) -> float | None:
    """Сколько секунд осталось до конца ивента; None — ивент без ограничения по времени."""
    chat = get_chat(chat_id)
    if not chat or not chat["event_ends"]:
        return None
    now = chat["paused_at"] if chat["paused_until"] and S("pause_freeze_time") else time.time()
    return max(0.0, chat["event_ends"] - now)


def expired_chats() -> list[int]:
    rows = db.all(
        "SELECT chat_id FROM chats WHERE event_active = 1 AND event_ends > 0 AND event_ends <= ? "
        "AND (paused_until = 0 OR ? = 0)", time.time(), int(S("pause_freeze_time")),
    )
    return [row["chat_id"] for row in rows]


# ─── Журнал ивентов ────────────────────────────────────────────────────────

LOG_COUNTERS = {"pauses", "killer_visits", "killer_hits", "rat_visits", "rat_stolen", "rat_caught", "nfts"}


def backfill_running_events() -> None:
    """Ивентам, запущенным до появления журнала, заводим запись задним числом."""
    for chat in db.all("SELECT * FROM chats WHERE event_active = 1 AND current_event = 0"):
        planned = int(chat["event_ends"] - chat["event_started"]) if chat["event_ends"] else 0
        cursor = db.run(
            "INSERT INTO events_log(chat_id, started, planned) VALUES(?, ?, ?)",
            chat["chat_id"], chat["event_started"] or time.time(), max(0, planned),
        )
        db.run("UPDATE chats SET current_event = ? WHERE chat_id = ?", cursor.lastrowid, chat["chat_id"])


def log_inc(chat_id: int, field: str, amount: int = 1) -> None:
    assert field in LOG_COUNTERS
    chat = get_chat(chat_id)
    if chat and chat["current_event"] and amount:
        db.run(f"UPDATE events_log SET {field} = {field} + ? WHERE id = ?", amount, chat["current_event"])


def event_duration(row) -> float:
    """Сколько ивент реально шёл, без перемен."""
    end = row["ended"] or time.time()
    return max(0.0, end - row["started"] - row["paused"])


def chat_events(chat_id: int, limit: int, offset: int = 0):
    return db.all(
        "SELECT * FROM events_log WHERE chat_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", chat_id, limit, offset,
    )


def chat_events_count(chat_id: int) -> int:
    return db.one("SELECT COUNT(*) AS n FROM events_log WHERE chat_id = ?", chat_id)["n"]


def chat_stats(chat_id: int):
    return db.one(
        "SELECT COUNT(*) AS events, COALESCE(SUM(spins), 0) AS spins, COALESCE(SUM(jackpots), 0) AS jackpots, "
        "COALESCE(MAX(players), 0) AS max_players, COALESCE(SUM(nfts), 0) AS nfts, "
        "COALESCE(SUM(CASE WHEN ended > 0 THEN ended - started - paused ELSE 0 END), 0) AS total_time, "
        "COALESCE(SUM(CASE WHEN ended > 0 THEN 1 ELSE 0 END), 0) AS finished "
        "FROM events_log WHERE chat_id = ?", chat_id,
    )


def chat_champions(chat_id: int, limit: int = 3):
    return db.all(
        "SELECT winner_name AS name, COUNT(*) AS wins FROM events_log WHERE chat_id = ? AND winner_id != 0 "
        "GROUP BY winner_id ORDER BY wins DESC LIMIT ?", chat_id, limit,
    )


def get_event(event_id: int):
    return db.one("SELECT * FROM events_log WHERE id = ?", event_id)


def event_number(row) -> int:
    """Порядковый номер ивента внутри чата."""
    return db.one(
        "SELECT COUNT(*) AS n FROM events_log WHERE chat_id = ? AND id <= ?", row["chat_id"], row["id"],
    )["n"]


# ─── Перемена ──────────────────────────────────────────────────────────────

def is_paused(chat_id: int) -> bool:
    chat = get_chat(chat_id)
    return bool(chat and chat["event_active"] and chat["paused_until"])


def pause_left(chat_id: int) -> float:
    chat = get_chat(chat_id)
    if not chat or not chat["paused_until"]:
        return 0.0
    return max(0.0, chat["paused_until"] - time.time())


def pause(chat_id: int, duration: int) -> None:
    """Ставит перемену. Если она уже идёт — задаёт новое время окончания."""
    now = time.time()
    chat = get_chat(chat_id)
    paused_at = chat["paused_at"] if chat and chat["paused_until"] else now
    if chat and not chat["paused_until"]:
        log_inc(chat_id, "pauses")
    db.run("UPDATE chats SET paused_at = ?, paused_until = ? WHERE chat_id = ?", paused_at, now + duration, chat_id)


def resume(chat_id: int) -> None:
    """Снимает перемену. Если время ивента стояло — конец сдвигается на длину перемены."""
    chat = get_chat(chat_id)
    if not chat or not chat["paused_until"]:
        return
    db.run("UPDATE events_log SET paused = paused + ? WHERE id = ?", time.time() - chat["paused_at"], chat["current_event"])
    if chat["event_ends"] and S("pause_freeze_time"):
        shift = time.time() - chat["paused_at"]
        db.run("UPDATE chats SET event_ends = event_ends + ? WHERE chat_id = ?", shift, chat_id)
    db.run("UPDATE chats SET paused_at = 0, paused_until = 0 WHERE chat_id = ?", chat_id)


def due_resumes() -> list[int]:
    rows = db.all(
        "SELECT chat_id FROM chats WHERE event_active = 1 AND paused_until > 0 AND paused_until <= ?", time.time(),
    )
    return [row["chat_id"] for row in rows]


def in_final_window(chat_id: int) -> bool:
    """Идут последние deadline_min минут ивента: неотвеченное сгорает, новые события не приходят."""
    left = time_left(chat_id)
    return left is not None and left <= S("deadline_min") * 60


def set_start_msg(chat_id: int, message_id: int) -> None:
    db.run("UPDATE chats SET start_msg = ? WHERE chat_id = ?", message_id, chat_id)


def planned_duration(chat_id: int) -> int:
    chat = get_chat(chat_id)
    if not chat or not chat["current_event"]:
        return 0
    row = db.one("SELECT planned FROM events_log WHERE id = ?", chat["current_event"])
    return row["planned"] if row else 0


def set_pin(chat_id: int, message_id: int) -> None:
    db.run("UPDATE chats SET pin_msg = ? WHERE chat_id = ?", message_id, chat_id)


# ─── Игроки ────────────────────────────────────────────────────────────────

def get_player(chat_id: int, user_id: int):
    return db.one("SELECT * FROM players WHERE chat_id = ? AND user_id = ?", chat_id, user_id)


def ensure_player(chat_id: int, user_id: int, name: str, username: str = ""):
    db.run(
        "INSERT INTO players(chat_id, user_id, name, username) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET name = excluded.name, username = excluded.username",
        chat_id, user_id, name, username or "",
    )
    return get_player(chat_id, user_id)


def top(chat_id: int, limit: int = 10):
    return db.all(
        "SELECT * FROM players WHERE chat_id = ? ORDER BY points DESC, last_spin ASC LIMIT ?",
        chat_id, limit,
    )


def ranked(chat_id: int):
    """Все участники ивента по местам."""
    return db.all("SELECT * FROM players WHERE chat_id = ? ORDER BY points DESC, last_spin ASC", chat_id)


def place(chat_id: int, user_id: int) -> int:
    player = get_player(chat_id, user_id)
    if not player:
        return 0
    row = db.one("SELECT COUNT(*) AS n FROM players WHERE chat_id = ? AND points > ?", chat_id, player["points"])
    return row["n"] + 1


def players_count(chat_id: int) -> int:
    return db.one("SELECT COUNT(*) AS n FROM players WHERE chat_id = ?", chat_id)["n"]


def active_targets(chat_id: int):
    """Живые игроки без мута, которые крутили недавно — их выбирают киллер и крыса."""
    now = time.time()
    return db.all(
        "SELECT * FROM players p WHERE chat_id = ? AND alive = 1 AND last_spin >= ? "
        "AND NOT EXISTS (SELECT 1 FROM mutes m WHERE m.chat_id = p.chat_id "
        "AND m.user_id = p.user_id AND m.until > ?)",
        chat_id, now - S("active_window"), now,
    )


def raid_victims(chat_id: int):
    return db.all("SELECT * FROM players WHERE chat_id = ? AND alive = 1 AND points > 0", chat_id)


def add_points(chat_id: int, user_id: int, delta: int) -> None:
    db.run(
        "UPDATE players SET points = MAX(0, points + ?) WHERE chat_id = ? AND user_id = ?",
        delta, chat_id, user_id,
    )


def steal(chat_id: int, user_id: int, percent: int) -> int:
    player = get_player(chat_id, user_id)
    if not player or player["points"] <= 0 or percent <= 0:
        return 0
    amount = max(1, player["points"] * percent // 100)
    add_points(chat_id, user_id, -amount)
    return amount


# ─── Прокрут ───────────────────────────────────────────────────────────────

def try_spin(chat_id: int, user_id: int, name: str, username: str = "") -> str:
    """Проверяет, можно ли крутить, и сразу бронирует прокрут (кулдаун).

    Возвращает: ok / no_event / paused / out / muted / cooldown
    """
    if not event_active(chat_id):
        return "no_event"
    if is_paused(chat_id):
        return "paused"
    player = ensure_player(chat_id, user_id, name, username)
    if not player["alive"]:
        return "out"
    if mute_left(chat_id, user_id) > 0:
        return "muted"
    now = time.time()
    if now - player["last_spin"] < S("cooldown"):
        return "cooldown"
    db.run(
        "UPDATE players SET last_spin = ?, spins = spins + 1 WHERE chat_id = ? AND user_id = ?",
        now, chat_id, user_id,
    )
    return "ok"


@dataclass
class SpinResult:
    combo: str | None
    gained: int
    points: int
    won: bool
    nft: bool


def apply_spin(chat_id: int, user_id: int, value: int) -> SpinResult | None:
    if not event_active(chat_id):
        return None
    player = get_player(chat_id, user_id)
    if not player or not player["alive"]:
        return None
    combo = COMBOS.get(value)
    gained = S(COMBO_POINTS[combo]) if combo else S("pts_miss")
    points = player["points"] + gained
    db.run(
        "UPDATE players SET points = ?, jackpots = jackpots + ? WHERE chat_id = ? AND user_id = ?",
        points, int(combo == "seven"), chat_id, user_id,
    )
    won = (not S("unlimited") and points >= S("target")) or (combo == "seven" and S("jackpot_win"))
    nft = combo == "seven" and S("nft_on") and random.random() * 100 < S("nft_chance")
    if won:
        stop_event(chat_id, "winner", user_id)
    return SpinResult(combo, gained, points, won, nft)


def set_last_msg(chat_id: int, user_id: int, message_id: int) -> None:
    db.run("UPDATE players SET last_msg = ? WHERE chat_id = ? AND user_id = ?", message_id, chat_id, user_id)


def last_chat_msg(chat_id: int) -> int:
    row = db.one("SELECT MAX(last_msg) AS m FROM players WHERE chat_id = ?", chat_id)
    return row["m"] or 0


# ─── Смерти и муты ─────────────────────────────────────────────────────────

@dataclass
class Death:
    deaths: int
    eliminated: bool
    mute: int


def register_death(chat_id: int, user_id: int) -> Death:
    player = get_player(chat_id, user_id)
    deaths = player["deaths"] + 1
    eliminated = deaths >= S("lives")
    if eliminated:
        mute = S("elim_min") * 60
    else:
        mute = S("mute_1") if deaths == 1 else S("mute_2")
    db.run(
        "UPDATE players SET deaths = ?, alive = ? WHERE chat_id = ? AND user_id = ?",
        deaths, int(not eliminated), chat_id, user_id,
    )
    return Death(deaths, eliminated, mute)


def revive(chat_id: int, user_id: int) -> None:
    db.run("UPDATE players SET deaths = 0, alive = 1 WHERE chat_id = ? AND user_id = ?", chat_id, user_id)


def set_mute(chat_id: int, user_id: int, until: float, restricted: bool, eliminated: bool) -> None:
    db.run(
        "INSERT INTO mutes(chat_id, user_id, until, restricted, eliminated) VALUES(?, ?, ?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET until = excluded.until, "
        "restricted = MAX(restricted, excluded.restricted), eliminated = excluded.eliminated",
        chat_id, user_id, until, int(restricted), int(eliminated),
    )


def mute_left(chat_id: int, user_id: int) -> float:
    row = db.one("SELECT until FROM mutes WHERE chat_id = ? AND user_id = ?", chat_id, user_id)
    return max(0.0, row["until"] - time.time()) if row else 0.0


def due_mutes():
    return db.all("SELECT * FROM mutes WHERE until <= ?", time.time())


def chat_mutes(chat_id: int):
    return db.all("SELECT * FROM mutes WHERE chat_id = ?", chat_id)


def delete_mute(chat_id: int, user_id: int) -> None:
    db.run("DELETE FROM mutes WHERE chat_id = ? AND user_id = ?", chat_id, user_id)


# ─── Ожидания ответа (двери киллера, игры крысы) ──────────────────────────

def save_pending(token: str, kind: str, chat_id: int, target_id: int, answer: int,
                 options: list[str], header: str, message_id: int) -> None:
    db.run(
        "INSERT OR REPLACE INTO pending(token, kind, chat_id, target_id, answer, options, header, message_id) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        token, kind, chat_id, target_id, answer, json.dumps(options, ensure_ascii=False), header, message_id,
    )


def all_pending():
    return db.all("SELECT * FROM pending")


def delete_pending(token: str) -> None:
    db.run("DELETE FROM pending WHERE token = ?", token)


# ─── Призы ─────────────────────────────────────────────────────────────────

def prizes() -> dict[int, dict]:
    """Призы на места, которые сейчас разыгрываются (с учётом числа призовых мест)."""
    rows = db.all("SELECT * FROM prizes WHERE place <= ? ORDER BY place", S("prize_places"))
    return {row["place"]: {"kind": row["kind"], "value": row["value"]} for row in rows}


def set_prize(place: int, kind: str, value: str) -> None:
    db.run(
        "INSERT INTO prizes(place, kind, value) VALUES(?, ?, ?) "
        "ON CONFLICT(place) DO UPDATE SET kind = excluded.kind, value = excluded.value",
        place, kind, value,
    )


def clear_prize(place: int) -> None:
    db.run("DELETE FROM prizes WHERE place = ?", place)


# ─── Чемпионы ──────────────────────────────────────────────────────────────

def record_win(chat_id: int, user_id: int, name: str, points: int) -> None:
    db.run(
        "INSERT INTO history(chat_id, user_id, name, points, finished) VALUES(?, ?, ?, ?, ?)",
        chat_id, user_id, name, points, time.time(),
    )
    db.run(
        "INSERT INTO legends(user_id, name, wins) VALUES(?, ?, 1) "
        "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, wins = wins + 1",
        user_id, name,
    )


def get_legend(user_id: int):
    return db.one("SELECT * FROM legends WHERE user_id = ?", user_id)


def is_legend(user_id: int) -> bool:
    return get_legend(user_id) is not None


def legends():
    return db.all("SELECT * FROM legends ORDER BY wins DESC, name")


def legend_phrases(kind: str) -> list[tuple[str, str]]:
    column = "killer_phrase" if kind == "killer" else "rat_phrase"
    rows = db.all(f"SELECT name, {column} AS phrase FROM legends WHERE {column} != ''")
    return [(row["name"], row["phrase"]) for row in rows]


def set_legend_phrase(user_id: int, kind: str, phrase: str) -> None:
    column = "killer_phrase" if kind == "killer" else "rat_phrase"
    db.run(f"UPDATE legends SET {column} = ? WHERE user_id = ?", phrase, user_id)


def clear_legend_phrases() -> None:
    db.run("UPDATE legends SET killer_phrase = '', rat_phrase = ''")
