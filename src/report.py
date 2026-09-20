"""Markdown 日报渲染与落盘。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
ARCHIVE = REPORTS / "archive"

ARROW = {"强烈看涨": "▲▲", "偏强": "▲", "中性（多空交织）": "—", "偏弱": "▼", "强烈看弱": "▼▼"}

WATCH_CALENDAR = """- **每周三 22:30（北京）**：美国 EIA 原油/成品油库存周报
- **每周**：美国钻井数（Baker Hughes）、国内秦港 Q5500 现货日报、欧洲储气率周报（AGSI）
- **每月上旬**：EIA STEO、IEA 石油市场月报、OPEC 月报（供需平衡与三大机构预期差）
- **不定时**：OPEC+ 部长级会议/JMMC、美联储 FOMC、国内发改委/能源局电价与保供政策、各省电力现货结算公告"""


def render(ctx: dict) -> str:
    cn: datetime = ctx["cn_time"]
    run_no = ctx["run_no"]
    temp = ctx["analysis"]["temperature"]
    L: list[str] = []

    L.append(f"# 能源电力市场监控日报（第 {run_no} 期）")
    L.append("")
    L.append(f"> 生成时间：{cn.strftime('%Y-%m-%d %H:%M')}（北京/UTC+8）　|　监控周期：每 3 小时　|　"
             f"新增事件：{ctx['news']['new_count']} 条　|　命中主题：{ctx['analysis']['tagged_count']} 条")
    if ctx["news"]["first_run"]:
        L.append(">")
        L.append("> **首期运行**：事件池包含人工核验基线（2026-09-20 前公开信息），后续各期仅展示新监控到的增量信息。")
    L.append("")

    # 1 速览
    L.append("## 一、四品种影响速览")
    L.append("")
    L.append("| 品种 | 方向信号 | 量化评分 | 本期利多/利空事件数 | 核心驱动（Top） |")
    L.append("|---|---|---|---|---|")
    for key in ("oil", "gas", "coal", "power"):
        v = temp[key]
        top = _top_driver(ctx["analysis"]["signals"], key)
        L.append(f"| {v['name']} | {ARROW[v['label']]} {v['label']} | {v['score']} | {v['pos']} / {v['neg']} | {top} |")
    L.append("")
    L.append("> 评分=Σ(主题权重×历史影响强度×方向)，仅衡量本期新增事件的边际压力，非价格预测点位；评分高代表边际驱动集中。")
    L.append("")

    # 2 行情
    L.append("## 二、行情快照")
    L.append("")
    L.append("### 2.1 国际期货与宏观（自动抓取）")
    L.append("")
    L.append("| 品种 | 最新价 | 日涨跌 | 单位 | 数据源 | 时间 |")
    L.append("|---|---|---|---|---|---|")
    for p in ctx["prices"]:
        if p.get("value") is None:
            L.append(f"| {p['name']} | 抓取失败 | - | {p['unit']} | - | 见页脚错误日志 |")
        else:
            chg = f"{p['change_pct']:+.2f}%" if p.get("change_pct") is not None else "-"
            tag = "（基线报价）" if p.get("fallback") else ""
            L.append(f"| {p['name']}{tag} | {p['value']} | {chg} | {p['unit']} | {p.get('source') or '人工核验基线'} | {p.get('ts') or '-'} |")
    L.append("")
    L.append("### 2.2 区域现货参考（新闻文本自动提取）")
    L.append("")
    if ctx["spot"]:
        L.append("| 基准 | 报价 | 单位 | 出处 | 时间 |")
        L.append("|---|---|---|---|---|")
        for s in ctx["spot"]:
            L.append(f"| {s['name']} | {s['value']} | {s['unit']} | {s['source']}：{s['evidence'][:34]} | {s['published'][:16]} |")
    else:
        L.append("_本期新闻文本未识别到结构化现货报价。_")
    L.append("")

    # 3 重大事件
    L.append("## 三、本期重大事件（按影响因子分组）")
    L.append("")
    sigs = ctx["analysis"]["signals"]
    if not sigs:
        L.append("_本期新增新闻未命中核心影响因子，可能以噪声/价格复述为主。_")
    for i, sg in enumerate(sigs, 1):
        if sg.get("structural"):
            L.append(f"### 3.{i} {sg['name']}　【{sg['category']}｜结构性变化：{sg['neutral'] + sg['up'] + sg['down']} 条相关，不计多空评分】")
        else:
            L.append(f"### 3.{i} {sg['name']}　【{sg['category']}｜对商品利多 {sg['up']} 条 / 利空 {sg['down']} 条】")
        for ev in sg["evidence"]:
            mark = {1: "▲", -1: "▼"}.get(ev.get("real_dir", 0), "•")
            tail = f"（反转信号：{ev['inverter']}）" if ev["inverter"] else ""
            L.append(f"- {mark} [{ev['title']}]({ev['link']}) — {ev['source']}，{ev['published'][:16]}{tail}")
        L.append("")
    other = [x for x in ctx["news"]["new_items"] if x.get("channel") != "seed"][:10]
    if other:
        L.append("<details><summary>其他能源相关资讯（点击展开）</summary>")
        L.append("")
        for it in other:
            L.append(f"- [{it['title']}]({it['link']}) — {it['source']}，{it['published'][:16]}")
        L.append("")
        L.append("</details>")
        L.append("")

    # 4 推演
    L.append("## 四、事件 → 价格传导推演（基于历史经验矩阵）")
    L.append("")
    for key in ("oil", "gas", "coal", "power"):
        v = temp[key]
        L.append(f"### 4.{['oil','gas','coal','power'].index(key)+1} {v['name']}：{ARROW[v['label']]} {v['label']}（评分 {v['score']}）")
        drivers, channels, horizons = _driver_details(sigs, key)
        if drivers:
            L.append(f"- **本期驱动**：{'；'.join(drivers)}")
            for ch in channels[:4]:
                L.append(f"- **传导逻辑**：{ch}")
            for hz in horizons[:3]:
                L.append(f"- **时滞/持续性**：{hz}")
        else:
            L.append("- **本期驱动**：无显著新增冲击，价格沿存量主线（地缘溢价、季节性与政策预期）运行。")
        if key == "power":
            L.append("- **中国市场注记**：国内电量电价受中长期合约、容量电价与政府调控平滑，对国际油气短期冲击钝化；"
                     "成本压力主要通过次年长协谈判与沿海现货报价体现。结构性看，现货扩围+负价下限调整使**峰谷价差双向放大**，不能只看日均价。")
            L.append("- **欧洲市场注记**：气电为边际定价机组，TTF→批发电价近似完全传导；电价冬季合约对储气率与寒潮高度敏感。")
        if key == "coal":
            L.append("- **结构注记**：国内看'三西'安监与秦港库存，进口看印尼 HBA/RKAB 与纽卡斯尔；长协煤（'三锁'定价）与现货价差决定电厂采购节奏。")
        L.append("")

    # 5 综合研判
    L.append("## 五、综合研判与情景")
    L.append("")
    if ctx.get("llm"):
        L.append(ctx["llm"])
        L.append("")
    L.append(_scenario_block(temp, sigs))
    L.append("")
    L.append("**关注日历**")
    L.append("")
    L.append(WATCH_CALENDAR)
    L.append("")

    # 6 附录
    L.append("## 六、运行信息与免责声明")
    L.append("")
    L.append(f"- 抓取条目：新增 {ctx['news']['new_count']} / 近24h去重后 {ctx['news']['total_count']}；"
             f"未命中主题 {ctx['analysis']['untagged_count']} 条（作为资讯留存，不进入评分）")
    L.append(f"- 数据源：Google News RSS（{len(ctx['config']['news']['google_news'])} 组关键词，中英文）、"
             f"公开 RSS {len(ctx['config']['news']['direct_feeds'])} 个、Yahoo Finance/Stooq 行情")
    if ctx["errors"]:
        L.append(f"- 本次失败源（{len(ctx['errors'])}，已自动跳过，不影响其余源）：`{'`, `'.join(ctx['errors'][:12])}`")
    else:
        L.append("- 本次所有数据源请求成功。")
    L.append("- **免责声明**：本报告由监控程序基于公开信息与预设的历史传导规则自动生成，仅供交易研究参考，"
             "不构成任何投资建议。规则方向为历史经验的统计性概括，单次事件的实际价格反应受仓位、预期差、"
             "政策干预与流动性影响，可能与历史规律偏离，请结合实时盘口独立决策。")
    L.append("")
    return "\n".join(L)


def _top_driver(signals: list[dict], ck: str) -> str:
    best, best_score = "", 0
    for sg in signals:
        eff = sg["effects"].get(ck, {})
        if eff.get("mag", 0) == 0 or eff.get("dir", 0) == 0:
            continue
        score = (sg["up"] + sg["down"]) * eff["mag"] * abs(eff["dir"]) * sg["direction"] * eff["dir"]
        if score > best_score:
            best_score, best = score, sg["name"]
    return best or "—"


def _driver_details(signals: list[dict], ck: str):
    drivers, channels, horizons = [], [], []
    for sg in signals:
        eff = sg["effects"].get(ck, {})
        if eff.get("mag", 0) == 0 or eff.get("dir", 0) == 0:
            continue
        arrow = "▲" if eff["dir"] * sg["direction"] > 0 else "▼"
        drivers.append(f'{arrow}{sg["name"]}（强度{eff["mag"]}/5，{sg["up"]+sg["down"]}条证据）')
        if eff.get("channel") and eff["channel"] != "-" and eff["channel"] not in channels:
            channels.append(eff["channel"])
        if eff.get("horizon") and eff["horizon"] != "-" and eff["horizon"] not in horizons:
            horizons.append(eff["horizon"])
    return drivers, channels, horizons


def _scenario_block(temp: dict, sigs: list[dict]) -> str:
    geo_on = any(s["id"] == "middle_east" and s["direction"] > 0 for s in sigs)
    lines = ["**情景推演（未来 3 小时～3 个交易日）**", ""]
    if geo_on:
        lines += [
            "- **基准情景**：中东局势维持紧张但未进一步断航 → 油价维持地缘溢价、高位震荡；TTF/欧洲电价易涨难跌；"
            "亚太煤价受气煤切换支撑，国内现货煤价随产地约束与补库延续偏强，电价情绪面向暖。",
            "- **上行情景**：霍尔木兹通航进一步受阻或冲突外溢（袭击升级、制裁加码）→ 油气跳涨，煤炭被动跟涨，"
            "欧洲冬季电价与国内次年长协预期同步上修。",
            "- **下行情景**：停火/复航/谈判进展、OPEC+放量或战略储备投放 → 风险溢价快速回吐，气价弹性大于油价，"
            "高价煤回落，现货电价情绪转弱。",
        ]
    else:
        strongest = max(temp.values(), key=lambda v: abs(v["score"]))
        lines.append(
            f"- **基准情景**：无单一主导冲击，市场按库存/天气/宏观数据交易；当前边际最强品种为**{strongest['name']}**（{strongest['label']}）。"
        )
        lines.append("- **上下行风险**：关注库存周度数据、美联储表态与主要经济体需求预期修正带来的再定价。")
    return "\n".join(lines)


def save(md: str, cn: datetime) -> dict:
    REPORTS.mkdir(exist_ok=True)
    day_dir = ARCHIVE / cn.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    archive_path = day_dir / f"{cn.strftime('%H%M')}.md"
    archive_path.write_text(md, encoding="utf-8")
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    _rebuild_index()
    return {"archive": str(archive_path.relative_to(ROOT)), "latest": "reports/latest.md"}


def _rebuild_index() -> None:
    files = sorted(ARCHIVE.rglob("*.md"), reverse=True)[:60]
    lines = ["# 日报归档", "", "| 期次（时间） | 链接 |", "|---|---|"]
    for f in files:
        rel = f.relative_to(REPORTS)
        stem = f"{f.parent.name} {f.stem[:2]}:{f.stem[2:]}"
        lines.append(f"| {stem} | [{f.stem}.md]({rel.as_posix()}) |")
    (REPORTS / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
