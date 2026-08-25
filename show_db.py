"""Показать содержимое SQLite: user_id и JSON свечей."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "candles.db"


def main() -> None:
    if not DB.exists():
        print("Базы ещё нет:", DB)
        return
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT user_id, payload FROM kv").fetchall()
    conn.close()
    if not rows:
        print("Таблица пустая.")
        return
    for user_id, payload in rows:
        print("user_id:", user_id)
        try:
            print(json.dumps(json.loads(payload), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(payload)
        print("-" * 40)


if __name__ == "__main__":
    main()
