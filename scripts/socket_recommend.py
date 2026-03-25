#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import shutil
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

NOTO_CJK_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if NOTO_CJK_FONT.exists():
    font_manager.fontManager.addfont(str(NOTO_CJK_FONT))
    matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
matplotlib.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
    "WenQuanYi Zen Hei",
    "Microsoft YaHei",
    "SimHei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


BASE_DIR = Path("/home/lhy/workspace/sockets")
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
SNAPSHOT_FILE = DATA_DIR / "stocks_snapshot.json"
MARKET_FILE = DATA_DIR / "market_context.json"
MANUAL_TRENDS_FILE = DATA_DIR / "manual_trends.json"
TREND_CACHE_FILE = DATA_DIR / "southbound_trends_cache.json"
BUY_FILE = BASE_DIR / "prompts" / "buyv2.md"
LATEST_OUTPUT_FILE = OUTPUT_DIR / "latest_recommendation.md"
LATEST_TREND_PNG_FILE = OUTPUT_DIR / "latest_recommendation_trends.png"
LATEST_TREND_WEEKLY_PNG_FILE = OUTPUT_DIR / "latest_recommendation_trends_weekly.png"
LATEST_TREND_JSON_FILE = OUTPUT_DIR / "latest_recommendation_trends.json"
TREND_CACHE_MAX_POINTS = 420
TREND_CACHE_INCREMENTAL_FETCH_POINTS = 120
TREND_CACHE_INITIAL_FETCH_POINTS = 260
DEFAULT_NUM_RECOMMENDATIONS = 3
EXPORT_DPI = 160
MAIN_PLOT_WIDTH_PX = 2048
LEGEND_PANEL_WIDTH_PX = 0
# Per subplot row target height (px at EXPORT_DPI); larger reduces crowding / legend overlap.
ROW_HEIGHT_PX = 1008


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


def build_output_paths(run_at: datetime) -> dict[str, Path]:
    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    return {
        "markdown": OUTPUT_DIR / f"{stamp}_stock_recommendation.md",
        "trend_png": OUTPUT_DIR / f"{stamp}_stock_recommendation_trends.png",
        "trend_weekly_png": OUTPUT_DIR / f"{stamp}_stock_recommendation_trends_weekly.png",
        "trend_json": OUTPUT_DIR / f"{stamp}_stock_recommendation_trends.json",
    }


def sync_latest_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HK tech stock recommendations and trend charts.")
    parser.add_argument(
        "--num",
        type=int,
        default=DEFAULT_NUM_RECOMMENDATIONS,
        help="Number of strategy-selected stocks to recommend before appending manual picks.",
    )
    return parser.parse_args()


def load_trend_cache() -> dict[str, Any]:
    return load_json(TREND_CACHE_FILE, {"updated_at": None, "codes": {}})


def save_trend_cache(cache: dict[str, Any]) -> None:
    cache["updated_at"] = datetime.now().isoformat()
    save_json(TREND_CACHE_FILE, cache)


def recompute_cumulative_50d(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(series, key=lambda item: item["trade_date"])
    running_window: list[float] = []
    normalized: list[dict[str, Any]] = []
    for item in ordered:
        row = dict(item)
        value = row.get("southbound_flow_proxy_hkd_billion")
        v = 0.0 if value is None else float(value)
        running_window.append(v)
        if len(running_window) > 50:
            running_window.pop(0)
        row["cumulative_50d_flow_proxy_hkd_billion"] = round(sum(running_window), 4)
        normalized.append(row)
    return normalized[-TREND_CACHE_MAX_POINTS:]


def merge_trend_series(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_by_date: dict[str, dict[str, Any]] = {}
    for row in existing:
        if isinstance(row, dict) and row.get("trade_date"):
            merged_by_date[row["trade_date"]] = dict(row)
    for row in incoming:
        if isinstance(row, dict) and row.get("trade_date"):
            merged_by_date[row["trade_date"]] = dict(row)
    return recompute_cumulative_50d(list(merged_by_date.values()))


def build_manual_row(entry: dict[str, Any], stocks: list[dict[str, Any]]) -> dict[str, Any]:
    matched = next((stock for stock in stocks if stock.get("code") == entry.get("code")), {})
    return {
        "name": entry.get("name", matched.get("name", entry.get("code", "unknown"))),
        "code": entry.get("code", "unknown"),
        "current_price_hkd": matched.get("current_price_hkd", "unknown"),
        "valuation_percentile_5y": matched.get("valuation_percentile_5y", "unknown"),
        "southbound_net_buy_50d_hkd_billion": matched.get(
            "southbound_net_buy_50d_hkd_billion",
            matched.get("southbound_net_buy_20d_hkd_billion", "unknown"),
        ),
        "southbound_turnover_ratio_5d": matched.get("southbound_turnover_ratio_5d", "unknown"),
        "buy_weeks_in_10w": matched.get(
            "southbound_buy_weeks_in_10w",
            matched.get("buy_weeks_in_10w", "unknown"),
        ),
        "catalyst_strength": matched.get("catalyst_strength", "unknown"),
        "total_score": matched.get("manual_score", "manual"),
        "priority": "人选",
        "signal": "人选",
        "disqualify_reason": "",
        "position_pass": True,
        "low_area_pass": True,
        "no_chase_pass": True,
        "flow_ok": True,
        "manual_pick": True,
    }


def parse_percentile(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        if "-" in text:
            parts = text.split("-", 1)
            try:
                return float(parts[-1])
            except Exception:
                return None
        try:
            return float(text)
        except Exception:
            return None
    return None


def bool_is_true(value: Any) -> bool:
    return value is True


def get_southbound_strength(stock: dict[str, Any]) -> tuple[bool, float]:
    candidates = [
        stock.get("southbound_net_buy_50d_hkd_billion"),
        stock.get("southbound_net_buy_20d_hkd_billion"),
        stock.get("southbound_net_buy_10d_hkd_billion"),
        stock.get("southbound_net_buy_8d_hkd_billion"),
        stock.get("southbound_net_buy_7d_hkd_billion"),
        stock.get("southbound_net_buy_streak_hkd_billion"),
        stock.get("southbound_recent_daily_hkd_billion"),
    ]
    numeric = [float(x) for x in candidates if isinstance(x, (int, float))]
    streak = stock.get("southbound_recent_buy_streak_days")
    has_positive = any(x > 0 for x in numeric) or (isinstance(streak, int) and streak >= 3)
    strength = max(numeric) if numeric else 0.0
    return has_positive, strength


def position_pass(stock: dict[str, Any]) -> bool:
    ratio = stock.get("price_vs_52w_high_pct")
    if isinstance(ratio, (int, float)) and ratio <= 50:
        return True
    percentile = parse_percentile(stock.get("valuation_percentile_5y"))
    if percentile is not None and percentile <= 30:
        return True
    return False


def low_area_pass(stock: dict[str, Any]) -> bool:
    ratio = stock.get("price_vs_52w_high_pct")
    if isinstance(ratio, (int, float)) and ratio <= 55:
        return True
    percentile = parse_percentile(stock.get("valuation_percentile_5y"))
    if percentile is not None and percentile <= 35:
        return True
    return False


def no_chase_pass(stock: dict[str, Any]) -> bool:
    if bool_is_true(stock.get("three_month_has_single_day_gain_ge_10pct")):
        return False
    if stock.get("three_month_accumulated_gain_gt_15pct") is True:
        return False
    return True


def valuation_score(stock: dict[str, Any]) -> int:
    percentile = parse_percentile(stock.get("valuation_percentile_5y"))
    if percentile is not None:
        if percentile < 10:
            return 100
        if percentile < 20:
            return 80
        if percentile < 30:
            return 60
        if percentile < 40:
            return 40
        return 0
    ratio = stock.get("price_vs_52w_high_pct")
    if isinstance(ratio, (int, float)):
        if ratio <= 40:
            return 80
        if ratio <= 50:
            return 60
        if ratio <= 65:
            return 40
    return 0


def catalyst_score(stock: dict[str, Any]) -> int:
    strength = stock.get("catalyst_strength")
    if strength == "strong":
        return 100
    if strength == "medium":
        return 60
    if strength == "weak":
        return 20
    return 0


def funds_score(stock: dict[str, Any], max_strength: float, max_weeks: float) -> int:
    _, strength = get_southbound_strength(stock)
    weeks_raw = stock.get("southbound_buy_weeks_in_10w") or stock.get("buy_weeks_in_10w")
    weeks = 0.0
    if isinstance(weeks_raw, (int, float)):
        weeks = float(weeks_raw)
    elif isinstance(weeks_raw, str):
        digits = "".join(ch for ch in weeks_raw if ch.isdigit())
        if digits:
            weeks = float(digits)
    strength_norm = 100 * strength / max_strength if max_strength > 0 else 0
    weeks_norm = 100 * weeks / max_weeks if max_weeks > 0 else 0
    return round(strength_norm * 0.5 + weeks_norm * 0.5)


def classify_signal(stock: dict[str, Any]) -> str:
    weeks_raw = stock.get("southbound_buy_weeks_in_10w") or stock.get("buy_weeks_in_10w")
    weeks = 0
    if isinstance(weeks_raw, int):
        weeks = weeks_raw
    elif isinstance(weeks_raw, str):
        digits = "".join(ch for ch in weeks_raw if ch.isdigit())
        if digits:
            weeks = int(digits)

    _, strength = get_southbound_strength(stock)
    ratio = stock.get("price_vs_52w_high_pct")
    if weeks >= 6 and strength >= 1.5:
        return "A"
    if weeks >= 4 or strength >= 2.5:
        return "B"
    if isinstance(ratio, (int, float)) and ratio <= 30 and stock.get("catalyst_strength") in {"strong", "medium"}:
        return "C"
    return "-"


def priority_from(score: int, signal: str, no_chase: bool) -> str:
    if not no_chase:
        return "P3"
    if score >= 85 and signal == "A":
        return "P0"
    if score >= 70 and signal == "B":
        return "P1"
    if score >= 50 and signal in {"B", "C"}:
        return "P2"
    return "P3"


def fetch_southbound_trend_remote(code: str, page_size: int = TREND_CACHE_INITIAL_FETCH_POINTS) -> list[dict[str, Any]]:
    digits = code.split(".")[0]
    params = {
        "reportName": "RPT_MUTUAL_STOCK_HOLDRANKS",
        "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME,TRADE_DATE,HOLD_MARKET_CAP,HOLD_SHARES,CLOSE_PRICE,CHANGE_RATE",
        "filter": f'(MUTUAL_TYPE="002")(SECUCODE="{digits}.HK")',
        "pageNumber": "1",
        "pageSize": str(page_size),
        "source": "WEB",
        "client": "WEB",
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
    }
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    rows = (data.get("result") or {}).get("data") or []
    rows = list(reversed(rows))

    parsed = []
    prev_hold_shares = None
    for row in rows:
        trade_date = datetime.strptime(row["TRADE_DATE"].split()[0], "%Y-%m-%d")
        hold_shares = float(row["HOLD_SHARES"])
        daily_delta = None if prev_hold_shares is None else hold_shares - prev_hold_shares
        close_price = float(row["CLOSE_PRICE"])
        daily_flow_proxy_hkd_billion = None
        if daily_delta is not None:
            daily_flow_proxy_hkd_billion = daily_delta * close_price / 100000000.0
        parsed.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "close_price": close_price,
                "hold_market_cap_hkd": float(row["HOLD_MARKET_CAP"]),
                "hold_shares": hold_shares,
                "southbound_flow_proxy_shares": daily_delta,
                "southbound_flow_proxy_hkd_billion": daily_flow_proxy_hkd_billion,
                "change_rate": float(row["CHANGE_RATE"]),
            }
        )
        prev_hold_shares = hold_shares

    return recompute_cumulative_50d(parsed)


def get_trend_series(
    code: str,
    name: str,
    trend_cache: dict[str, Any],
    runtime_trends: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if code in runtime_trends:
        return runtime_trends[code]

    cache_codes = trend_cache.setdefault("codes", {})
    cache_entry = cache_codes.get(code, {})
    cached_series = cache_entry.get("series", []) if isinstance(cache_entry, dict) else []

    try:
        fetch_size = TREND_CACHE_INITIAL_FETCH_POINTS if not cached_series else TREND_CACHE_INCREMENTAL_FETCH_POINTS
        incoming = fetch_southbound_trend_remote(code, page_size=fetch_size)
        series = merge_trend_series(cached_series, incoming)
        cache_codes[code] = {
            "code": code,
            "name": name,
            "source": "EastMoney RPT_MUTUAL_STOCK_HOLDRANKS",
            "last_trade_date": series[-1]["trade_date"] if series else None,
            "last_refresh_at": datetime.now().isoformat(),
            "series": series,
        }
    except Exception:
        if not cached_series:
            raise
        series = recompute_cumulative_50d(cached_series)
        cache_codes[code] = {
            "code": code,
            "name": name,
            "source": "EastMoney RPT_MUTUAL_STOCK_HOLDRANKS",
            "last_trade_date": series[-1]["trade_date"] if series else None,
            "last_refresh_at": cache_entry.get("last_refresh_at"),
            "series": series,
        }

    runtime_trends[code] = cache_codes[code]["series"]
    return runtime_trends[code]


def summarize_trend(trend: list[dict[str, Any]]) -> dict[str, Any]:
    def sum_last(n: int) -> float:
        rows = trend[-n:] if len(trend) >= n else trend
        return round(sum((r.get("southbound_flow_proxy_hkd_billion") or 0.0) for r in rows), 4)

    def positive_days_last(n: int) -> int:
        rows = trend[-n:] if len(trend) >= n else trend
        return sum(1 for r in rows if (r.get("southbound_flow_proxy_hkd_billion") or 0.0) > 0)

    return {
        "recent_5d_flow_hkd_billion": sum_last(5),
        "recent_10d_flow_hkd_billion": sum_last(10),
        "recent_20d_flow_hkd_billion": sum_last(20),
        "recent_50d_flow_hkd_billion": sum_last(50),
        "recent_5d_positive_days": positive_days_last(5),
    }


def low_area_wash_ok(stock: dict[str, Any], trend_summary: dict[str, Any]) -> bool:
    if not low_area_pass(stock):
        return False
    if not no_chase_pass(stock):
        return False
    recent_20 = trend_summary.get("recent_20d_flow_hkd_billion", 0.0)
    recent_50 = trend_summary.get("recent_50d_flow_hkd_billion", 0.0)
    recent_5 = trend_summary.get("recent_5d_flow_hkd_billion", 0.0)
    if recent_20 <= 0 or recent_50 <= 0:
        return False
    if recent_5 >= 0:
        return False
    return abs(recent_5) <= max(abs(recent_20) * 0.4, 0.8)


def build_trend_payload(
    recommendations: list[dict[str, Any]],
    trend_cache: dict[str, Any],
    runtime_trends: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    trend_payload = []
    for rec in recommendations:
        trend = get_trend_series(rec["code"], rec["name"], trend_cache, runtime_trends)
        trend_payload.append(
            {
                "code": rec["code"],
                "name": rec["name"],
                "southbound_flow_unit": "亿港元",
                "series": trend,
            }
        )
    return trend_payload


def build_chart_rows(
    recommendations: list[dict[str, Any]],
    trend_payload: list[dict[str, Any]],
    window_days: int | None,
) -> list[dict[str, Any]]:
    payload_by_code = {item["code"]: item for item in trend_payload}
    chart_rows: list[dict[str, Any]] = []
    for rec in recommendations:
        payload = payload_by_code.get(rec["code"], {"series": []})
        trend = payload.get("series", [])
        if window_days is not None:
            trend = trend[-window_days:]
        dates = [datetime.strptime(item["trade_date"], "%Y-%m-%d") for item in trend]
        prices = [item["close_price"] for item in trend]
        daily_flows = [(item.get("southbound_flow_proxy_hkd_billion") or 0.0) * 10 for item in trend]
        cumulative_5d = []
        cumulative_20d = []
        running_5d: list[float] = []
        running_20d: list[float] = []
        for value in daily_flows:
            running_5d.append(value)
            if len(running_5d) > 5:
                running_5d.pop(0)
            cumulative_5d.append(round(sum(running_5d), 4))

            running_20d.append(value)
            if len(running_20d) > 20:
                running_20d.pop(0)
            cumulative_20d.append(round(sum(running_20d), 4))
        cumulative_50d = [(item.get("cumulative_50d_flow_proxy_hkd_billion") or 0.0) * 10 for item in trend]
        chart_rows.append(
            {
                "rec": rec,
                "dates": dates,
                "prices": prices,
                "daily_flows": daily_flows,
                "cumulative_5d": cumulative_5d,
                "cumulative_20d": cumulative_20d,
                "cumulative_50d": cumulative_50d,
            }
        )
    return chart_rows


def build_summary_price_change_series(
    dates: list[datetime],
    prices: list[float],
    mode: str,
) -> tuple[list[datetime], list[float]]:
    if not dates or not prices:
        return [], []

    if mode == "weekly_pct":
        weekly_points: list[tuple[datetime, float]] = []
        last_key = None
        for dt, price in zip(dates, prices):
            iso = dt.isocalendar()
            key = (iso.year, iso.week)
            if key != last_key:
                weekly_points.append((dt, price))
                last_key = key
            else:
                weekly_points[-1] = (dt, price)
        pct_dates: list[datetime] = []
        pct_values: list[float] = []
        prev_price = None
        for dt, price in weekly_points:
            if prev_price is None or prev_price == 0:
                pct = 0.0
            else:
                pct = round((price / prev_price - 1.0) * 100.0, 2)
            pct_dates.append(dt)
            pct_values.append(pct)
            prev_price = price
        return pct_dates, pct_values

    pct_values = [0.0]
    for prev_price, price in zip(prices[:-1], prices[1:]):
        if prev_price == 0:
            pct_values.append(0.0)
        else:
            pct_values.append(round((price / prev_price - 1.0) * 100.0, 2))
    return dates, pct_values


def render_trend_chart(
    recommendations: list[dict[str, Any]],
    chart_rows: list[dict[str, Any]],
    trend_png_file: Path,
    latest_png_file: Path,
    chart_title: str,
    summary_price_title: str,
    summary_daily_title: str,
    summary_5d_title: str,
    summary_20d_title: str,
    summary_cum_title: str,
    stock_title_suffix: str,
    x_locator: Any,
    x_formatter: Any,
    x_minor_locator: Any | None,
    figure_size: tuple[float, float],
    bar_width: float,
    summary_price_mode: str,
    summary_price_ylabel: str,
    summary_flow_visual_scale: float,
) -> None:
    n = len(recommendations)
    if not chart_rows:
        if latest_png_file.exists():
            latest_png_file.unlink()
        if trend_png_file.exists():
            trend_png_file.unlink()
        return

    total_width_in = figure_size[0]
    total_height_in = figure_size[1]
    fig = plt.figure(figsize=(total_width_in, total_height_in))
    fig.patch.set_facecolor("#f5f7fb")
    grid = fig.add_gridspec(
        nrows=n + 5,
        ncols=1,
        height_ratios=[1.4, 2.35, 2.35, 2.35, 2.35] + [2.85] * n,
        hspace=0.68,
    )
    summary_price_ax = fig.add_subplot(grid[0, 0])
    summary_daily_ax = fig.add_subplot(grid[1, 0])
    summary_5d_ax = fig.add_subplot(grid[2, 0])
    summary_20d_ax = fig.add_subplot(grid[3, 0])
    summary_cum_ax = fig.add_subplot(grid[4, 0])
    cmap = plt.get_cmap("tab10")
    line_styles = ["-", "--", "-.", ":"]
    chart_end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for idx, row in enumerate(chart_rows):
        rec = row["rec"]
        color = cmap(idx % 10)
        line_style = line_styles[idx % len(line_styles)]
        label = f"{rec['name']} ({rec['code']})"
        price_change_dates, price_change_values = build_summary_price_change_series(
            row["dates"],
            row["prices"],
            summary_price_mode,
        )
        summary_price_ax.plot(
            price_change_dates,
            price_change_values,
            color=color,
            linewidth=1.9,
            linestyle=line_style,
            label=label,
        )
        summary_daily_ax.plot(
            row["dates"],
            [value * summary_flow_visual_scale for value in row["daily_flows"]],
            color=color,
            linewidth=1.7,
            linestyle=line_style,
            label=label,
        )
        summary_5d_ax.plot(
            row["dates"],
            [value * summary_flow_visual_scale for value in row["cumulative_5d"]],
            color=color,
            linewidth=1.8,
            linestyle=line_style,
            label=label,
        )
        summary_20d_ax.plot(
            row["dates"],
            [value * summary_flow_visual_scale for value in row["cumulative_20d"]],
            color=color,
            linewidth=1.85,
            linestyle=line_style,
            label=label,
        )
        summary_cum_ax.plot(
            row["dates"],
            [value * summary_flow_visual_scale for value in row["cumulative_50d"]],
            color=color,
            linewidth=1.9,
            linestyle=line_style,
            label=label,
        )
    summary_axes = [
        (summary_price_ax, summary_price_title, summary_price_ylabel),
        (summary_daily_ax, summary_daily_title, "南资净额 (汇总放大3x)"),
        (summary_5d_ax, summary_5d_title, "南资净额 (汇总放大3x)"),
        (summary_20d_ax, summary_20d_title, "南资净额 (汇总放大3x)"),
        (summary_cum_ax, summary_cum_title, "南资净额 (汇总放大3x)"),
    ]
    for ax, title, ylabel in summary_axes:
        ax.set_facecolor("#fcfdff")
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", linestyle="--", alpha=0.25, linewidth=0.8)
        ax.grid(True, axis="x", which="major", linestyle=":", alpha=0.15, linewidth=0.7)
        ax.xaxis.set_major_locator(x_locator)
        ax.xaxis.set_major_formatter(x_formatter)
        if x_minor_locator is not None:
            ax.xaxis.set_minor_locator(x_minor_locator)
            ax.grid(True, axis="x", which="minor", linestyle=":", alpha=0.08, linewidth=0.5)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0.0, 1.02),
            ncol=min(2, max(1, n)),
            fontsize=8,
            frameon=False,
            borderaxespad=0.0,
            columnspacing=0.8,
            handletextpad=0.5,
            labelspacing=0.4,
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    price_ymin, price_ymax = summary_price_ax.get_ylim()
    summary_price_ax.axhspan(max(0, price_ymin), max(0, price_ymax), color="#fef2f2", alpha=0.65, zorder=0)
    summary_price_ax.axhspan(min(0, price_ymin), min(0, price_ymax), color="#f0fdf4", alpha=0.75, zorder=0)
    summary_price_ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    summary_price_ax.axhline(0, color="#374151", linewidth=1.2, alpha=0.85)

    for flow_ax in (summary_daily_ax, summary_5d_ax, summary_20d_ax, summary_cum_ax):
        ymin, ymax = flow_ax.get_ylim()
        flow_ax.axhspan(max(0, ymin), max(0, ymax), color="#fff7ed", alpha=0.35, zorder=0)
        flow_ax.axhspan(min(0, ymin), min(0, ymax), color="#ecfdf5", alpha=0.35, zorder=0)
        flow_ax.axhline(0, color="#374151", linewidth=1.15, alpha=0.8)

    for idx, row in enumerate(chart_rows):
        rec = row["rec"]
        ax = fig.add_subplot(grid[idx + 5, 0])
        ax.set_facecolor("#ffffff")
        ax2 = ax.twinx()
        bar_colors = ["#d95f5f" if value >= 0 else "#4daf7c" for value in row["daily_flows"]]
        ax.plot(
            row["dates"],
            row["prices"],
            color="#2563eb",
            linewidth=2.2,
            marker="o",
            markersize=2.6,
            markerfacecolor="#ffffff",
            markeredgewidth=0.7,
            label="股价",
        )
        ax2.bar(
            row["dates"],
            row["daily_flows"],
            color=bar_colors,
            alpha=0.35,
            width=bar_width,
            label="南资日净额",
        )
        ax2.plot(
            row["dates"],
            row["cumulative_5d"],
            color="#ea580c",
            linewidth=1.75,
            linestyle="--",
            label="5日南资净额",
        )
        ax2.plot(
            row["dates"],
            row["cumulative_20d"],
            color="#9333ea",
            linewidth=1.75,
            linestyle="-.",
            label="20日南资净额",
        )
        ax2.plot(
            row["dates"],
            row["cumulative_50d"],
            color="#16a34a",
            linewidth=2.0,
            marker="o",
            markersize=2.0,
            markerfacecolor="#ffffff",
            markeredgewidth=0.6,
            label="50日南资净额",
        )
        ax2.fill_between(row["dates"], row["cumulative_50d"], 0, color="#16a34a", alpha=0.06)

        ax.set_title(f"{rec['name']} ({rec['code']})\n{stock_title_suffix}")
        ax.set_ylabel("股价 (港元)", color="#2563eb")
        ax2.set_ylabel("南资净额 5/20/50日 (亿港元)", color="#4b5563")
        ax.tick_params(axis="y", labelcolor="#2563eb")
        ax2.tick_params(axis="y", labelcolor="#4b5563")
        ax.grid(True, axis="y", linestyle="--", alpha=0.28, linewidth=0.8)
        ax.grid(True, axis="x", which="major", linestyle=":", alpha=0.14, linewidth=0.7)
        ax.xaxis.set_major_locator(x_locator)
        ax.xaxis.set_major_formatter(x_formatter)
        if x_minor_locator is not None:
            ax.xaxis.set_minor_locator(x_minor_locator)
            ax.grid(True, axis="x", which="minor", linestyle=":", alpha=0.08, linewidth=0.5)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax2.spines["top"].set_visible(False)
        ax2.axhline(0, color="#666666", linewidth=0.8, alpha=0.7)
        if row["dates"]:
            ax.set_xlim(row["dates"][0], chart_end_date)
            ax2.set_xlim(row["dates"][0], chart_end_date)
        handles_1, labels_1 = ax.get_legend_handles_labels()
        handles_2, labels_2 = ax2.get_legend_handles_labels()
        ax.legend(handles_1 + handles_2, labels_1 + labels_2, loc="upper left", fontsize=8, frameon=False)

    all_dates = [dt for row in chart_rows for dt in row["dates"]]
    if all_dates:
        chart_start_date = min(all_dates)
        for ax in (summary_price_ax, summary_daily_ax, summary_5d_ax, summary_20d_ax, summary_cum_ax):
            ax.set_xlim(chart_start_date, chart_end_date)

    fig.suptitle(chart_title, fontsize=15, y=0.995)
    fig.subplots_adjust(top=0.96, bottom=0.04, left=0.06, right=0.96)
    fig.savefig(trend_png_file, dpi=160, bbox_inches="tight")
    plt.close(fig)
    sync_latest_copy(trend_png_file, latest_png_file)


def write_trend_chart(
    recommendations: list[dict[str, Any]],
    trend_png_file: Path,
    trend_weekly_png_file: Path,
    trend_json_file: Path,
    trend_cache: dict[str, Any],
    runtime_trends: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not recommendations:
        if LATEST_TREND_PNG_FILE.exists():
            LATEST_TREND_PNG_FILE.unlink()
        if LATEST_TREND_WEEKLY_PNG_FILE.exists():
            LATEST_TREND_WEEKLY_PNG_FILE.unlink()
        if trend_png_file.exists():
            trend_png_file.unlink()
        if trend_weekly_png_file.exists():
            trend_weekly_png_file.unlink()
        save_json(trend_json_file, {"generated_at": datetime.now().isoformat(), "trends": []})
        sync_latest_copy(trend_json_file, LATEST_TREND_JSON_FILE)
        return []

    trend_payload = build_trend_payload(recommendations, trend_cache, runtime_trends)
    daily_chart_rows = build_chart_rows(recommendations, trend_payload, window_days=90)
    weekly_chart_rows = build_chart_rows(recommendations, trend_payload, window_days=260)

    render_trend_chart(
        recommendations,
        daily_chart_rows,
        trend_png_file,
        LATEST_TREND_PNG_FILE,
        "推荐港股科技股：90日股价与南向资金趋势",
        "汇总视图：当日涨跌幅",
        "汇总视图：南资日净额",
        "汇总视图：5日南资累计净额",
        "汇总视图：20日南资累计净额",
        "汇总视图：50日南资净额",
        "90日股价与南向资金趋势",
        mdates.DayLocator(interval=5),
        mdates.DateFormatter("%m-%d"),
        mdates.DayLocator(interval=1),
        (
            MAIN_PLOT_WIDTH_PX / EXPORT_DPI,
            (len(recommendations) + 5) * ROW_HEIGHT_PX / EXPORT_DPI,
        ),
        0.72,
        "daily_pct",
        "当日涨跌幅 (%)",
        3.0,
    )
    render_trend_chart(
        recommendations,
        weekly_chart_rows,
        trend_weekly_png_file,
        LATEST_TREND_WEEKLY_PNG_FILE,
        "推荐港股科技股：近1年股价与南向资金趋势（周轴）",
        "周视图汇总：周涨跌幅",
        "周视图汇总：南资日净额",
        "周视图汇总：5日南资累计净额",
        "周视图汇总：20日南资累计净额",
        "周视图汇总：50日南资净额",
        "近1年股价与南向资金趋势（周轴）",
        mdates.WeekdayLocator(byweekday=mdates.MO, interval=3),
        mdates.DateFormatter("%m-%d"),
        mdates.WeekdayLocator(byweekday=mdates.MO, interval=1),
        (
            MAIN_PLOT_WIDTH_PX / EXPORT_DPI,
            (len(recommendations) + 5) * ROW_HEIGHT_PX / EXPORT_DPI,
        ),
        2.8,
        "weekly_pct",
        "周涨跌幅 (%)",
        3.0,
    )

    save_json(
        trend_json_file,
        {
            "generated_at": datetime.now().isoformat(),
            "trend_png": str(trend_png_file),
            "trend_weekly_png": str(trend_weekly_png_file),
            "trends": trend_payload,
        },
    )
    sync_latest_copy(trend_json_file, LATEST_TREND_JSON_FILE)
    return trend_payload


def build_output(
    trend_cache: dict[str, Any],
    runtime_trends: dict[str, list[dict[str, Any]]],
    num_recommendations: int,
) -> tuple[str, list[dict[str, Any]]]:
    market = load_json(MARKET_FILE, {})
    snapshot = load_json(SNAPSHOT_FILE, {"stocks": []})
    manual_trends = load_json(MANUAL_TRENDS_FILE, [])
    stocks = snapshot.get("stocks", [])

    strengths = []
    weeks_list = []
    for stock in stocks:
        _, strength = get_southbound_strength(stock)
        strengths.append(strength)
        weeks_raw = stock.get("southbound_buy_weeks_in_10w") or stock.get("buy_weeks_in_10w")
        if isinstance(weeks_raw, (int, float)):
            weeks_list.append(float(weeks_raw))
        elif isinstance(weeks_raw, str):
            digits = "".join(ch for ch in weeks_raw if ch.isdigit())
            if digits:
                weeks_list.append(float(digits))
    max_strength = max(strengths) if strengths else 0
    max_weeks = max(weeks_list) if weeks_list else 0

    scored_rows = []
    for stock in stocks:
        no_chase = no_chase_pass(stock)
        pos_ok = position_pass(stock)
        low_pos_ok = low_area_pass(stock)
        flow_ok, _ = get_southbound_strength(stock)
        val_score = valuation_score(stock)
        fund_score = funds_score(stock, max_strength, max_weeks)
        cat_score = catalyst_score(stock)
        total_score = round(val_score * 0.4 + fund_score * 0.4 + cat_score * 0.2)
        signal = classify_signal(stock)
        priority = priority_from(total_score, signal, no_chase)

        row = {
            "name": stock.get("name", stock.get("code")),
            "code": stock.get("code"),
            "current_price_hkd": stock.get("current_price_hkd", "unknown"),
            "valuation_percentile_5y": stock.get("valuation_percentile_5y", "unknown"),
            "southbound_net_buy_50d_hkd_billion": stock.get(
                "southbound_net_buy_50d_hkd_billion",
                stock.get(
                    "southbound_net_buy_20d_hkd_billion",
                    stock.get(
                        "southbound_net_buy_10d_hkd_billion",
                        stock.get(
                            "southbound_net_buy_8d_hkd_billion",
                            stock.get("southbound_net_buy_7d_hkd_billion", "unknown"),
                        ),
                    ),
                ),
            ),
            "southbound_turnover_ratio_5d": stock.get("southbound_turnover_ratio_5d", "unknown"),
            "buy_weeks_in_10w": stock.get(
                "southbound_buy_weeks_in_10w",
                stock.get("buy_weeks_in_10w", "unknown"),
            ),
            "catalyst_strength": stock.get("catalyst_strength", "unknown"),
            "total_score": total_score,
            "priority": priority,
            "signal": signal,
            "disqualify_reason": stock.get("disqualify_reason", ""),
            "position_pass": pos_ok,
            "low_area_pass": low_pos_ok,
            "no_chase_pass": no_chase,
            "flow_ok": flow_ok,
        }
        scored_rows.append(row)

    scored_rows.sort(key=lambda x: x["total_score"], reverse=True)

    trend_summaries: dict[str, dict[str, Any]] = {}
    shortlist_for_trend = [
        row for row in scored_rows
        if row["no_chase_pass"] and (row["flow_ok"] or row["low_area_pass"])
    ][:12]
    for row in shortlist_for_trend:
        try:
            trend = get_trend_series(row["code"], row["name"], trend_cache, runtime_trends)
            summary = summarize_trend(trend)
        except Exception as exc:
            summary = {
                "recent_5d_flow_hkd_billion": 0.0,
                "recent_10d_flow_hkd_billion": 0.0,
                "recent_20d_flow_hkd_billion": 0.0,
                "recent_50d_flow_hkd_billion": 0.0,
                "recent_5d_positive_days": 0,
                "trend_error": str(exc),
            }
        trend_summaries[row["code"]] = summary

    primary: list[dict[str, Any]] = []
    wash_candidates: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []

    for row in scored_rows:
        summary = trend_summaries.get(row["code"], {})
        if summary:
            row["southbound_net_buy_50d_hkd_billion"] = row["southbound_net_buy_50d_hkd_billion"]
            row["trend_recent_5d_flow_hkd_billion"] = summary.get("recent_5d_flow_hkd_billion")
            row["trend_recent_20d_flow_hkd_billion"] = summary.get("recent_20d_flow_hkd_billion")
            row["trend_recent_50d_flow_hkd_billion"] = summary.get("recent_50d_flow_hkd_billion")
        flow_from_trend = summary.get("recent_20d_flow_hkd_billion", 0.0) > 0 or summary.get("recent_50d_flow_hkd_billion", 0.0) > 0
        wash_ok = low_area_wash_ok(
            {
                "price_vs_52w_high_pct": row.get("current_price_hkd") and next(
                    (s.get("price_vs_52w_high_pct") for s in stocks if s.get("code") == row["code"]),
                    None,
                ),
                "valuation_percentile_5y": row["valuation_percentile_5y"],
                "three_month_has_single_day_gain_ge_10pct": False if row["no_chase_pass"] else True,
                "three_month_accumulated_gain_gt_15pct": False,
            },
            summary,
        )
        row["wash_ok"] = wash_ok
        if row["no_chase_pass"] and row["low_area_pass"] and (row["flow_ok"] or flow_from_trend) and row["total_score"] >= 35:
            if row["priority"] == "P3":
                row["priority"] = "P2"
            primary.append(row)
        elif wash_ok:
            row["priority"] = "P2"
            row["signal"] = "B"
            wash_candidates.append(row)
        elif row["flow_ok"]:
            watchlist.append(row)

    primary.sort(key=lambda x: x["total_score"], reverse=True)
    wash_candidates.sort(key=lambda x: x["total_score"], reverse=True)
    watchlist.sort(key=lambda x: x["total_score"], reverse=True)

    manual_code_set = {
        entry.get("code")
        for entry in manual_trends
        if isinstance(entry, dict) and entry.get("code")
    }
    auto_target = max(num_recommendations - len(manual_code_set), 0)

    selected: list[dict[str, Any]] = []
    selected_codes = set()
    for bucket in (primary, wash_candidates):
        for row in bucket:
            if row["code"] in selected_codes:
                continue
            selected.append(row)
            selected_codes.add(row["code"])
            if len(selected) >= auto_target:
                break
        if len(selected) >= auto_target:
            break

    if len(selected) < auto_target:
        extras = [
            row for row in scored_rows
            if row["code"] not in selected_codes and row["no_chase_pass"] and row["low_area_pass"]
        ]
        for row in extras:
            selected.append(row)
            selected_codes.add(row["code"])
            if len(selected) >= auto_target:
                break

    recommendations = selected[:auto_target] if auto_target > 0 else []
    selected_codes = {row["code"] for row in recommendations}
    for entry in manual_trends:
        if not isinstance(entry, dict) or not entry.get("code"):
            continue
        if entry["code"] in selected_codes:
            for row in recommendations:
                if row["code"] == entry["code"]:
                    row["manual_pick"] = True
                    row["priority"] = "人选"
                    row["signal"] = "人选"
            continue
        manual_row = build_manual_row(entry, stocks)
        summary = trend_summaries.get(manual_row["code"])
        if summary is None:
            try:
                trend = get_trend_series(manual_row["code"], manual_row["name"], trend_cache, runtime_trends)
                summary = summarize_trend(trend)
            except Exception as exc:
                summary = {
                    "recent_5d_flow_hkd_billion": 0.0,
                    "recent_10d_flow_hkd_billion": 0.0,
                    "recent_20d_flow_hkd_billion": 0.0,
                    "recent_50d_flow_hkd_billion": 0.0,
                    "recent_5d_positive_days": 0,
                    "trend_error": str(exc),
                }
            trend_summaries[manual_row["code"]] = summary
        manual_row["trend_recent_5d_flow_hkd_billion"] = summary.get("recent_5d_flow_hkd_billion")
        manual_row["trend_recent_20d_flow_hkd_billion"] = summary.get("recent_20d_flow_hkd_billion")
        manual_row["trend_recent_50d_flow_hkd_billion"] = summary.get("recent_50d_flow_hkd_billion")
        recommendations.append(manual_row)
        selected_codes.add(manual_row["code"])

    if len(recommendations) < num_recommendations:
        extras_after_manual = [
            row for row in scored_rows
            if row["code"] not in selected_codes and row["no_chase_pass"] and row["low_area_pass"]
        ]
        for row in extras_after_manual:
            recommendations.append(row)
            selected_codes.add(row["code"])
            if len(recommendations) >= num_recommendations:
                break

    lines = []
    lines.append(f"# Socket Stock Suggestion ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    lines.append("")
    lines.append("## 本次使用的本地数据")
    lines.append(f"- 市场快照日期：`{market.get('snapshot_date', 'unknown')}`")
    lines.append(f"- 个股快照日期：`{snapshot.get('snapshot_date', 'unknown')}`")
    lines.append("- 自动更新字段：`current_price_hkd`、`high_52w_hkd`、`low_52w_hkd`、`pe_ttm`、`price_vs_52w_high_pct`")
    lines.append("- 人工/搜索缓存字段：南向资金、估值分位、催化、是否追高")
    lines.append("")
    lines.append("## 推荐股票列表")
    lines.append("")
    lines.append("| 排序 | 股票名称 (代码) | 当前股价 (港元) | 个股PE分位数 (近5年) | 南向近50日净买入 (亿港元) | 南向成交占比 | 近10周上榜次数 | 催化强度 | 综合得分 | 优先级 | 信号类型 |")
    lines.append("|-----|----------------|----------------|---------------------|--------------------------|-------------|--------------|---------|---------|--------|---------|")
    if recommendations:
        for idx, row in enumerate(recommendations, start=1):
            name_display = row["name"]
            if row.get("manual_pick"):
                name_display = f"{name_display} [人选]"
            lines.append(
                f"| {idx} | {name_display} ({row['code']}) | {row['current_price_hkd']} | "
                f"{row['valuation_percentile_5y']} | {row['southbound_net_buy_50d_hkd_billion']} | "
                f"{row['southbound_turnover_ratio_5d']} | {row['buy_weeks_in_10w']} | "
                f"{row['catalyst_strength']} | {row['total_score']} | {row['priority']} | {row['signal']} |"
            )
    else:
        lines.append("| - | 当前无严格满足条件的正式推荐 | - | - | - | - | - | - | - | - | - |")

    if watchlist:
        lines.append("")
        lines.append("## 观察池")
        lines.append("")
        for row in watchlist[:5]:
            reason = row["disqualify_reason"] or "数据未完全满足正式推荐条件"
            lines.append(f"- `{row['name']} ({row['code']})`：{reason}")

    lines.append("")
    lines.append("## 详细说明")
    lines.append("")
    for row in recommendations:
        detail = []
        if row.get("manual_pick"):
            detail.append("人工加入趋势观察与展示。")
        if row.get("wash_ok"):
            detail.append("低位区短线净卖出更可能是洗盘，近20-50日累计南向流向仍偏正。")
        if row.get("trend_recent_50d_flow_hkd_billion") is not None:
            detail.append(f"近50日南向流向代理值约 {row['trend_recent_50d_flow_hkd_billion']:.2f} 亿港元。")
        if row.get("trend_recent_5d_flow_hkd_billion") is not None:
            detail.append(f"近5日南向流向代理值约 {row['trend_recent_5d_flow_hkd_billion']:.2f} 亿港元。")
        if not detail:
            detail.append("以本地缓存中的南向资金与估值字段为主。")
        lines.append(f"- `{row['name']} ({row['code']})`：{' '.join(detail)}")

    lines.append("")
    lines.append("## 结论")
    if recommendations:
        lines.append(f"- 当前推荐数量：`{len(recommendations)}`")
        if any(row.get("manual_pick") for row in recommendations):
            lines.append("- 已将 `manual_trends.json` 中的人工入选股票一并加入推荐表与趋势图展示，并标注“人选”。")
        lines.append("- 已纳入“低位短线净卖出可能是洗盘”的判断，不再把低位小幅净卖出直接视作撤离。")
        lines.append("- 推荐结果基于本地缓存 + 本次自动增量更新后的最新行情字段。")
    else:
        lines.append("- 当前严格按策略筛选，正式推荐为空。")
        lines.append("- 主要原因通常是：价格不够低、近3个月存在追高特征、或南向资金字段仍不足。")

    return "\n".join(lines) + "\n", recommendations


def main() -> None:
    args = parse_args()
    num_recommendations = max(1, args.num)
    run_at = datetime.now()
    output_paths = build_output_paths(run_at)
    trend_cache = load_trend_cache()
    runtime_trends: dict[str, list[dict[str, Any]]] = {}
    output, recommendations = build_output(trend_cache, runtime_trends, num_recommendations)
    trend_payload = write_trend_chart(
        recommendations,
        output_paths["trend_png"],
        output_paths["trend_weekly_png"],
        output_paths["trend_json"],
        trend_cache,
        runtime_trends,
    )
    save_trend_cache(trend_cache)
    if recommendations:
        output += "\n"
        output += "## 趋势图输出\n\n"
        output += f"- 推荐结果 Markdown：`{output_paths['markdown']}`\n"
        output += f"- 90日趋势图 PNG：`{output_paths['trend_png']}`\n"
        output += f"- 1年周视图 PNG：`{output_paths['trend_weekly_png']}`\n"
        output += f"- 趋势图数据 JSON：`{output_paths['trend_json']}`\n"
        output += f"- 趋势图股票数量：`{len(trend_payload)}`\n"
        output += f"- 最新兼容 Markdown：`{LATEST_OUTPUT_FILE}`\n"
        output += f"- 最新兼容 90日 PNG：`{LATEST_TREND_PNG_FILE}`\n"
        output += f"- 最新兼容 1年周视图 PNG：`{LATEST_TREND_WEEKLY_PNG_FILE}`\n"
        output += f"- 最新兼容 JSON：`{LATEST_TREND_JSON_FILE}`\n"
        output += f"- 自动推荐数量参数：`num={num_recommendations}`（默认 `3`，人工入选股票仍会追加展示）。\n"
        output += "- 趋势图前五行为汇总视图：日视图中股价改为当日涨跌幅，周视图中股价改为周涨跌幅；并新增5日、20日、50日南资累计净额汇总视图，南资相关汇总区做了约3倍视觉放大，且每个视图均带股票图例。\n"
        output += "- 各股子图右轴在同一坐标系中叠加 5日（橙虚线）、20日（紫点划线）、50日（绿实线+浅绿填充）南资滚动累计净额曲线。\n"
        output += "- 趋势图时间范围已调整为近90日，横轴按日展示，并加宽图像以便观察每日变化。\n"
        output += "- 另生成一张近1年周视图，横轴按周展示，图像和纵向高度进一步加大，便于观察中期趋势。\n"
        output += "- 趋势图右侧纵轴单位统一为“亿港元”。\n"
        output += "- 图中“50天累计南向净流入额”为基于南向持股日变化 × 当日收盘价估算的资金流向代理值。\n"
    else:
        output += "\n## 趋势图输出\n\n- 当前无正式推荐股票，因此未生成趋势图。\n"
        output += f"- 推荐结果 Markdown：`{output_paths['markdown']}`\n"
        output += f"- 最新兼容 Markdown：`{LATEST_OUTPUT_FILE}`\n"
    output_paths["markdown"].write_text(output, encoding="utf-8")
    sync_latest_copy(output_paths["markdown"], LATEST_OUTPUT_FILE)
    print(output)


if __name__ == "__main__":
    main()
