"""Все настройки игры. Меняются из админ-панели и хранятся в базе."""
import json
from dataclasses import dataclass

from app import db
from app.ui import fmt_secs, points_word


@dataclass(frozen=True)
class Num:
    label: str
    default: int
    min: int
    max: int
    step: int
    unit: str
    section: str


@dataclass(frozen=True)
class Toggle:
    label: str
    default: bool
    section: str


SECTIONS = {
    "event": ("Ивент", "timer"),
    "slots": ("Слоты и очки", "slot"),
    "killer": ("Киллер", "killer"),
    "rat": ("Крыса", "rat"),
    "rewards": ("Награды", "winner"),
    # разделы за кнопкой «Ещё настройки»
    "top": ("Топ и закреп", "pin"),
    "chat": ("Чат и сообщения", "chat"),
    "pause": ("Перемена", "pause"),
}
EXTRA_SECTIONS = ("top", "chat", "pause")

TOGGLES: dict[str, Toggle] = {
    "unlimited": Toggle("Очки без лимита", True, "event"),
    "final_alert": Toggle("Предупреждать о последних минутах", True, "event"),

    "pause_top": Toggle("Топ при перемене", True, "pause"),
    "pause_pin": Toggle("Закреплять перемену", False, "pause"),
    "pause_resume_msg": Toggle("Сообщать о конце перемены", True, "pause"),
    "pause_freeze_time": Toggle("Время ивента стоит на перемене", True, "pause"),

    "pin_top": Toggle("Присылать и закреплять топ", True, "top"),
    "pin_start": Toggle("Закреплять старт ивента", True, "top"),
    "pin_winner": Toggle("Закреплять победителя", True, "top"),
    "pin_silent": Toggle("Закреп без уведомления", True, "top"),
    "unpin_old": Toggle("Снимать старый закреп", True, "top"),
    "top_hearts": Toggle("Жизни в топе", True, "top"),

    "spin_command": Toggle("Команда /spin", True, "chat"),
    "deny_msgs": Toggle("Писать «ты в муте / выбыл»", True, "chat"),
    "delete_cooldown": Toggle("Удалять 🎰 на кулдауне", True, "chat"),

    "nft_on": Toggle("Розыгрыш NFT на 777", True, "slots"),
    "jackpot_win": Toggle("777 = мгновенная победа", False, "slots"),
    "reply_empty": Toggle("Отвечать на пустые прокруты", False, "slots"),
    "allow_forwarded": Toggle("Пересланные 🎰 считаются", True, "slots"),

    "killer_on": Toggle("Киллер", True, "killer"),
    "killer_takes_life": Toggle("Не та дверь забирает жизнь", True, "killer"),
    "tg_mute": Toggle("Настоящий мут в чате", True, "killer"),
    "elim_return": Toggle("Возврат после вылета", False, "killer"),
    "killer_spare_legend": Toggle("Не трогает чемпиона", False, "killer"),
    "killer_needs_points": Toggle("Только к тем, у кого есть очки", False, "killer"),

    "rat_on": Toggle("Крыса", True, "rat"),
    "rat_cups": Toggle("Напёрстки", True, "rat"),
    "rat_quiz": Toggle("Вопрос от крысы", True, "rat"),
    "rat_raid": Toggle("Налёт на всех", True, "rat"),

    "show_prizes": Toggle("Показывать призы в чате", True, "rewards"),
    "prizes_in_top": Toggle("Приз рядом с ником в итогах", False, "rewards"),
    "congrats": Toggle("Поздравления от киллера и крысы", True, "rewards"),
    "legend_immunity": Toggle("Чемпион неуязвим для крысы", True, "rewards"),
    "legend_phrases": Toggle("Фразы чемпионов в игре", True, "rewards"),
    "notify_admins": Toggle("Уведомлять админов в личку", True, "rewards"),
}

NUMS: dict[str, Num] = {
    "pin_every": Num("Топ каждые", 15, 1, 1440, 5, "мин", "top"),
    "top_size": Num("Мест в топе", 10, 3, 30, 1, "шт", "top"),
    "slot_delay": Num("Ответ на 🎰 через", 2, 0, 10, 1, "сек", "chat"),
    "warn_delay": Num("Удалять предупреждения через", 4, 2, 60, 1, "сек", "chat"),
    "target": Num("Цель (если есть лимит)", 777, 5, 100000, 10, "очков", "event"),
    "deadline_min": Num("Штраф за неответ до конца", 10, 1, 1440, 5, "мин", "event"),
    "lives": Num("Жизней у игрока", 3, 1, 5, 1, "шт", "event"),
    "min_players": Num("Мин. активных для киллера и крысы", 1, 1, 20, 1, "шт", "event"),
    "pause_default": Num("Перемена по умолчанию", 10, 1, 240, 5, "мин", "pause"),
    "pts_miss": Num("Очки за мимо", 0, 0, 100, 1, "очков", "slots"),

    "pts_777": Num("7️⃣7️⃣7️⃣", 3, 0, 10000, 1, "очков", "slots"),
    "pts_lemon": Num("🍋🍋🍋", 1, 0, 10000, 1, "очков", "slots"),
    "pts_grapes": Num("🍇🍇🍇", 1, 0, 10000, 1, "очков", "slots"),
    "pts_bar": Num("BAR BAR BAR", 1, 0, 10000, 1, "очков", "slots"),
    "cooldown": Num("Кулдаун", 3, 0, 600, 1, "сек", "slots"),
    "nft_chance": Num("Шанс NFT на 777", 10, 0, 100, 5, "%", "slots"),
    "active_window": Num("Игрок активен", 300, 30, 7200, 30, "сек", "slots"),

    "killer_chance": Num("Шанс появления", 100, 0, 100, 10, "%", "killer"),
    "killer_min": Num("Интервал от", 90, 15, 7200, 15, "сек", "killer"),
    "killer_max": Num("Интервал до", 240, 15, 7200, 15, "сек", "killer"),
    "killer_rooms": Num("Дверей", 2, 2, 5, 1, "шт", "killer"),
    "killer_deadly": Num("Из них опасных", 1, 1, 4, 1, "шт", "killer"),
    "killer_steal": Num("Забирает", 25, 0, 100, 5, "%", "killer"),
    "mute_1": Num("Мут за 1-ю смерть", 10, 0, 3600, 5, "сек", "killer"),
    "mute_2": Num("Мут за 2-ю и дальше", 20, 0, 3600, 5, "сек", "killer"),
    "elim_min": Num("Мут при вылете", 30, 1, 1440, 5, "мин", "killer"),

    "rat_chance": Num("Шанс появления", 100, 0, 100, 10, "%", "rat"),
    "rat_min": Num("Интервал от", 120, 15, 7200, 15, "сек", "rat"),
    "rat_max": Num("Интервал до", 300, 15, 7200, 15, "сек", "rat"),
    "rat_cups_count": Num("Стаканов в напёрстках", 3, 2, 5, 1, "шт", "rat"),
    "rat_steal": Num("Ворует у одного", 15, 0, 100, 5, "%", "rat"),
    "rat_raid_steal": Num("Ворует при налёте", 10, 0, 100, 5, "%", "rat"),
    "rat_raid_chance": Num("Шанс налёта", 25, 0, 100, 5, "%", "rat"),
    "rat_catch_bonus": Num("Бонус за поимку", 10, 0, 10000, 5, "очков", "rat"),

    "prize_places": Num("Призовых мест", 3, 1, 10, 1, "шт", "rewards"),
}

_PERCENT = (0, 10, 25, 50, 75, 100)
_STEAL = (0, 5, 10, 15, 25, 50)
_POINTS = (0, 1, 2, 3, 5, 10)

# Готовые значения на экране настройки
PRESETS: dict[str, tuple[int, ...]] = {
    "pin_every": (5, 10, 15, 30, 60, 120),
    "prize_places": (1, 3, 5, 10),
    "lives": (1, 2, 3, 4, 5),
    "min_players": (1, 2, 3, 5, 10),
    "pause_default": (5, 10, 15, 30, 60),
    "pts_miss": (0, 1, 2, 3),
    "top_size": (3, 5, 10, 15, 20, 30),
    "slot_delay": (0, 1, 2, 3, 5),
    "warn_delay": (3, 4, 5, 10, 30, 60),
    "target": (100, 250, 500, 777, 1000, 2000),
    "deadline_min": (5, 10, 15, 30, 60, 120),
    "pts_777": _POINTS, "pts_lemon": _POINTS, "pts_grapes": _POINTS, "pts_bar": _POINTS,
    "cooldown": (0, 3, 5, 10, 30, 60),
    "nft_chance": (0, 5, 10, 25, 50, 100),
    "active_window": (60, 180, 300, 600, 1800, 3600),
    "killer_chance": _PERCENT, "rat_chance": _PERCENT, "rat_raid_chance": _PERCENT,
    "killer_min": (30, 60, 90, 180, 300, 600), "killer_max": (60, 120, 240, 300, 600, 1200),
    "rat_min": (60, 120, 180, 300, 600, 900), "rat_max": (120, 300, 600, 900, 1200, 1800),
    "killer_rooms": (2, 3, 4, 5), "killer_deadly": (1, 2, 3, 4), "rat_cups_count": (2, 3, 4, 5),
    "killer_steal": _STEAL, "rat_steal": _STEAL, "rat_raid_steal": _STEAL,
    "mute_1": (0, 10, 20, 30, 60, 300), "mute_2": (0, 10, 20, 30, 60, 300),
    "elim_min": (5, 10, 30, 60, 120, 1440),
    "rat_catch_bonus": (0, 5, 10, 20, 50, 100),
}

# Короткие названия для кнопок (полные — в тексте раздела)
SHORT: dict[str, str] = {
    "unlimited": "Без лимита", "final_alert": "Последние минуты",
    "show_prizes": "Призы в чате", "prize_places": "Призовых мест", "prizes_in_top": "Приз у ника",
    "lives": "Жизней", "min_players": "Мин. игроков", "pts_miss": "Мимо",
    "pause_top": "Топ", "pause_pin": "Закреп", "pause_resume_msg": "Сообщить о конце",
    "pause_freeze_time": "Время стоит", "pause_default": "По умолчанию",
    "killer_spare_legend": "Щадит чемпиона", "killer_needs_points": "Только с очками",
    "pin_top": "Топ в чат", "pin_start": "Закреп старта", "pin_winner": "Закреп победы",
    "pin_silent": "Тихий закреп", "unpin_old": "Снимать старый", "top_hearts": "Жизни в топе",
    "spin_command": "/spin", "deny_msgs": "Предупреждения", "delete_cooldown": "Чистка кулдауна",
    "top_size": "Мест", "slot_delay": "Ответ через", "warn_delay": "Удалять через",
    "nft_on": "NFT за 777", "jackpot_win": "777 = победа", "reply_empty": "Ответ на мимо",
    "allow_forwarded": "Пересылка 🎰",
    "killer_on": "Киллер", "killer_takes_life": "Отнимает жизнь", "tg_mute": "Мут в чате",
    "elim_return": "Возврат",
    "rat_on": "Крыса", "rat_cups": "Напёрстки", "rat_quiz": "Вопросы", "rat_raid": "Налёты",
    "congrats": "Поздравления", "legend_immunity": "Иммунитет", "legend_phrases": "Фразы чемпионов",
    "notify_admins": "Уведомления",
    "pin_every": "Топ каждые", "target": "Цель", "deadline_min": "Штраф",
    "pts_777": "777", "pts_lemon": "Лимоны", "pts_grapes": "Виноград", "pts_bar": "Бары",
    "cooldown": "Кулдаун", "nft_chance": "Шанс NFT", "active_window": "Активен",
    "killer_chance": "Шанс", "killer_min": "Пауза от", "killer_max": "Пауза до",
    "killer_rooms": "Дверей", "killer_deadly": "Опасных", "killer_steal": "Забирает",
    "mute_1": "Мут 1", "mute_2": "Мут 2", "elim_min": "Вылет",
    "rat_chance": "Шанс", "rat_min": "Пауза от", "rat_max": "Пауза до", "rat_cups_count": "Стаканов",
    "rat_steal": "Крадёт", "rat_raid_steal": "Налёт", "rat_raid_chance": "Шанс налёта",
    "rat_catch_bonus": "Бонус",
}

# Короткое пояснение на экране настройки
HINTS: dict[str, str] = {
    "pin_every": "Как часто бот присылает и закрепляет свежий топ в чате.",
    "prize_places": "Сколько мест получают призы. Сами призы — в «Призы» на главной.",
    "lives": "Сколько смертей от киллера выдерживает игрок. Последняя — вылет из ивента.",
    "min_players": "Киллер и крыса приходят, только если столько игроков недавно крутили.",
    "pause_default": "На сколько ставится перемена командой /change без времени.",
    "pts_miss": "Очки за прокрут без комбинации. 0 — ничего.",
    "top_size": "Сколько игроков показывать в топе.",
    "slot_delay": "Через сколько секунд бот отвечает на 🎰 — чтобы не спойлерить, пока крутится барабан.",
    "warn_delay": "Через сколько удаляются «ты в муте», «ты выбыл» и другие временные сообщения.",
    "target": "Сколько очков нужно для победы, если выключено «Очки без лимита».",
    "deadline_min": "За сколько минут до конца ивента неотвеченные киллер и крыса забирают своё.",
    "pts_777": "Очки за 777 (джекпот).",
    "pts_lemon": "Очки за 3 лимона.",
    "pts_grapes": "Очки за 3 винограда.",
    "pts_bar": "Очки за 3 бара.",
    "cooldown": "Пауза между прокрутами одного игрока.",
    "nft_chance": "Шанс получить NFT, когда выпал 777.",
    "active_window": "Сколько после своего прокрута игрок может стать целью киллера и крысы.",
    "killer_chance": "Когда подходит время, киллер приходит с этим шансом. 0% — не приходит совсем.",
    "killer_min": "Самая короткая пауза между приходами киллера.",
    "killer_max": "Самая длинная пауза между приходами киллера.",
    "killer_rooms": "Сколько дверей видит игрок.",
    "killer_deadly": "Сколько дверей опасные. Одна всегда пустая.",
    "killer_steal": "Сколько % очков забирает киллер при попадании.",
    "mute_1": "Мут после первой смерти.",
    "mute_2": "Мут после второй смерти.",
    "elim_min": "Мут после третьей смерти — вылет из ивента.",
    "rat_chance": "Когда подходит время, крыса приходит с этим шансом. 0% — не приходит совсем.",
    "rat_min": "Самая короткая пауза между приходами крысы.",
    "rat_max": "Самая длинная пауза между приходами крысы.",
    "rat_cups_count": "Сколько стаканов в напёрстках. Больше — сложнее угадать.",
    "rat_steal": "Сколько % очков крыса крадёт у одного игрока.",
    "rat_raid_steal": "Сколько % крыса крадёт у каждого при налёте.",
    "rat_raid_chance": "Шанс, что крыса устроит налёт на всех, а не пристанет к одному.",
    "rat_catch_bonus": "Сколько очков получает тот, кто поймал крысу при налёте.",
}

_values: dict = {}


def load() -> None:
    _values.clear()
    for row in db.all("SELECT key, value FROM settings"):
        if row["key"] in NUMS or row["key"] in TOGGLES:
            _values[row["key"]] = json.loads(row["value"])


def get(key: str):
    if key in _values:
        return _values[key]
    if key in NUMS:
        return NUMS[key].default
    return TOGGLES[key].default


def put(key: str, value) -> None:
    if key in NUMS:
        spec = NUMS[key]
        value = max(spec.min, min(spec.max, int(value)))
    else:
        value = bool(value)
    _values[key] = value
    db.run(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        key, json.dumps(value),
    )
    # Хоть одна дверь киллера должна быть пустой
    if key in ("killer_rooms", "killer_deadly") and get("killer_deadly") > get("killer_rooms") - 1:
        put("killer_deadly", get("killer_rooms") - 1)


def fmt(key: str, value: int | None = None) -> str:
    value = get(key) if value is None else value
    unit = NUMS[key].unit
    if unit == "сек":
        return fmt_secs(value) if value else "0 сек"
    if unit == "мин":
        return fmt_secs(value * 60)
    if unit == "%":
        return f"{value}%"
    if unit == "очков":
        return points_word(value)
    return str(value)


def fmt_short(key: str) -> str:
    """Компактное значение для кнопки: 90с, 4м, 1ч30м, 25%."""
    value = get(key)
    unit = NUMS[key].unit
    seconds = value if unit == "сек" else value * 60 if unit == "мин" else None
    if seconds is None:
        return f"{value}%" if unit == "%" else str(value)
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}м" + (f"{s}с" if s else "")
    h, m = divmod(seconds // 60, 60)
    return f"{h}ч" + (f"{m}м" if m else "")
