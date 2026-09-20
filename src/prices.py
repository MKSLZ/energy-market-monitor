"""能源期货行情抓取：CNBC 报价接口为主（云服务器 IP 友好、含涨跌幅），Yahoo Finance 为备。

无需 API Key。任何源失败均返回 None，由上层降级，不影响报告生成。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
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


def fetch_live_spot(cfg: dict) -> tuple[list[dict], list[str]]:
    """确定性区域基准取数（无 API Key）：Trading Economics 国际煤价、energy-charts 欧洲日前电价。

    新闻正则提取现货价不稳定，这里提供每 3 小时稳定的锚点；任一源失败返回错误并跳过，不影响主流程。
    返回结构与 analyze.extract_spot_prices 一致，可直接并入现货池。
    """
    out: list[dict] = []
    errors: list[str] = []
    now_iso = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes")
    browser_h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

    for meta in cfg.get("prices", {}).get("live_spot", []):
        try:
            typ = meta["type"]
            if typ == "tradingeconomics":
                r = requests.get(meta["url"], headers=browser_h, timeout=TIMEOUT)
                r.raise_for_status()
                m = re.search(r'"last"\s*:\s*"?(-?\d+(?:\.\d+)?)', r.text)
                if not m:
                    raise ValueError("last not found")
                val = float(m.group(1))
                lo, hi = meta.get("range", [-1e9, 1e9])
                if not (lo <= val <= hi):
                    raise ValueError(f"out of range {val}")
                evidence = f"{meta['name']}自动取数（Trading Economics）"
            elif typ == "energy_charts":
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=meta.get("lookback_days", 3))
                r = requests.get(
                    meta["url"],
                    params={"country": meta.get("country", "de"),
                            "start": start.strftime("%Y-%m-%dT%H:%MZ"),
                            "end": end.strftime("%Y-%m-%dT%H:%MZ")},
                    headers=browser_h, timeout=TIMEOUT,
                )
                r.raise_for_status()
                arr = [x for x in r.json().get("price", []) if x is not None]
                if not arr:
                    raise ValueError("empty price series")
                last24 = arr[-24:]
                val = sum(last24) / len(last24)   # 最近24小时日前均值，避免取到单小时极端价
                evidence = (f"{meta['name']}近24小时日前均值 {val:.1f}"
                            f"（最新小时 {arr[-1]:.1f}，近{len(arr)}小时均值 {sum(arr)/len(arr):.1f}）")
            else:
                errors.append(f"live_spot unknown:{typ}")
                continue
            out.append({"id": meta["id"], "name": meta["name"], "unit": meta["unit"],
                        "value": round(float(val), 2), "evidence": evidence,
                        "source": meta.get("source_name", typ),
                        "published": now_iso, "link": meta["url"]})
        except Exception as e:  # noqa: BLE001
            errors.append(f"live_spot:{meta.get('id')} {type(e).__name__}")
        time.sleep(0.4)
    return out, errors


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
