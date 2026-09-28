"""Фразы персонажей, вопросы крысы и тексты правил."""
import random
import re
from html import escape

from app.emoji import em, plain
from app import game
from app.settings import get as S
from app.ui import fmt_secs, plural


def pick(options: list[str], **fields) -> str:
    return random.choice(options).format(**fields)


# ─── Киллер ────────────────────────────────────────────────────────────────

KILLER_MISS = [
    "Как ты ещё жив, уёбок? Револьвер заклинило.",
    "Осечка. В следующий раз повезёт меньше.",
    "Барабан пустой, а ты всё ещё дышишь.",
    "Ствол дёрнулся. Родился в рубашке.",
    "Пусто. Я терпеливый.",
]

KILLER_HIT = [
    "Заказ выполнен. Царь свергнут.",
    "Один выстрел — один труп.",
    "Голова с плеч. Следующий.",
    "Не та дверь. Бывает.",
]

KILLER_CONGRATS = [
    "Брал на тебя заказы — ни один не закрыл. Уважаю, {name}.",
    "Самая живучая цель в карьере. С победой, {name}.",
    "Снимаю шляпу и прицел. Ты победил, {name}.",
]


# ─── Крыса ─────────────────────────────────────────────────────────────────

RAT_STOLE = [
    "Ха, у кого-то стало меньше очков. Бывает.",
    "Слышал, ты копил? Уже нет.",
    "Спасибо за донат. Приходи ещё.",
    "Было твоё — стало моё.",
    "Иди плачь.",
]

RAT_ESCAPED = [
    "Тьфу. Повезло.",
    "Этот раунд твой. Я не забуду.",
    "Умный, да? Найду потупее.",
]

RAT_RAID_DONE = [
    "Спасибо за донат, нищеброды.",
    "Какие же вы медленные.",
    "Карманы пустые, крыса довольная.",
]

RAT_RAID_CAUGHT = [
    "Ай, хвост! Ухожу.",
    "Чёрт, быстрый. Сегодня без добычи.",
]

RAT_CONGRATS = [
    "Я пыталась, честно. С победой, {name}. Держи карман крепче.",
    "Даже красть у тебя теперь стыдно, {name}. Почти.",
]

# Вопросы крысы: (вопрос, правильный ответ, неверный, неверный)
QUIZ = [
    ("Сколько будет 7 × 7 × 7?", "343", "777", "49"),
    ("Какая комбинация — джекпот?", "7️⃣7️⃣7️⃣", "🍋🍋🍋", "🍇🍇🍇"),
    ("Что крыса любит больше всего?", "Чужие очки", "Сыр", "Честность"),
    ("Сколько секунд в минуте?", "60", "100", "30"),
    ("Самый короткий месяц?", "Февраль", "Апрель", "Ноябрь"),
    ("Сколько ног у паука?", "8", "6", "10"),
    ("Столица Японии?", "Токио", "Осака", "Киото"),
    ("Сколько граней у кубика?", "6", "8", "4"),
    ("Ближайшая к Солнцу планета?", "Меркурий", "Венера", "Марс"),
    ("Сколько цветов у радуги?", "7", "6", "8"),
    ("Что тяжелее: кг ваты или кг железа?", "Одинаково", "Железо", "Вата"),
    ("Сколько часов в сутках?", "24", "12", "36"),
    ("Какое число после 776?", "777", "778", "767"),
    ("2 + 2 × 2 = ?", "6", "8", "4"),
    ("Чем мы дышим?", "Кислородом", "Азотом", "Гелием"),
    ("Самое большое животное?", "Синий кит", "Слон", "Жираф"),
    ("Дней в високосном году?", "366", "365", "364"),
    ("Кто ворует очки в этом чате?", "Крыса", "Киллер", "Админ"),
    ("Сколько букв в слове «крыса»?", "5", "4", "6"),
    ("Какой фрукт есть на слоте?", "Лимон", "Банан", "Арбуз"),
    ("100 − 23 = ?", "77", "87", "67"),
    ("Минут в полутора часах?", "90", "150", "60"),
    ("Сколько материков на Земле?", "6", "5", "8"),
]


# ─── Правила ──────────────────────────────────────────────────────────────

COMBO_TITLE = {"seven": "ДЖЕКПОТ !", "lemon": "Лимоны !", "grapes": "Виноград !", "bar": "Бары !"}
COMBO_DROP = {"seven": "777", "lemon": "3 лимона", "grapes": "3 винограда", "bar": "3 бара"}


# ─── Призы ────────────────────────────────────────────────────────────────

PLACE_ICONS = {1: "gold", 2: "silver", 3: "bronze"}
NFT_LINK = re.compile(r"^(?:https?://)?t\.me/nft/([A-Za-z0-9]+)-(\d+)/?$")


def nft_title(link: str) -> str:
    """https://t.me/nft/PlushPepe-1234 → Plush Pepe #1234"""
    match = NFT_LINK.match(link.strip())
    if not match:
        return "NFT"
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", match.group(1))
    return f"{name} #{match.group(2)}"


def normalize_nft_link(text: str) -> str | None:
    text = text.strip()
    if not NFT_LINK.match(text):
        return None
    return text if text.startswith("http") else f"https://{text}"


FIGURE_SPACE = " "  # пробел шириной ровно в одну цифру


PLACE_PAD = " "  # добивка после номера, чтобы имена стояли под именами у медалей


def place_icon(place: int, pad: str | None = None) -> str:
    """Места в списках: 🥇🥈🥉 для первых трёх, дальше жирный номер.

    Номера выровнены по правому краю (пробел шириной в цифру перед однозначными),
    поэтому « 4.» и «10.» стоят ровно друг под другом.
    """
    if place in PLACE_ICONS:
        return em(PLACE_ICONS[place])
    shift = " "  # сдвиг на один пробел вправо — под медали
    return f"{shift}<b>{FIGURE_SPACE if place < 10 else ''}{place}.</b>{PLACE_PAD if pad is None else pad}"


def place_title(place: int) -> str:
    """«🥇 1 место» — для призов и заголовков победителей."""
    medal = f"{em(PLACE_ICONS[place])} " if place in PLACE_ICONS else ""
    return f"{medal}<b>{place} место</b>"


def prize_html(prize: dict) -> str:
    if prize["kind"] == "nft":
        return f'{em("gift")} <a href="{escape(prize["value"])}">{escape(nft_title(prize["value"]))}</a>'
    return f"{em('star')} <b>{prize['value']}</b> Stars"


def prize_short(prize: dict) -> str:
    """Короткая подпись приза для итогов: «🎁 Приз» (ссылка на NFT) или «⭐ 250»."""
    if prize["kind"] == "nft":
        return f'{em("gift")} <a href="{escape(prize["value"])}">Приз</a>'
    return f"{em('star')} <b>{prize['value']}</b>"


def prize_plain(prize: dict | None) -> str:
    """Подпись для кнопки (без разметки)."""
    if not prize:
        return "не задан"
    if prize["kind"] == "nft":
        return f"NFT · {nft_title(prize['value'])}"
    return f"{plain('star')} {prize['value']} Stars"


def prizes_block() -> str:
    """Блок «Призы» для старта, закрепа и итогов. Пусто, если призов нет или показ выключен."""
    prizes = game.prizes()
    if not prizes or not S("show_prizes"):
        return ""
    lines = [f"{place_title(place)} — {prize_html(prize)}" for place, prize in prizes.items()]
    return f"{em('gift')} <b>Призы</b>\n<blockquote>" + "\n".join(lines) + "</blockquote>"


def doors_text(n: int) -> str:
    return f"{n} {plural(n, 'дверь', 'двери', 'дверей')}"


def combo_symbols(combo: str) -> str:
    return em(f"combo_{combo}")


def combos_text() -> str:
    lines = [
        f"{combo_symbols('seven')} 777 — <b>+{S('pts_777')}</b>"
        + (f" · шанс NFT {S('nft_chance')}%" if S("nft_on") else ""),
    ]
    for combo in ("lemon", "grapes", "bar"):
        if S(f"pts_{combo}"):
            lines.append(f"{combo_symbols(combo)} {COMBO_DROP[combo]} — <b>+{S(f'pts_{combo}')}</b>")
    return "\n".join(lines)


def rules_text(title: str = "ИВЕНТ 777", subtitle: str = "") -> str:
    if S("unlimited"):
        goal = (
            "набери больше всех очков, уворачивайся от пули киллера и не дай крысе забрать "
            "твои очки — чтобы быть на 1 месте!"
        )
    else:
        goal = (
            f"первым набери <b>{S('target')}</b> очков, уворачивайся от пули киллера и не дай "
            f"крысе забрать твои очки!"
        )
    killer_loss = f"−{S('killer_steal')}% очков" + (" и жизнь" if S("killer_takes_life") else "")
    lives = S("lives")
    deaths = []
    if lives > 1:
        deaths.append(f"1-я смерть — мут {fmt_secs(S('mute_1'))}")
    if lives > 2:
        deaths.append(f"{'2-я' if lives == 3 else f'2–{lives - 1}-я'} — мут {fmt_secs(S('mute_2'))}")
    deaths.append(f"{lives}-я — вылет и мут {fmt_secs(S('elim_min') * 60)}")
    deaths_text = "\n".join(deaths)
    rooms, deadly = S("killer_rooms"), min(S("killer_deadly"), S("killer_rooms") - 1)
    rat_modes = [name for name, key in (("напёрстки", "rat_cups"), ("вопросы", "rat_quiz"), ("налёты", "rat_raid")) if S(key)]
    details = [
        f"{em('killer')} <b>Киллер</b> приходит к тем, кто крутит. "
        f"Перед тобой {doors_text(rooms)}, в {deadly} из них — он. Не та дверь: {killer_loss}.",
        f"{em('rat')} <b>Крыса</b> ворует очки: {', '.join(rat_modes) or 'отдыхает'}. "
        f"Ошибся — −{S('rat_steal')}%. При налёте жми «Поймать крысу» первым — получишь +{S('rat_catch_bonus')}.",
        f"{em('timer')} Киллер и крыса <b>ждут ответа</b>. Не ответил за {S('deadline_min')} мин до конца — теряешь очки.",
        f"{em('pause')} На <b>перемене</b> слоты, киллер и крыса отдыхают, время ивента стоит.",
    ]
    if S("nft_on"):
        details.append(f"{em('gift')} За 777 — шанс {S('nft_chance')}% на <b>NFT</b>.")
    details.append(f"{em('crown')} Победитель получает статус чемпиона — крыса его больше не тронет.")
    details.append(f"{em('info')} /lives — жизни · /me — мои очки · /top — топ · /rules — правила")
    lead = f"{subtitle}\n" if subtitle else ""
    prizes = prizes_block()
    return (
        f"{combo_symbols('seven')} <b>{title}</b>\n{lead}\n"
        f"<blockquote>{em('winner')} <b>Цель:</b> {goal}</blockquote>\n\n"
        + (f"{prizes}\n\n" if prizes else "") +
        f"{em('slot')} <b>Крути:</b> отправь 🎰 или /spin\n"
        f"<blockquote>{combos_text()}</blockquote>\n\n"
        f"{em('heart') * lives} <b>{lives} {plural(lives, 'жизнь', 'жизни', 'жизней')}</b>\n"
        f"<blockquote>{deaths_text}</blockquote>\n\n"
        f"<blockquote expandable>{em('info')} <b>Подробнее об игре</b>\n\n" + "\n\n".join(details) + "</blockquote>"
    )
