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

    # 3) 行情基线兜底（实时源全失败时，用 7 天内人工核验报价占位并标注）
    _apply_seed_prices(quote_items, bundle["seed_prices"], cn_time)

    # 4) 事件分析：仅对新增事件评分；若本周期无新增，回退近24h存量信号（在报告中注明）
    matrix = analyze.load_matrix()
    analysis_input = bundle["new_items"] if bundle["new_items"] else bundle["recent_items"]
    using_recent_fallback = not bool(bundle["new_items"])
    analysis = analyze.analyze(analysis_input, matrix)

    # 5) 现货报价提取（新增 + 近24h）
    merged: dict[str, dict] = {}
    for it in bundle["new_items"] + bundle["recent_items"]:
        merged[it["hash"]] = it
    spot = analyze.extract_spot_prices(list(merged.values()), cfg["prices"]["spot_patterns"])
    # 现货报价跨期沿用（TTL 内最近值），仅用于国内电价等量化推演；2.2 表仍展示当期提取值
    effective_spot = spot_store.merge(spot, cn_time)

    # 6) 可选 LLM 研判
    commentary = analyze.llm_commentary(analysis, analysis_input, quote_items)

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
        "spot": spot,
        "cn": cn_view,
        "llm": commentary,
        "errors": errors,
        "fallback_window": using_recent_fallback,
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
