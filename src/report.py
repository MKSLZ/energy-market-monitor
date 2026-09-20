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
    delta_temp = (ctx.get("delta") or {}).get("temperature", {})
    L.append(f"> 生成时间：{cn.strftime('%Y-%m-%d %H:%M')}（北京/UTC+8）　|　监控周期：每 3 小时　|　"
             f"本3h新增：{ctx['news']['new_count']} 条、命中 {(ctx.get('delta') or {}).get('tagged_count', 0)} 主题　|　"
             f"近24h事件：{ctx['news']['total_count']} 条、命中 {ctx['analysis']['tagged_count']} 主题")
    if ctx["news"]["first_run"]:
        L.append(">")
        L.append("> **首期运行**：事件池包含人工核验基线（2026-09-20 前公开信息），后续各期仅展示新监控到的增量信息。")
    if ctx.get("fallback_window"):
        L.append(">")
        L.append("> **本3小时无新增重大事件**，下列主态势基于近 24 小时滚动资讯，价格沿既有主线运行；本3h边际均为 0。")
    L.append("")

    # 1 速览
    L.append("## 一、四品种影响速览（主分=近24h市场态势，末列=本3h边际）")
    L.append("")
    L.append("| 品种 | 方向信号 | 24h态势分 | 近24h利多/利空 | 本3h边际 | 核心驱动（Top） |")
    L.append("|---|---|---|---|---|---|")
    for key in ("oil", "gas", "coal", "power"):
        v = temp[key]
        top = _top_driver(ctx["analysis"]["signals"], key)
        ds = delta_temp.get(key, {}).get("score", 0)
        dm = f"▲ +{ds:.0f}" if ds > 0 else (f"▼ {ds:.0f}" if ds < 0 else "无新增驱动")
        L.append(f"| {v['name']} | {ARROW[v['label']]} {v['label']} | {v['score']} | {v['pos']} / {v['neg']} | {dm} | {top} |")
    L.append("")
    L.append("> 24h态势分=Σ(主题权重×历史影响强度×方向)，同一因子只计一次，基于近24小时滚动事件，反映当前市场压力与集中度；本3h边际仅计最新3小时新增。均非价格预测点位。")
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
    L.append("## 三、近24小时重大事件（按影响因子分组，**[NEW·3h]** 为本3小时新增）")
    L.append("")
    sigs = ctx["analysis"]["signals"]
    if not sigs:
        L.append("_近24小时监控到的资讯未命中核心影响因子，多为噪声/价格复述；行情与国内电价板块仍在更新。_")
    for i, sg in enumerate(sigs, 1):
        n_new = sum(1 for evd in sg["evidence"] if evd.get("new"))
        ntip = f"，其中本3h新增 {n_new}" if n_new else ""
        if sg.get("structural"):
            L.append(f"### 3.{i} {sg['name']}　【{sg['category']}｜结构性变化：{sg['neutral'] + sg['up'] + sg['down']} 条相关，不计多空评分{ntip}】")
        else:
            L.append(f"### 3.{i} {sg['name']}　【{sg['category']}｜近24h对商品利多 {sg['up']} 条 / 利空 {sg['down']} 条{ntip}】")
        for ev in sg["evidence"]:
            mark = {1: "▲", -1: "▼"}.get(ev.get("real_dir", 0), "•")
            newb = "**[NEW·3h]** " if ev.get("new") else ""
            tail = f"（反转信号：{ev['inverter']}）" if ev["inverter"] else ""
            L.append(f"- {mark} {newb}[{ev['title']}]({ev['link']}) — {ev['source']}，{ev['published'][:16]}{tail}")
        L.append("")
    other = [x for x in ctx["news"]["new_items"] if x.get("channel") != "seed"][:10]
    if other:
        L.append("<details><summary>本3小时其他新增资讯（点击展开）</summary>")
        L.append("")
        for it in other:
            L.append(f"- [{it['title']}]({it['link']}) — {it['source']}，{it['published'][:16]}")
        L.append("")
        L.append("</details>")
        L.append("")

    # 4 推演
    L.append("## 四、事件 → 价格传导推演（近24h主线 · 基于历史经验矩阵）")
    L.append("")
    for key in ("oil", "gas", "coal", "power"):
        v = temp[key]
        ds = delta_temp.get(key, {}).get("score", 0)
        dm = f"本3h边际 ▲+{ds:.0f}" if ds > 0 else (f"本3h边际 ▼{ds:.0f}" if ds < 0 else "本3h无新增驱动")
        L.append(f"### 4.{['oil','gas','coal','power'].index(key)+1} {v['name']}：{ARROW[v['label']]} {v['label']}（24h态势 {v['score']}；{dm}）")
        drivers, channels, horizons = _driver_details(sigs, key)
        if drivers:
            L.append(f"- **近24h主线驱动**：{'；'.join(drivers)}")
            for ch in channels[:4]:
                L.append(f"- **传导逻辑**：{ch}")
            for hz in horizons[:3]:
                L.append(f"- **时滞/持续性**：{hz}")
        else:
            L.append("- **近24h主线驱动**：无显著主导因子，价格沿存量主线（地缘溢价、季节性与政策预期）运行。")
        if key == "power":
            L.append("- **中国市场注记**：国内电量电价受中长期合约、容量电价与政府调控平滑，对国际油气短期冲击钝化；"
                     "成本压力主要通过次年长协谈判与沿海现货报价体现。结构性看，现货扩围+负价下限调整使**峰谷价差双向放大**，不能只看日均价。")
            L.append("- **欧洲市场注记**：气电为边际定价机组，TTF→批发电价近似完全传导；电价冬季合约对储气率与寒潮高度敏感。")
        if key == "coal":
            L.append("- **结构注记**：国内看'三西'安监与秦港库存，进口看印尼 HBA/RKAB 与纽卡斯尔；长协煤（'三锁'定价）与现货价差决定电厂采购节奏。")
        L.append("")

    # 5 国内电价专项
    L.append(_cn_md(ctx))

    # 6 综合研判
    L.append("## 六、综合研判与情景")
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

    # 7 附录
    L.append("## 七、运行信息与免责声明")
    L.append("")
    L.append(f"- 抓取条目：新增 {ctx['news']['new_count']} / 近24h去重后 {ctx['news']['total_count']}；"
             f"未命中主题 {ctx['analysis']['untagged_count']} 条（作为资讯留存，不进入评分）")
    L.append(f"- 数据源：Google News RSS（{len(ctx['config']['news']['google_news'])} 组关键词，中英文）、"
             f"公开 RSS {len(ctx['config']['news']['direct_feeds'])} 个、CNBC 行情（Yahoo 备用）")
    if ctx["errors"]:
        L.append(f"- 本次失败源（{len(ctx['errors'])}，已自动跳过，不影响其余源）：`{'`, `'.join(ctx['errors'][:12])}`")
    else:
        L.append("- 本次所有数据源请求成功。")
    L.append("- **免责声明**：本报告由监控程序基于公开信息与预设的历史传导规则自动生成，仅供交易研究参考，"
             "不构成任何投资建议。规则方向为历史经验的统计性概括，单次事件的实际价格反应受仓位、预期差、"
             "政策干预与流动性影响，可能与历史规律偏离，请结合实时盘口独立决策。")
    L.append("")
    return "\n".join(L)


def _cn_md(ctx: dict) -> str:
    cn = ctx.get("cn")
    if not cn:
        return ""
    coal, gas, oil, pm = cn["coal"], cn["gas"], cn["oil"], cn["params"]
    q = coal.get("q5500")
    nc = pm.get("newcastle")
    cdt = (f"（{coal.get('q_date')}·当期）" if coal.get("q_fresh", True) else f"（沿用{coal.get('q_date')}）") if q is not None and coal.get("q_date") else ""
    tdt = (f"（{gas.get('ttf_date')}·当期）" if gas.get("t_fresh", True) else f"（沿用{gas.get('ttf_date')}）") if gas.get("ttf") is not None and gas.get("ttf_date") else ""
    ttf_part = (f"TTF {gas.get('ttf')} 欧元/兆瓦时 {tdt}" if gas.get("ttf") is not None
                else (f"TTF 待报（HH {gas.get('hh')} 美元/百万英热）" if gas.get("hh") is not None else "TTF 待报"))
    if q is not None:
        cstate = coal.get("bracket")
    elif nc is not None:
        cstate = f"秦港待报·国际煤 {nc:.0f}$"
    else:
        cstate = "报价缺失"
    L = ["## 五、国内电价专项推演 · 事件 / 油价 / 气价 / 煤价 → 中国电价", ""]
    L.append(f"**国内现货电价成本压力指数：{cn['score']}/100（{cn['label']}）**")
    L.append("")
    L.append(cn["summary"])
    L.append("")
    L.append("### 5.1 三种能源对国内电价的传导权重")
    L.append("")
    L.append(f"- **原油（几乎不传导）**：Brent {oil.get('brent') if oil.get('brent') is not None else '—'} 美元/桶，"
             f"油电仅占发电约 {pm['oil_share']*100:.1f}%。{oil['verdict']}")
    L.append(f"- **天然气（沿海尖峰）**：{ttf_part}，"
             f"气电占发电约 {pm['gas_share']*100:.1f}%、气耗约 {gas['gas_use_m3']} m³/度。{gas['verdict']} "
             f"敏感度：气价每涨 1 元/方，气电度电燃料成本约 +{gas['cost_per_1yuan']:.0f} 分。")
    L.append(f"- **煤炭（定价主体）**：秦港Q5500 {q if q is not None else '—'} 元/吨 {cdt}（{cstate}），"
             f"煤电占发电约 {pm['coal_share']*100:.0f}%、度电煤耗约 300 克。国内电价以煤为锚，但约 80% 电煤走长协，"
             f"现货煤波动被大幅对冲；进口煤（约 9%、集中沿海）与国际煤价（纽卡斯尔 {nc if nc is not None else '—'}）主要影响边际与情绪。")
    L.append("")
    syn = bool(coal.get("synthetic", q is None))
    L.append(("### 5.2 煤价 → 度电燃料成本 · 情景对照（本期未取到秦港官方价，下列为假设档位）" if syn
              else "### 5.2 煤价 → 度电燃料成本测算（行业经验参数）"))
    L.append("")
    L.append("| 煤价情景：秦港Q5500（元/吨） | 边际煤机燃料成本（元/度） | 长协煤80%对冲后综合燃料成本（元/度） |")
    L.append("|---|---|---|")
    for sc in coal["scenarios"]:
        L.append(f"| {sc['coal_price']}（{sc['label']}） | {sc['marginal_fuel']:.3f} | {sc['blended_fuel']:.3f} |")
    L.append("")
    if not syn:
        L.append(f"> 当前较长协锚（{coal['anchor']:.0f} 元）：边际煤机燃料成本端约 **+{coal['marginal_gap_fen']:.0f} 分/度**；"
                 f"经长协煤对冲后，综合上网电量成本端约 **+{coal['blended_gap_fen']:.1f} 分/度**。"
                 "此为成本端推力、非电价预测点位；实际出清还取决于负荷、新能源出力与政策限价。")
    else:
        tail = f"国际煤价纽卡斯尔当前约 **{nc:.0f} 美元/吨**，高位进口煤对沿海现货与次年长协形成成本支撑。" if nc is not None else "国际煤价当前待报。"
        L.append(f"> 本期未取到秦港Q5500官方价，上表为假设煤价档位（非实测），用于弹性参照；{tail}"
                 "官方秦港价以 CECI 沿海电煤采购指数 / 秦皇岛海运煤炭交易网为准。")
    L.append("")
    L.append("### 5.3 对国内电价各环节的方向与时滞")
    L.append("")
    L.append("| 环节 | 方向 | 成本推力 | 说明 |")
    L.append("|---|---|---|---|")
    for hz in cn["horizons"]:
        if hz.get("push_fen"):
            push = f"+{hz['push_fen'][0]:.1f}~{hz['push_fen'][1]:.1f} 分/度"
        else:
            push = "滞后 1-2 个月" if hz["key"] == "retail" else "见 5.2 煤价情景"
        L.append(f"| {hz['name']} | {hz['dir']} | {push} | {hz['note']} |")
    L.append("")
    if cn.get("domestic_quotes"):
        L.append("### 5.4 本期新闻文本识别到的国内电价参考（自动提取，以官方交易中心为准）")
        L.append("")
        L.append("| 类型 | 数值 | 出处 |")
        L.append("|---|---|---|")
        for qt in cn["domestic_quotes"]:
            tname = "省现货均价（日前/实时）" if "兆瓦时" in qt["unit"] else "年度长协成交均价"
            L.append(f"| {tname} | {qt['value']} {qt['unit']} | {qt['source']}：{qt['evidence'][:30]} |")
        L.append("")
    L.append("**分区域敏感度**")
    L.append("")
    for r in cn["regions"]:
        L.append(f"- {r['region']}（{r['sensitivity']}）：{r['note']}")
    L.append("")
    L.append("**结构性机制提示（影响价格结构而非单一方向）**")
    L.append("")
    for n in cn["struct_notes"]:
        L.append(f"- {n}")
    L.append("")
    L.append("> 测算口径：供电煤耗约 300 克标煤/度、电煤长协约 80%（测算锚 700 元/吨，合理区间 570-770）、"
             "气电度电气耗约 0.19 m³，均为公开行业经验近似；数字为成本端推力，用于判断方向与弹性，"
             "不等于实际成交电价，不构成投资建议。")
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
