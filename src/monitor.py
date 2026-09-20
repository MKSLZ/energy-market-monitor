"""监控主入口：抓行情 -> 聚合新闻 -> 传导分析 -> 生成日报。

用法：python -m src.monitor
退出码恒为 0（单源/单模块失败已内部降级），保证 GitHub Actions 的提交步骤可执行。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from src import analyze, cn_power, html_report, news, prices, report, spot_store

ROOT = report.ROOT
CN_TZ = timezone(timedelta(hours=8))


def main() -> int:
    cn_time = datetime.now(CN_TZ)
    cfg = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    # 1) 行情
    quote_items, price_errs = prices.fetch_all(cfg)
    errors += price_errs

    # 2) 新闻（首跑会并入人工核验基线）
    bundle = news.collect(cfg)
    errors += bundle["errors"]

    # 2.5) 链接治理：把 Google/Bing 聚合跳转链接尽力还原为媒体原文直链（云端美国网络，按 hash 缓存）；
    #      解析不出的保留聚合链接，渲染层给国内可达的百度检索兜底，确保每条资讯在国内都能找到原文。
    link_map = news.load_link_map()
    _link_items, _seen_h = [], set()
    for it in bundle["new_items"] + bundle["recent_items"]:
        if it["hash"] not in _seen_h:
            _seen_h.add(it["hash"])
            _link_items.append(it)
    try:
        link_map = news.resolve_links(_link_items, link_map)
        news.save_link_map(link_map)
    except Exception as ex:  # noqa: BLE001
        errors.append(f"link_resolve {type(ex).__name__}")

    # 3) 行情基线兜底（实时源全失败时，用 7 天内人工核验报价占位并标注）
    _apply_seed_prices(quote_items, bundle["seed_prices"], cn_time)

    # 4) 事件分析（双层）：
    #    主态势 analysis —— 近 24h 滚动窗口，保证任何时候打开都反映当前市场状态；
    #    边际 delta      —— 仅本周期新增事件，体现最近 3 小时的边际变化。
    matrix = analyze.load_matrix()
    new_hashes = {it["hash"] for it in bundle["new_items"]}
    analysis = analyze.analyze(bundle["recent_items"], matrix, new_hashes=new_hashes)
    delta = analyze.analyze(bundle["new_items"], matrix)
    no_new_events = not bool(bundle["new_items"])

    # 5) 现货报价提取（新增 + 近24h）
    merged: dict[str, dict] = {}
    for it in bundle["new_items"] + bundle["recent_items"]:
        merged[it["hash"]] = it
    spot_news = analyze.extract_spot_prices(list(merged.values()), cfg["prices"]["spot_patterns"])
    # 确定性区域基准（国际煤价/欧洲日前电价）优先；新闻正则补充未覆盖的基准（如秦港、TTF）
    live_spot, live_errs = prices.fetch_live_spot(cfg)
    errors += live_errs
    spot = list(live_spot)
    _have = {s["id"] for s in live_spot}
    for s in spot_news:
        if s["id"] not in _have:
            spot.append(s)
    # 现货报价跨期沿用（TTL 内最近值），仅用于国内电价等量化推演；2.2 表展示当期值（含确定性源）
    effective_spot = spot_store.merge(spot, cn_time)

    # 6) 可选 LLM 研判（基于 24h 滚动态势）
    commentary = analyze.llm_commentary(analysis, bundle["recent_items"], quote_items)

    # 6.5) 国内电价专项推演（油/气/煤价格与事件 → 中国国内电价，分时间/分区域量化）
    cn_view = cn_power.build_view(
        quote_items, effective_spot, analysis["signals"], analysis["temperature"], list(merged.values())
    )

    ctx = {
        "cn_time": cn_time,
        "run_no": bundle.get("run_no", 1),
        "config": cfg,
        "prices": quote_items,
        "news": bundle,
        "analysis": analysis,
        "delta": delta,
        "spot": spot,
        "cn": cn_view,
        "llm": commentary,
        "errors": errors,
        "fallback_window": no_new_events,
    }
    md = report.render(ctx)
    paths = report.save(md, cn_time)

    # 7) HTML 网页日报（GitHub Pages 站点：site/index.html + 按日归档）
    page_html = html_report.render(ctx)
    hpaths = html_report.save("", page_html, cn_time)

    snapshot = {
        "run_time": cn_time.isoformat(timespec="minutes"),
        "run_no": ctx["run_no"],
        "temperature": analysis["temperature"],
        "new_events": bundle["new_count"],
        "errors": errors,
        "llm_enabled": bool(commentary),
        "html": hpaths["site"],
    }
    (ROOT / "data" / "last_run.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] report #{ctx['run_no']} -> {paths['archive']}")
    for k, v in analysis["temperature"].items():
        print(f"  {v['name']}: {v['label']} score={v['score']} (+{v['pos']}/-{v['neg']})")
    if errors:
        print(f"[WARN] {len(errors)} source(s) failed (degraded, see report)")
    return 0


def _apply_seed_prices(quote_items: list[dict], seed_prices: list[dict], now: datetime) -> None:
    if not seed_prices:
        return
    seed_map = {p["name"]: p for p in seed_prices}
    for q in quote_items:
        if q.get("value") is not None:
            continue
        s = seed_map.get(q["name"])
        if not s:
            continue
        try:
            pub = datetime.fromisoformat(s["ts"])
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=CN_TZ)
        except Exception:  # noqa: BLE001
            continue
        if now - pub.astimezone(CN_TZ) <= timedelta(days=7):
            q.update({"value": s["value"], "change_pct": s.get("change_pct"),
                      "source": s.get("source", "人工核验基线"), "ts": s["ts"], "fallback": True})


if __name__ == "__main__":
    sys.exit(main())
