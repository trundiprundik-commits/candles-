# Candles (сайт)

Веб-приложение «Свечи»: Яндекс-вход, вкладки, SQLite локально или Postgres в Docker.

Локально без Docker: SQLite в `data/candles.db`.

```text
python -m pip install -r requirements.txt
python -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

Туннель для теста: `python run_tunnel.py`.

## Один сервер: сайт + Postgres (без Managed Yandex)

На любой Ubuntu VPS (дешёвый Timeweb / Beget / FirstVDS, или бесплатный Oracle Cloud Always Free):

1. Установи Docker: https://docs.docker.com/engine/install/ubuntu/
2. Скопируй папку проекта на сервер.
3. Скопируй `.env.example` → `.env`, заполни ключи Яндекса, `SESSION_SECRET`, `POSTGRES_PASSWORD`, `PUBLIC_BASE_URL=http://IP_СЕРВЕРА:8000` (позже https).
4. В oauth.yandex.ru Redirect URI: `http://IP:8000/auth/callback` (или https, когда сделаешь).
5. Запуск:

```text
docker compose up -d --build
```

Сайт: `http://IP:8000`. Postgres слушает **только внутри Docker**, снаружи порт 5432 не открываем.

Данные: `python show_db.py` локально (SQLite). На сервере:

```text
docker compose exec db psql -U candles -d candles -c "SELECT user_id, left(payload,80) FROM kv;"
```

Десктоп: `C:\Users\north\py-candles-desktop`.
