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
LINKMAP_PATH = ROOT / "data" / "link_map.json"
SEEN_KEEP_DAYS = 7

# 聚合跳转链接域名（中国大陆通常无法直接打开 news.google.com），需还原为原文直链或给国内检索兜底
_AGG_MARKERS = ("news.google.com", "bing.com/news", "bing.com/newsv7", "/news/apiclick", "msn.com/en-us/news")


def is_aggregator(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in _AGG_MARKERS)


def domestic_search_url(title: str) -> str:
    """国内可达的原文检索入口：百度按标题搜索，首条通常即媒体原文。"""
    from urllib.parse import quote_plus
    return "https://www.baidu.com/s?wd=" + quote_plus((title or "").strip()[:80])


def load_link_map() -> dict:
    if LINKMAP_PATH.exists():
        try:
            return json.loads(LINKMAP_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_link_map(link_map: dict) -> None:
    # 仅保留最近 2000 条，避免无限膨胀
    if len(link_map) > 2000:
        link_map = dict(list(link_map.items())[-2000:])
    LINKMAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINKMAP_PATH.write_text(json.dumps(link_map, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_one(url: str, timeout: float) -> str | None:
    """尝试把聚合跳转链接还原为媒体原文直链（跟随重定向）。失败/仍是聚合页返回 None。

    带 Google 同意 cookie 与美区参数，尽量绕过 consent/JS 中间页拿到对原文的 302；
    新版加密链接若仍只返回 200 HTML 则放弃（不做激进的页面 URL 猜测，避免给错链接）。
    """
    try:
        target = url + ("&" if "?" in url else "?") + "hl=en-US&gl=US&ceid=US:en"
        cookies = {"CONSENT": "PENDING+987",
                   "SOCS": "CAISHAgCEhJnd3NfMjAyNDA5MjctMF9SQzEaAmRlIAEaBgiA_LGuBg"}
        r = requests.get(target, headers={"User-Agent": _UA,
                                          "Accept-Language": "en-US,en;q=0.9",
                                          "Referer": "https://news.google.com/"},
                         cookies=cookies, timeout=timeout, allow_redirects=True)
        final = r.url
        if final and not is_aggregator(final) and final.startswith("http"):
            return final
    except Exception:  # noqa: BLE001
        return None
    return None


def resolve_links(items: list[dict], link_map: dict, timeout: float = 6.0,
                  workers: int = 8) -> dict:
    """对聚合链接尽力还原真实网址；按 hash 缓存，只对未缓存项请求网络，更新后返回 link_map。

    解析成功会就地把 item['link'] 替换为原文直链；失败保留聚合链接，由渲染层给国内检索兜底。
    """
    from concurrent.futures import ThreadPoolExecutor

    pending: dict[str, str] = {}
    for it in items:
        h = it.get("hash") or title_hash(it["title"])
        if not h:
            continue
        if h in link_map and link_map[h]:
            it["link"] = link_map[h]
        elif is_aggregator(it.get("link", "")) and h not in pending:
            pending[h] = it["link"]

    if pending:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_resolve_one, u, timeout): h for h, u in pending.items()}
            for fut in futs:
                h = futs[fut]
                real = None
                try:
                    real = fut.result()
                except Exception:  # noqa: BLE001
                    real = None
                if real:
                    link_map[h] = real
        # 用解析结果回填本轮 item
        for it in items:
            h = it.get("hash") or title_hash(it["title"])
            if link_map.get(h):
                it["link"] = link_map[h]
    return link_map



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
