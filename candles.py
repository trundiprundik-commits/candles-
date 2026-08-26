"""Правила свечей и state (без HTTP и SQL)."""

from __future__ import annotations

from datetime import datetime, timezone

from config import CANDLE_SIZES, TAB_IDS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def empty_state() -> dict:
    return {"active": "health", "tabs": {tab: [] for tab in TAB_IDS}}


def normalize_candle_size(value: object) -> str:
    size = str(value or "").strip().lower()
    return size if size in CANDLE_SIZES else "small"


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


def prune_state(state: dict, settings: dict) -> tuple[dict, bool]:
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
        if len(kept) != len(items):
            changed = True
    return result, changed
