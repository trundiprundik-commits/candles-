"""Веб-сервер свечей: Яндекс ID, SQLite/Postgres, сгорание, settings_candles."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def empty_state() -> dict:
    return {"active": "health", "tabs": {tab: [] for tab in TAB_IDS}}


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


def normalize_candle_size(value: object) -> str:
    size = str(value or "").strip().lower()
    return size if size in CANDLE_SIZES else "small"


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


def parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def life_for_size(settings: dict, size: str) -> int:
    size = normalize_candle_size(size)
    if size == "xl":
        return int(settings["life_xl_sec"])
    if size == "large":
        return int(settings["life_large_sec"])
    return int(settings["life_small_sec"])


def remaining_ratio(created_at: str, size: str, settings: dict, now: datetime | None = None) -> float:
    created = parse_created_at(created_at)
    if created is None:
        return 1.0
    now = now or datetime.now(timezone.utc)
    life = life_for_size(settings, size)
    elapsed = (now - created).total_seconds()
    return max(0.0, min(1.0, 1.0 - elapsed / life))


def clean_candle(item: dict, now_iso: str) -> dict | None:
    try:
        entry = {
            "caption": str(item.get("caption") or "").strip()[:200],
            "size": normalize_candle_size(item.get("size")),
        }
        has_norm = item.get("nx") is not None and item.get("ny") is not None
        has_abs = item.get("x") is not None and item.get("y") is not None
        if has_norm:
            entry["nx"] = round(float(item["nx"]), 5)
            entry["ny"] = round(float(item["ny"]), 5)
        if has_abs:
            entry["x"] = round(float(item["x"]), 1)
            entry["y"] = round(float(item["y"]), 1)
        if not has_norm and not has_abs:
            return None
        created = parse_created_at(item.get("created_at"))
        entry["created_at"] = created.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if created else now_iso
        return entry
    except (TypeError, ValueError):
        return None


def prune_state(state: dict, settings: dict | None = None) -> tuple[dict, bool]:
    settings = settings or load_settings()
    now = datetime.now(timezone.utc)
    now_iso = utc_now_iso()
    changed = False
    result = empty_state()
    if state.get("active") in TAB_IDS:
        result["active"] = state["active"]
    tabs = state.get("tabs")
    if not isinstance(tabs, dict):
        return result, True
    for tab in TAB_IDS:
        items = tabs.get(tab)
        kept: list[dict] = []
        if not isinstance(items, list):
            changed = True
            continue
        for item in items:
            if not isinstance(item, dict):
                changed = True
                continue
            entry = clean_candle(item, now_iso)
            if entry is None:
                changed = True
                continue
            if entry["created_at"] != item.get("created_at"):
                changed = True
            if remaining_ratio(entry["created_at"], entry["size"], settings, now) <= 0:
                changed = True
                continue
            kept.append(entry)
        result["tabs"][tab] = kept
        if kept != items:
            # structural change already tracked above; ensure save if lengths differ
            if len(kept) != len(items):
                changed = True
    return result, changed


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
    pruned, changed = prune_state(state)
    if changed:
        save_payload(user_id, pruned)
    return pruned


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


def public_base(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto}://{host}"
    return str(request.base_url).rstrip("/")


def current_user(request: Request) -> str | None:
    user_id = request.session.get("user_id")
    if isinstance(user_id, str) and user_id:
        return user_id
    return None


def require_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Задай ADMIN_PASSWORD в .env")
    if not request.session.get("is_admin"):
        raise HTTPException(401, "Нужен вход в админку")


app = FastAPI(title="Candles")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 30,
)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/me")
def api_me(request: Request) -> JSONResponse:
    user_id = current_user(request)
    return JSONResponse(
        {
            "user_id": user_id,
            "email": request.session.get("email") or None,
            "login": request.session.get("login") or None,
            "display_name": request.session.get("display_name") or None,
            "is_admin": bool(request.session.get("is_admin")),
            "auth_configured": bool(YANDEX_CLIENT_ID and YANDEX_CLIENT_SECRET),
            "login_url": "/auth/login",
            "db": "postgres" if USE_POSTGRES else "sqlite",
        }
    )


@app.get("/api/settings")
def api_settings_public() -> JSONResponse:
    return JSONResponse(load_settings())


@app.post("/api/admin/login")
async def admin_login(request: Request) -> JSONResponse:
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Задай ADMIN_PASSWORD в .env")
    body = await request.json()
    password = str((body or {}).get("password") or "")
    if password != ADMIN_PASSWORD:
        raise HTTPException(403, "Неверный пароль")
    request.session["is_admin"] = True
    return JSONResponse({"ok": True})


@app.post("/api/admin/logout")
def admin_logout(request: Request) -> JSONResponse:
    request.session.pop("is_admin", None)
    return JSONResponse({"ok": True})


@app.get("/api/admin/settings")
def admin_get_settings(request: Request) -> JSONResponse:
    require_admin(request)
    return JSONResponse(load_settings())


@app.put("/api/admin/settings")
async def admin_put_settings(request: Request) -> JSONResponse:
    require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Ожидался JSON-объект")
    return JSONResponse(save_settings(body))


@app.get("/api/admin/data")
def admin_get_data(request: Request) -> JSONResponse:
    """Все строки kv + settings_candles для таблицы в админке."""
    require_admin(request)
    settings = load_settings()
    with db_conn() as conn:
        rows = conn.execute("SELECT user_id, payload FROM kv ORDER BY user_id").fetchall()
        setting_rows = conn.execute("SELECT key, value FROM settings_candles ORDER BY key").fetchall()
    users = []
    for user_id, payload in rows:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        counts = {tab: 0 for tab in TAB_IDS}
        total = 0
        if isinstance(data, dict):
            tabs = data.get("tabs")
            if isinstance(tabs, dict):
                for tab in TAB_IDS:
                    items = tabs.get(tab)
                    n = len(items) if isinstance(items, list) else 0
                    counts[tab] = n
                    total += n
        users.append(
            {
                "user_id": user_id,
                "active": data.get("active") if isinstance(data, dict) else None,
                "counts": counts,
                "total_candles": total,
                "payload": data,
            }
        )
    return JSONResponse(
        {
            "settings": settings,
            "settings_rows": [{"key": k, "value": v} for k, v in setting_rows],
            "users": users,
            "user_count": len(users),
        }
    )


@app.get("/auth/login")
def auth_login(request: Request) -> RedirectResponse:
    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        raise HTTPException(503, "Заполни YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET в .env")
    redirect_uri = f"{public_base(request)}/auth/callback"
    request.session["oauth_state"] = secrets.token_urlsafe(16)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": YANDEX_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "state": request.session["oauth_state"],
            "force_confirm": "yes",
        }
    )
    return RedirectResponse(f"{YANDEX_AUTHORIZE}?{query}")


@app.get("/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None) -> RedirectResponse:
    if not code:
        raise HTTPException(400, "Нет code от Яндекса")
    expected = request.session.get("oauth_state")
    if not expected or state != expected:
        raise HTTPException(400, "Неверный state")
    redirect_uri = f"{public_base(request)}/auth/callback"
    token_resp = httpx.post(
        YANDEX_TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": YANDEX_CLIENT_ID,
            "client_secret": YANDEX_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        },
        timeout=20,
    )
    token_resp.raise_for_status()
    access = token_resp.json().get("access_token")
    if not access:
        raise HTTPException(400, "Яндекс не отдал токен")
    info_resp = httpx.get(
        YANDEX_INFO,
        params={"format": "json"},
        headers={"Authorization": f"OAuth {access}"},
        timeout=20,
    )
    info_resp.raise_for_status()
    info = info_resp.json()
    user_id = str(info.get("id") or info.get("psuid") or "")
    if not user_id:
        raise HTTPException(400, "Яндекс не отдал id")
    email = info.get("default_email") or ""
    if not email:
        emails = info.get("emails")
        if isinstance(emails, list) and emails:
            email = str(emails[0])
    login = str(info.get("login") or "")
    display = str(info.get("display_name") or info.get("real_name") or login or email or user_id)
    is_admin = bool(request.session.get("is_admin"))
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["email"] = email
    request.session["login"] = login
    request.session["display_name"] = display
    if is_admin:
        request.session["is_admin"] = True
    return RedirectResponse("/", status_code=302)


@app.post("/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


@app.get("/api/state")
def get_state(request: Request) -> JSONResponse:
    user_id = current_user(request)
    if not user_id:
        raise HTTPException(401, "Нужен вход через Яндекс")
    settings = load_settings()
    state = load_payload(user_id)
    return JSONResponse({"state": state, "settings": settings, "server_time": utc_now_iso()})


@app.put("/api/state")
async def put_state(request: Request) -> JSONResponse:
    user_id = current_user(request)
    if not user_id:
        raise HTTPException(401, "Нужен вход через Яндекс")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Ожидался JSON-объект")
    # совместимость: либо {state, ...}, либо старый формат сразу state
    raw_state = body.get("state") if isinstance(body.get("state"), dict) else body
    state = empty_state()
    if raw_state.get("active") in TAB_IDS:
        state["active"] = raw_state["active"]
    tabs = raw_state.get("tabs")
    now_iso = utc_now_iso()
    if isinstance(tabs, dict):
        for tab in TAB_IDS:
            items = tabs.get(tab)
            if not isinstance(items, list):
                continue
            cleaned = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                entry = clean_candle(item, now_iso)
                if entry is not None:
                    cleaned.append(entry)
            state["tabs"][tab] = cleaned
    settings = load_settings()
    pruned, _ = prune_state(state, settings)
    save_payload(user_id, pruned)
    return JSONResponse({"state": pruned, "settings": settings, "server_time": utc_now_iso()})


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
