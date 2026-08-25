"""Поднимает веб-сервер и Cloudflare Tunnel (trycloudflare.com)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CLOUDFLARED = ROOT / "tools" / "cloudflared.exe"
DOWNLOAD = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def ensure_cloudflared() -> Path:
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    if CLOUDFLARED.exists():
        return CLOUDFLARED
    CLOUDFLARED.parent.mkdir(exist_ok=True)
    print("Скачиваю cloudflared...")
    urllib.request.urlretrieve(DOWNLOAD, CLOUDFLARED)
    return CLOUDFLARED


def main() -> None:
    os.chdir(ROOT)
    bin_path = ensure_cloudflared()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web_app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
    )
    time.sleep(1.2)
    DATA_DIR.mkdir(exist_ok=True)
    log_path = DATA_DIR / "cloudflared.log"
    if log_path.exists():
        log_path.unlink()
    tunnel = subprocess.Popen(
        [
            str(bin_path),
            "tunnel",
            "--url",
            "http://127.0.0.1:8000",
            "--no-autoupdate",
            "--protocol",
            "http2",
            "--logfile",
            str(log_path),
        ],
        cwd=ROOT,
    )
    public = None
    print("Жду ссылку Cloudflare...")
    try:
        for _ in range(90):
            time.sleep(1)
            if log_path.exists():
                text = log_path.read_text(encoding="utf-8", errors="replace")
                match = URL_RE.search(text)
                if match:
                    public = match.group(0)
                    (ROOT / "public_url.txt").write_text(public + "\n", encoding="utf-8")
                    print("Открой в браузере:", public)
                    print("В Яндексе Redirect URI:", f"{public}/auth/callback")
                    break
        if public is None:
            print("Ссылка не появилась. Смотри data/cloudflared.log")
        tunnel.wait()
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()
        server.terminate()


if __name__ == "__main__":
    main()
