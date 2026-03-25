#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path("/home/lhy/workspace/sockets")
DATA_DIR = BASE_DIR / "data"
POOL_FILE = DATA_DIR / "stock_pool.json"
SNAPSHOT_FILE = DATA_DIR / "stocks_snapshot.json"
MARKET_FILE = DATA_DIR / "market_context.json"
MANUAL_PATCH_FILE = DATA_DIR / "manual_incremental_updates.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        result = dict(base)
        for key, value in patch.items():
            result[key] = deep_merge(result.get(key), value)
        return result
    return patch


def to_float(value: str) -> float | None:
    try:
        if value in {"", "N/A", "null", "None", "--"}:
            return None
        return float(value)
    except Exception:
        return None


def qq_symbol(code: str) -> str:
    digits = code.split(".")[0]
    return f"hk{digits}"


def fetch_qq_quote(code: str) -> dict[str, Any] | None:
    url = f"https://qt.gtimg.cn/q=r_{qq_symbol(code)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("gbk", "ignore")
    if "~" not in raw:
        return None
    payload = raw.split('"', 1)[1].rsplit('"', 1)[0]
    fields = payload.split("~")
    if len(fields) < 46:
        return None

    current = to_float(fields[3])
    prev_close = to_float(fields[4])
    open_price = to_float(fields[5])
    change_abs = to_float(fields[31])
    change_pct = to_float(fields[32])
    day_high = to_float(fields[33])
    day_low = to_float(fields[34])
    pe_ttm = to_float(fields[39])
    high_52w = to_float(fields[44])
    low_52w = to_float(fields[45])
    timestamp = fields[30] if len(fields) > 30 else ""

    price_vs_high = None
    if current and high_52w and high_52w > 0:
        price_vs_high = round(current / high_52w * 100, 2)

    return {
        "code": code,
        "name": fields[1] or code,
        "current_price_hkd": current,
        "prev_close_hkd": prev_close,
        "open_hkd": open_price,
        "day_high_hkd": day_high,
        "day_low_hkd": day_low,
        "change_abs_hkd": change_abs,
        "change_pct": change_pct,
        "pe_ttm": pe_ttm,
        "high_52w_hkd": high_52w,
        "low_52w_hkd": low_52w,
        "price_vs_52w_high_pct": price_vs_high,
        "price_as_of": timestamp.replace("/", "-") if timestamp else None,
        "quote_source": "Tencent quote API",
        "quote_url": url,
    }


def remove_missing_field(entry: dict[str, Any], *field_names: str) -> None:
    missing = entry.get("missing_fields", [])
    if not isinstance(missing, list):
        return
    entry["missing_fields"] = [x for x in missing if x not in field_names]


def ensure_entry(existing: dict[str, Any] | None, symbol_meta: dict[str, Any]) -> dict[str, Any]:
    entry = dict(existing or {})
    entry.setdefault("code", symbol_meta["code"])
    entry.setdefault("name", symbol_meta["name"])
    entry.setdefault("status", "unreviewed")
    entry.setdefault("category", symbol_meta.get("category"))
    entry.setdefault("priority", symbol_meta.get("priority", "medium"))
    entry.setdefault("missing_fields", [])
    return entry


def update_snapshot() -> dict[str, Any]:
    pool = load_json(POOL_FILE, {"symbols": []})
    snapshot = load_json(SNAPSHOT_FILE, {"snapshot_date": None, "universe": "", "stocks": []})
    existing_by_code = {item["code"]: item for item in snapshot.get("stocks", []) if "code" in item}

    new_items: list[dict[str, Any]] = []
    updated_count = 0

    for symbol_meta in pool.get("symbols", []):
        code = symbol_meta["code"]
        entry = ensure_entry(existing_by_code.get(code), symbol_meta)
        try:
            quote = fetch_qq_quote(code)
        except Exception as exc:
            entry["last_quote_error"] = str(exc)
            entry["last_quote_attempt_at"] = datetime.now(timezone.utc).isoformat()
            new_items.append(entry)
            continue

        if quote:
            entry.update({k: v for k, v in quote.items() if v is not None})
            entry["last_quote_update_at"] = datetime.now(timezone.utc).isoformat()
            remove_missing_field(
                entry,
                "current_price_hkd",
                "high_52w_hkd",
                "low_52w_hkd",
                "pe_ttm",
            )
            updated_count += 1

        new_items.append(entry)

    snapshot["snapshot_date"] = datetime.now().date().isoformat()
    snapshot["universe"] = "Hong Kong technology stocks with local cache + automated quote refresh"
    snapshot["stocks"] = new_items
    snapshot["auto_quote_refresh_count"] = updated_count
    return snapshot


def touch_market_context() -> None:
    market = load_json(MARKET_FILE, {})
    market["last_auto_update_at"] = datetime.now(timezone.utc).isoformat()
    market.setdefault(
        "notes",
        [],
    )
    if "自动脚本当前主要更新个股行情字段；南向资金和PE分位仍以本地缓存+人工/搜索增量补充为主。" not in market["notes"]:
        market["notes"].append(
            "自动脚本当前主要更新个股行情字段；南向资金和PE分位仍以本地缓存+人工/搜索增量补充为主。"
        )
    save_json(MARKET_FILE, market)


def apply_manual_patches(snapshot: dict[str, Any]) -> dict[str, Any]:
    patch = load_json(MANUAL_PATCH_FILE, {})
    if not patch:
        return snapshot

    market_patch = patch.get("market_context")
    if market_patch:
        market = load_json(MARKET_FILE, {})
        market = deep_merge(market, market_patch)
        market["last_manual_patch_at"] = datetime.now(timezone.utc).isoformat()
        save_json(MARKET_FILE, market)

    stock_patches = patch.get("stocks", {})
    if stock_patches:
        by_code = {item["code"]: item for item in snapshot.get("stocks", []) if "code" in item}
        for code, stock_patch in stock_patches.items():
            if code not in by_code:
                by_code[code] = {"code": code, "status": "unreviewed", "missing_fields": []}
            by_code[code] = deep_merge(by_code[code], stock_patch)
            by_code[code]["last_manual_patch_at"] = datetime.now(timezone.utc).isoformat()
        snapshot["stocks"] = list(by_code.values())

    return snapshot


def main() -> None:
    snapshot = update_snapshot()
    snapshot = apply_manual_patches(snapshot)
    save_json(SNAPSHOT_FILE, snapshot)
    touch_market_context()
    print(
        f"Updated quotes for {snapshot.get('auto_quote_refresh_count', 0)} symbols "
        f"into {SNAPSHOT_FILE}"
    )


if __name__ == "__main__":
    main()
