"""Точка входа: FastAPI app, middleware, static."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import api
import auth
from config import SESSION_SECRET, STATIC
from db import init_db

app = FastAPI(title="Candles")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 30,
)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.include_router(auth.router)
app.include_router(api.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
