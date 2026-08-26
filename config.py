"""Конфиг: пути, env, константы настроек."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "candles.db"
STATIC = ROOT / "static"

TAB_IDS = ("health", "repose", "thanks", "event", "other")
YANDEX_AUTHORIZE = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN = "https://oauth.yandex.ru/token"
YANDEX_INFO = "https://login.yandex.ru/info"

SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "").strip()
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

DEFAULT_SETTINGS = {
    "life_small_sec": 5400,
    "life_large_sec": 10800,
    "life_xl_sec": 21600,
    "check_interval_sec": 300,
    "price_small_rub": 0,
    "price_large_rub": 0,
    "price_xl_rub": 0,
    "payment_mode": "off",  # off | mock
}

PAYMENT_MODES = frozenset({"off", "mock"})
CANDLE_SIZES = frozenset({"small", "large", "xl"})
