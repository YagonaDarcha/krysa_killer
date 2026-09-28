import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "game.db"
LOG_PATH = BASE_DIR / "bot.log"

load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("BOT_TOKEN", "").strip()


def _parse_ids(raw: str) -> set[int]:
    ids = set()
    for part in raw.replace(" ", "").split(","):
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS = _parse_ids(os.getenv("ADMIN_IDS", ""))
