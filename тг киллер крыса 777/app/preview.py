"""Предпросмотр: образцы сообщений бота, собранные на тестовых игроках.

Тексты собираются на копии базы в памяти, поэтому настоящие ивенты не затрагиваются.
"""
import re
import sqlite3
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app import db, events, game
from app.emoji import em
from app.ui import mention

SAMPLE_CHAT = -1000000000777
DEMO_NFT = "https://t.me/nft/PlushPepe-1234"
SAMPLE_PLAYERS = [  # имя, @username, очки, жив ли
    ("s7", "s7_nick", 30, True),
    ("theme", "theme", 19, True),
    ("Вася", "", 16, True),
    ("Петя", "petya", 13, True),
    ("Коля", "", 10, False),
    ("Маша", "masha", 7, True),
    ("Дима", "", 6, True),
    ("Лена", "lena", 5, True),
    ("Артём", "", 4, True),
    ("Кира", "kira", 3, True),
    ("Макс", "", 2, True),
    ("Оля", "olya", 1, True),
]


def build_samples(viewer_id: int) -> list[tuple[str, str]]:
    """Список (подпись, текст сообщения). Первого тестового игрока делаем самим зрителем — ссылка рабочая."""
    real = db._conn
    memory = sqlite3.connect(":memory:")
    memory.row_factory = sqlite3.Row
    real.backup(memory)
    db._conn = memory
    try:
        demo = not game.prizes()
        if demo:  # призы ещё не заданы — показываем пример
            game.set_prize(1, "nft", DEMO_NFT)
            game.set_prize(2, "stars", "500")
            game.set_prize(3, "stars", "250")
        game.upsert_chat(SAMPLE_CHAT, "Предпросмотр")
        game.start_event(SAMPLE_CHAT, 20 * 3600)
        now = time.time()
        for i, (name, username, points, alive) in enumerate(SAMPLE_PLAYERS):
            user_id = viewer_id if i == 0 else 1000 + i
            game.ensure_player(SAMPLE_CHAT, user_id, name, username)
            db.run(
                "UPDATE players SET points = ?, alive = ?, deaths = ?, spins = ?, last_spin = ? "
                "WHERE chat_id = ? AND user_id = ?",
                points, int(alive), 0 if alive else 3, points * 4, now - i, SAMPLE_CHAT, user_id,
            )
        start = events.start_text(SAMPLE_CHAT)
        top = events.top_pin_text(SAMPLE_CHAT)
        # тестовый ивент «шёл» 20 часов
        db.run("UPDATE events_log SET started = ? WHERE chat_id = ?", now - 20 * 3600, SAMPLE_CHAT)
        game.stop_event(SAMPLE_CHAT, "time", viewer_id)
        leader = mention(viewer_id, SAMPLE_PLAYERS[0][0])
        results = events.results_texts(
            SAMPLE_CHAT, events.winner_head(leader, "набрал больше всех очков!"),
        )
    finally:
        db._conn = real
        memory.close()
    note = " · призы для примера, свои задай в /admin → Призы" if demo else ""
    return [
        (f"Старт ивента{note}", start),
        ("Закреп топа", top),
        *[("Итоги ивента", text) for text in results],
    ]


async def send_previews(bot: Bot, chat_id: int, only: str | None = None) -> None:
    """only — прислать только образцы, в названии которых есть одно из слов через запятую («Итоги, Отчёт»)."""
    words = [word.strip().lower() for word in (only or "").split(",") if word.strip()]
    samples = [
        (title, text) for title, text in build_samples(chat_id)
        if not words or any(word in title.lower() for word in words)
    ]
    await bot.send_message(chat_id, f"{em('info')} <b>Предпросмотр</b> — так сообщения выглядят в чате:")
    for title, text in samples:
        body = f"<i>▸ {title}</i>\n\n{text}"
        try:
            await bot.send_message(chat_id, body)
        except TelegramAPIError:
            # у тестовых игроков нет настоящих профилей — без ссылок, если Telegram их не принял
            await bot.send_message(chat_id, re.sub(r'<a href="tg://user\?id=\d+">(.*?)</a>', r"\1", body))
