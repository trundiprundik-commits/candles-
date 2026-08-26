"""HTTP API: /api/* и админка."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import current_user, require_admin
from candles import clean_candle, empty_state, prune_state, utc_now_iso
from config import (
    ADMIN_PASSWORD,
    TAB_IDS,
    USE_POSTGRES,
    YANDEX_CLIENT_ID,
    YANDEX_CLIENT_SECRET,
)
from db import db_conn, load_payload, load_settings, save_payload, save_settings

router = APIRouter(tags=["api"])


@router.get("/api/me")
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


@router.get("/api/settings")
def api_settings_public() -> JSONResponse:
    return JSONResponse(load_settings())


@router.post("/api/admin/login")
async def admin_login(request: Request) -> JSONResponse:
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Задай ADMIN_PASSWORD в .env")
    body = await request.json()
    password = str((body or {}).get("password") or "")
    if password != ADMIN_PASSWORD:
        raise HTTPException(403, "Неверный пароль")
    request.session["is_admin"] = True
    return JSONResponse({"ok": True})


@router.post("/api/admin/logout")
def admin_logout(request: Request) -> JSONResponse:
    request.session.pop("is_admin", None)
    return JSONResponse({"ok": True})


@router.get("/api/admin/settings")
def admin_get_settings(request: Request) -> JSONResponse:
    require_admin(request)
    return JSONResponse(load_settings())


@router.put("/api/admin/settings")
async def admin_put_settings(request: Request) -> JSONResponse:
    require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Ожидался JSON-объект")
    return JSONResponse(save_settings(body))


@router.get("/api/admin/data")
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


@router.get("/api/state")
def get_state(request: Request) -> JSONResponse:
    user_id = current_user(request)
    if not user_id:
        raise HTTPException(401, "Нужен вход через Яндекс")
    settings = load_settings()
    state = load_payload(user_id)
    return JSONResponse({"state": state, "settings": settings, "server_time": utc_now_iso()})


@router.put("/api/state")
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
