"""БД: соединение, settings, kv payload."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from candles import empty_state, prune_state
from config import (
    DATA_DIR,
    DATABASE_URL,
    DB_PATH,
    DEFAULT_SETTINGS,
    PAYMENT_MODES,
    TAB_IDS,
    USE_POSTGRES,
)


def _pg_connect():
    import psycopg

    return psycopg.connect(DATABASE_URL)


@contextmanager
def db_conn():
    if USE_POSTGRES:
        conn = _pg_connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        DATA_DIR.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def qmark() -> str:
    return "%s" if USE_POSTGRES else "?"


def init_db() -> None:
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                user_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings_candles (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        for key, value in DEFAULT_SETTINGS.items():
            if USE_POSTGRES:
                conn.execute(
                    """
                    INSERT INTO settings_candles(key, value) VALUES(%s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, str(value)),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO settings_candles(key, value) VALUES(?, ?)
                    """,
                    (key, str(value)),
                )


def normalize_payment_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in PAYMENT_MODES else "off"


def load_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    with db_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings_candles").fetchall()
    for key, value in rows:
        if key not in DEFAULT_SETTINGS:
            continue
        if key == "payment_mode":
            out[key] = normalize_payment_mode(value)
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if key.startswith("price_"):
            out[key] = max(0, n)
        elif key == "check_interval_sec":
            out[key] = max(60, n)
        else:
            out[key] = max(60, n)
    return out


def save_settings(data: dict) -> dict:
    cleaned = {
        "life_small_sec": max(60, int(data.get("life_small_sec", DEFAULT_SETTINGS["life_small_sec"]))),
        "life_large_sec": max(60, int(data.get("life_large_sec", DEFAULT_SETTINGS["life_large_sec"]))),
        "life_xl_sec": max(60, int(data.get("life_xl_sec", DEFAULT_SETTINGS["life_xl_sec"]))),
        "check_interval_sec": max(60, int(data.get("check_interval_sec", DEFAULT_SETTINGS["check_interval_sec"]))),
        "price_small_rub": max(0, int(data.get("price_small_rub", DEFAULT_SETTINGS["price_small_rub"]))),
        "price_large_rub": max(0, int(data.get("price_large_rub", DEFAULT_SETTINGS["price_large_rub"]))),
        "price_xl_rub": max(0, int(data.get("price_xl_rub", DEFAULT_SETTINGS["price_xl_rub"]))),
        "payment_mode": normalize_payment_mode(data.get("payment_mode", DEFAULT_SETTINGS["payment_mode"])),
    }
    with db_conn() as conn:
        for key, value in cleaned.items():
            if USE_POSTGRES:
                conn.execute(
                    """
                    INSERT INTO settings_candles(key, value) VALUES(%s, %s)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (key, str(value)),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO settings_candles(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(value)),
                )
    return cleaned


def save_payload(user_id: str, payload: dict) -> None:
    blob = json.dumps(payload, ensure_ascii=False)
    with db_conn() as conn:
        if USE_POSTGRES:
            conn.execute(
                """
                INSERT INTO kv(user_id, payload) VALUES(%s, %s)
                ON CONFLICT(user_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (user_id, blob),
            )
        else:
            conn.execute(
                """
                INSERT INTO kv(user_id, payload) VALUES(?, ?)
                ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload
                """,
                (user_id, blob),
            )


def load_payload(user_id: str) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            f"SELECT payload FROM kv WHERE user_id = {qmark()}",
            (user_id,),
        ).fetchone()
    if not row:
        return empty_state()
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    state = empty_state()
    if data.get("active") in TAB_IDS:
        state["active"] = data["active"]
    tabs = data.get("tabs")
    if isinstance(tabs, dict):
        for tab in TAB_IDS:
            items = tabs.get(tab)
            if isinstance(items, list):
                state["tabs"][tab] = items
    settings = load_settings()
    pruned, changed = prune_state(state, settings)
    if changed:
        save_payload(user_id, pruned)
    return pruned
