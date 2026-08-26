# Candles (сайт)

Веб-приложение «Свечи»: Яндекс-вход, вкладки, Postgres в Docker, сгорание свечей, админка.

`.env` **не** в Git (секреты только на машинах).

## Обновление через Git (вместо scp)

### Один раз на ПК

1. Установи [Git](https://git-scm.com/download/win) (уже можно пользоваться).
2. Создай пустой репозиторий на GitHub (без README) — например `candles`.
3. В папке проекта:

```text
git remote add origin https://github.com/ТВОЙ_ЛОГИН/candles.git
git push -u origin main
```

### Один раз на сервере

```text
cd ~
git clone https://github.com/ТВОЙ_ЛОГИН/candles.git
cd candles
cp .env.example .env
nano .env
docker-compose up -d --build
```

Если папка `~/candles` уже есть со старыми файлами — либо переименуй её в `candles-old`, либо:

```text
cd ~/candles
git init
git remote add origin https://github.com/ТВОЙ_ЛОГИН/candles.git
git fetch
git checkout -f main
```

`.env` на сервере не трогай Git’ом (он в `.gitignore`).

### Каждый раз, когда правишь сайт

**На ПК:**

```text
git add -A
git commit -m "описание изменений"
git push
```

**На сервере:**

```text
cd ~/candles
bash deploy.sh
```

или вручную: `git pull` и `docker-compose up -d --build`.

## Локальный запуск без Docker

```text
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Админка: `/admin.html` (пароль `ADMIN_PASSWORD` в `.env`).

Десктоп: `C:\Users\north\py-candles-desktop`.
