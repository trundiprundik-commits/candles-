"""Яндекс OAuth и проверка сессии."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from config import (
    ADMIN_PASSWORD,
    PUBLIC_BASE_URL,
    YANDEX_AUTHORIZE,
    YANDEX_CLIENT_ID,
    YANDEX_CLIENT_SECRET,
    YANDEX_INFO,
    YANDEX_TOKEN,
)
from db import upsert_user_email

router = APIRouter(tags=["auth"])


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


@router.get("/auth/login")
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


@router.get("/auth/callback")
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
    upsert_user_email(user_id, str(email))
    return RedirectResponse("/", status_code=302)


@router.post("/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})
