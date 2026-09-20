"""能源期货行情抓取：Yahoo Finance chart API 为主，Stooq CSV 为备。

无需 API Key。任何源失败均抛出/返回 None，由上层降级，不影响报告生成。
"""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Optional

import requests

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json,text/csv,*/*"}
TIMEOUT = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_yahoo(code: str) -> Optional[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}"
    params = {"interval": "1d", "range": "5d"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    result = (j.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_pct = None
    if prev:
        change_pct = round((price - prev) / prev * 100, 2)
    ts = meta.get("regularMarketTime")
    return {
        "value": round(float(price), 2),
        "change_pct": change_pct,
        "source": "Yahoo Finance",
        "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else _now_iso(),
    }


def fetch_stooq(code: str) -> Optional[dict]:
    url = "https://stooq.com/q/l/"
    params = {"s": code, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text.strip()
    if not text or text.startswith("<") or text.lower().startswith("<!doctype"):
        return None
    row = next(csv.reader(io.StringIO(text)))
    # Symbol,Date,Time,Open,High,Low,Close,Volume
    if len(row) < 7 or row[6] in ("N/D", "0"):
        return None
    close = float(row[6])
    return {
        "value": round(close, 2),
        "change_pct": None,
        "source": "Stooq",
        "ts": f"{row[1]} {row[2]}",
    }


def fetch_all(cfg: dict) -> tuple[list[dict], list[str]]:
    """按配置抓取，yahoo -> stooq 顺序兜底。"""
    out: list[dict] = []
    errors: list[str] = []

    ycodes = {x["code"]: x for x in cfg["prices"]["yahoo"]}
    seen_names = set()
    for code, meta in ycodes.items():
        got = None
        for fn, c in ((fetch_yahoo, code), (fetch_stooq, next((s["code"] for s in cfg["prices"].get("stooq", []) if s["name"] == meta["name"]), None))):
            if not c:
                continue
            try:
                got = fn(c)
                if got:
                    break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{fn.__name__}:{c} {type(e).__name__}")
            time.sleep(0.4)
        item = {**meta, **(got or {})} if got else {**meta, "value": None, "change_pct": None, "source": None, "ts": None}
        out.append(item)
        seen_names.add(meta["name"])

    # stooq 补充 yahoo 列表没有的品种（若未来配置）
    for meta in cfg["prices"].get("stooq", []):
        if meta["name"] in seen_names:
            continue
        try:
            got = fetch_stooq(meta["code"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"stooq:{meta['code']} {type(e).__name__}")
            got = None
        out.append({**meta, **(got or {"value": None, "change_pct": None, "source": None, "ts": None})})

    return out, errors
