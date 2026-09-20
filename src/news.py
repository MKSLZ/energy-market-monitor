"""能源新闻聚合：Google News RSS（多关键词、中英文）+ 公开 RSS 直连源。

- 本地无状态，去重状态持久化在 data/state.json
- 任意单源失败不影响整体，错误收集后返回
- 支持 data/seed_events.json 人工核验基线（首跑时并入事件流；基线价格供 monitor 兜底）
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_RETRY_STATUS = {429, 500, 502, 503}


def _parse_feed(url: str, timeout: int = 12, retries: int = 2):
    """带超时、限流退避重试的 RSS 下载与解析。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout, allow_redirects=True)
            if r.status_code in _RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            if getattr(feed, "bozo", 0) and not feed.entries:
                # 被反爬/区域重定向到 HTML 页时视为失败
                raise RuntimeError(str(getattr(feed, "bozo_exception", "empty feed")))
            return feed
        except Exception as ex:  # noqa: BLE001
            last_exc = ex
            time.sleep(5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _google_url(q: dict, lookback_hours: int) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(q["q"] + f" when:{lookback_hours}h")
        + f"&hl={q['hl']}&gl={q['gl']}&ceid={q['ceid']}"
    )


def _bing_url(q: dict) -> str:
    lang = "zh-Hans" if q["hl"].startswith("zh") else "en-US"
    cc = "CN" if lang == "zh-Hans" else "US"
    return (
        "https://www.bing.com/news/search?q="
        + quote_plus(q["q"])
        + f"&format=RSS&setlang={lang}&cc={cc}"
    )

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
SEED_PATH = ROOT / "data" / "seed_events.json"
SEEN_KEEP_DAYS = 7


def _cn_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def title_hash(title: str) -> str:
    t = re.sub(r"\s+", "", title.lower())
    t = re.sub(r"[\W_]+", "", t, flags=re.UNICODE)
    return hashlib.md5(t[:120].encode("utf-8")).hexdigest()[:12]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"seen": {}, "runs": 0}


def save_state(state: dict) -> None:
    cutoff = _cn_now() - timedelta(days=SEEN_KEEP_DAYS)
    state["seen"] = {
        k: v
        for k, v in state.get("seen", {}).items()
        if _safe_parse(v, cutoff) >= cutoff
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_parse(iso_str: str, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:  # noqa: BLE001
        return fallback


def _entry_time(entry) -> datetime | None:
    pp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if pp:
        return datetime(*pp[:6], tzinfo=timezone.utc)
    return None


def _split_title_source(raw_title: str, feed_source: str) -> tuple[str, str]:
    # Google News 形如 "Headline - Media"
    if " - " in raw_title:
        head, _, src = raw_title.rpartition(" - ")
        if len(src) <= 40:
            return head.strip(), src.strip()
    return raw_title.strip(), feed_source


def fetch_google_news(queries: list[dict], limit: int, lookback_hours: int) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    for q in queries:
        feed = None
        channel = "google_news"
        try:
            feed = _parse_feed(_google_url(q, lookback_hours), retries=2)
        except Exception as ex:  # noqa: BLE001
            errors.append(f"google:{q['q']} {type(ex).__name__}")
            try:
                feed = _parse_feed(_bing_url(q), retries=1)
                channel = "bing_news"
            except Exception as ex2:  # noqa: BLE001
                errors.append(f"bing:{q['q']} {type(ex2).__name__}")
        if feed is not None:
            for e in feed.entries[:limit]:
                title, src = _split_title_source(e.get("title", ""), "Bing/Google News")
                ts = _entry_time(e)
                if ts and ts < cutoff:
                    continue
                items.append(
                    {
                        "title": title,
                        "link": e.get("link", ""),
                        "source": src,
                        "query": q["q"],
                        "published": ts.astimezone(timezone(timedelta(hours=8))).isoformat(timespec="minutes")
                        if ts
                        else _cn_now().isoformat(timespec="minutes"),
                        "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:300],
                        "channel": channel,
                    }
                )
        time.sleep(random.uniform(1.5, 3.2))
    return items, errors


def fetch_direct_feeds(feeds: list[dict], keywords: list[str], lookback_hours: int) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    kws = [k.lower() for k in keywords]
    for f in feeds:
        try:
            feed = _parse_feed(f["url"])
            if getattr(feed, "bozo", 0) and not feed.entries:
                raise RuntimeError(str(getattr(feed, "bozo_exception", "empty feed")))
            for e in feed.entries[:30]:
                title = e.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", e.get("summary", ""))[:300]
                blob = (title + " " + summary).lower()
                if not any(k in blob for k in kws):
                    continue
                ts = _entry_time(e)
                if ts and ts < cutoff:
                    continue
                items.append(
                    {
                        "title": title,
                        "link": e.get("link", ""),
                        "source": f["name"],
                        "query": "direct_feed",
                        "published": ts.astimezone(timezone(timedelta(hours=8))).isoformat(timespec="minutes")
                        if ts
                        else _cn_now().isoformat(timespec="minutes"),
                        "summary": summary,
                        "channel": "direct_feed",
                    }
                )
        except Exception as ex:  # noqa: BLE001
            errors.append(f"feed:{f['name']} {type(ex).__name__}")
        time.sleep(0.3)
    return items, errors


def load_seed(include_items: bool) -> dict:
    if not SEED_PATH.exists():
        return {"items": [], "prices": []}
    try:
        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"items": [], "prices": []}
    items = []
    if include_items:
        for it in data.get("items", []):
            it = {**it, "channel": "seed", "query": "manual_baseline"}
            it.setdefault("source", it.pop("source_name", "人工核验基线"))
            it.setdefault("summary", "")
            items.append(it)
    return {"items": items, "prices": data.get("prices", [])}


def collect(cfg: dict) -> dict:
    state = load_state()
    first_run = not bool(state.get("seen"))
    seed = load_seed(include_items=first_run)

    ncfg = cfg["news"]
    g_items, g_err = fetch_google_news(ncfg["google_news"], ncfg["per_query_limit"], ncfg["lookback_hours"])
    d_items, d_err = fetch_direct_feeds(ncfg["direct_feeds"], ncfg["filter_keywords"], ncfg["lookback_hours"])

    raw = seed["items"] + g_items + d_items

    # 全局去重（本次运行内 + 历史）
    uniq: dict[str, dict] = {}
    for it in raw:
        h = title_hash(it["title"])
        it["hash"] = h
        if h not in uniq:
            uniq[h] = it

    new_items, recent_items = [], []
    for h, it in uniq.items():
        if h not in state["seen"]:
            state["seen"][h] = _cn_now().isoformat(timespec="minutes")
            new_items.append(it)
        recent_items.append(it)

    # 按时间倒序
    new_items.sort(key=lambda x: x["published"], reverse=True)
    recent_items.sort(key=lambda x: x["published"], reverse=True)
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = _cn_now().isoformat(timespec="minutes")
    save_state(state)

    return {
        "new_items": new_items[: ncfg["max_items_in_report"]],
        "recent_items": recent_items[: ncfg["max_items_in_report"]],
        "new_count": len(new_items),
        "total_count": len(recent_items),
        "errors": g_err + d_err,
        "seed_prices": seed["prices"],
        "first_run": first_run,
        "run_no": state["runs"],
    }
