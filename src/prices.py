"""能源期货行情抓取：CNBC 报价接口为主（云服务器 IP 友好、含涨跌幅），Yahoo Finance 为备。

无需 API Key。任何源失败均返回 None，由上层降级，不影响报告生成。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import requests

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json,*/*"}
TIMEOUT = 15

CNBC_URL = (
    "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    "?requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_cnbc(code: str) -> Optional[dict]:
    r = requests.get(CNBC_URL, params={"symbols": code}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    q = r.json().get("FormattedQuoteResult", {}).get("FormattedQuote")
    if isinstance(q, list):
        q = q[0] if q else None
    if not q or q.get("code") not in (None, 0) or not q.get("last"):
        return None
    price = float(q["last"])
    chg_raw = q.get("change_pct", "")
    change_pct: Optional[float]
    if chg_raw and chg_raw.upper() != "UNCH":
        change_pct = round(float(str(chg_raw).replace("%", "")), 2)
    elif chg_raw.upper() == "UNCH":
        change_pct = 0.0
    else:
        change_pct = None
    return {
        "value": round(price, 3),
        "change_pct": change_pct,
        "source": "CNBC",
        "ts": q.get("last_time") or _now_iso(),
    }


def fetch_yahoo(code: str) -> Optional[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}"
    params = {"interval": "1d", "range": "5d"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    result = (r.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_pct = round((price - prev) / prev * 100, 2) if prev else None
    ts = meta.get("regularMarketTime")
    return {
        "value": round(float(price), 3),
        "change_pct": change_pct,
        "source": "Yahoo Finance",
        "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else _now_iso(),
    }


def fetch_all(cfg: dict) -> tuple[list[dict], list[str]]:
    """主源 CNBC，失败按名称映射用 Yahoo 兜底。"""
    out: list[dict] = []
    errors: list[str] = []
    ymap = {x["name"]: x["code"] for x in cfg["prices"].get("yahoo", [])}

    for meta in cfg["prices"]["cnbc"]:
        got = None
        try:
            got = fetch_cnbc(meta["code"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"cnbc:{meta['code']} {type(e).__name__}")
        if got is None and meta["name"] in ymap:
            try:
                got = fetch_yahoo(ymap[meta["name"]])
            except Exception as e:  # noqa: BLE001
                errors.append(f"yahoo:{ymap[meta['name']]} {type(e).__name__}")
        item = {k: meta.get(k) for k in ("name", "unit", "category")}
        out.append({**item, **(got or {"value": None, "change_pct": None, "source": None, "ts": None})})
        time.sleep(0.3)

    return out, errors
