"""HTML 日报渲染器：专业能源交易终端风格、单文件内联样式、无外部依赖。

红涨绿跌（中国市场习惯），响应式；所有来自 RSS 的文本与链接均做转义/白名单处理。
输出：site/index.html（最新）、site/archive/YYYY-MM-DD.html（按日归档，日内覆盖）、
     site/archive/index.html（历史目录），另存 reports/latest.html。
"""
from __future__ import annotations

import html
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ARCHIVE_WEB = SITE / "archive"

SIG_META = {
    "强烈看涨": ("s-up2", "▲▲"),
    "偏强": ("s-up1", "▲"),
    "中性（多空交织）": ("s-flat", "—"),
    "偏弱": ("s-dn1", "▼"),
    "强烈看弱": ("s-dn2", "▼▼"),
}

CALENDAR = [
    ("每周三 22:30（北京）", "美国 EIA 原油 / 成品油库存周报"),
    ("每周", "美国活跃钻机数（Baker Hughes）、秦皇岛 Q5500 现货日报、欧洲储气率周报（AGSI）"),
    ("每月上旬", "EIA STEO、IEA 石油市场月报、OPEC 月报（三大机构供需平衡与预期差）"),
    ("不定时", "OPEC+ 部长级会议 / JMMC、美联储 FOMC、国内发改委 / 能源局电价与保供政策、各省现货结算公告"),
]

NOTE_POWER_CN = ("国内电量电价受中长期合约、容量电价与政府调控平滑，对国际油气短期冲击钝化；"
                 "成本压力主要通过次年长协谈判与沿海现货报价体现。现货扩围 + 负价下限调整使"
                 "峰谷价差双向放大，不能只看日均价。")
NOTE_POWER_EU = ("气电为欧洲边际定价机组，TTF → 批发电价近似完全传导；冬季合约对储气率与寒潮高度敏感。")
NOTE_COAL = "国内看“三西”安监与秦港库存，进口看印尼 HBA/RKAB 与纽卡斯尔；长协煤与现货价差决定电厂采购节奏。"

STYLE = """
:root{
  --ink:#0e1c2e; --ink2:#33485f; --mut:#6b7c91; --line:#e4e9f0; --bg:#eef2f6;
  --card:#ffffff; --navy:#0f2742; --navy2:#163a5f; --amber:#f59e0b;
  --up:#c0392b; --up-bg:#fdeceb; --up-bd:#f0b4ad;
  --dn:#15803d; --dn-bg:#eafaf0; --dn-bd:#a9ddbd;
  --flat:#5b6b7d; --flat-bg:#f1f4f8; --flat-bd:#d3dce6;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 font-size:15px;line-height:1.65}
a{color:#1d5fd0;text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1100px;margin:0 auto;padding:0 18px 60px}
header.hero{background:linear-gradient(135deg,var(--navy) 0%,var(--navy2) 60%,#1f5a86 100%);color:#fff;
 padding:30px 0 26px;margin-bottom:22px;box-shadow:0 2px 14px rgba(15,39,66,.25)}
.hero .wrap{padding-bottom:0}
.hero h1{margin:0 0 6px;font-size:26px;letter-spacing:.5px}
.hero .sub{opacity:.85;font-size:13.5px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.25);
 padding:4px 11px;border-radius:999px;font-size:12.5px}
.chip b{font-weight:700}
.firstrun{margin-top:12px;background:rgba(245,158,11,.18);border:1px solid rgba(245,158,11,.55);
 padding:7px 12px;border-radius:8px;font-size:13px}
h2{font-size:19px;margin:34px 0 14px;padding-left:11px;border-left:5px solid var(--amber);line-height:1.2}
h3{font-size:15.5px;margin:20px 0 9px;color:var(--ink)}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 15px 14px;
 box-shadow:0 1px 3px rgba(16,40,67,.06)}
.pcard .name{font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.pill{display:inline-block;padding:3px 11px;border-radius:999px;font-size:13px;font-weight:700;margin:10px 0 4px;border:1px solid transparent}
.score{font-size:27px;font-weight:800;line-height:1.1;margin:2px 0}
.score small{font-size:12px;font-weight:600;color:var(--mut);margin-left:3px}
.pn{font-size:12px;color:var(--mut);margin:3px 0 9px}
.bar{height:7px;border-radius:5px;background:var(--dn-bg);overflow:hidden;display:flex;margin-bottom:10px}
.bar i{display:block;height:100%}
.bar .u{background:var(--up)} .bar .d{background:var(--dn)}
.driver{font-size:12.5px;color:var(--ink2);border-top:1px dashed var(--line);padding-top:8px}
.s-up2{color:var(--up);background:var(--up-bg);border-color:var(--up-bd)}
.s-up1{color:var(--up);background:var(--up-bg);border-color:var(--up-bd)}
.s-flat{color:var(--flat);background:var(--flat-bg);border-color:var(--flat-bd)}
.s-dn1{color:var(--dn);background:var(--dn-bg);border-color:var(--dn-bd)}
.s-dn2{color:var(--dn);background:var(--dn-bg);border-color:var(--dn-bd)}
.t-up2{color:var(--up)} .t-up1{color:var(--up)} .t-flat{color:var(--flat)} .t-dn1{color:var(--dn)} .t-dn2{color:var(--dn)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden;
 box-shadow:0 1px 3px rgba(16,40,67,.06);font-size:14px}
th{background:var(--navy);color:#fff;text-align:left;padding:10px 12px;font-weight:600;font-size:13px}
td{padding:9px 12px;border-top:1px solid var(--line);vertical-align:top}
tr:nth-child(even) td{background:#fafbfd}
.up-txt{color:var(--up);font-weight:700} .dn-txt{color:var(--dn);font-weight:700}
.mut{color:var(--mut)}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:5px;background:#eef2f7;color:var(--ink2);margin-left:6px}
.factor{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:4px 16px 12px;margin-bottom:13px;
 box-shadow:0 1px 3px rgba(16,40,67,.06)}
.factor .hd{display:flex;flex-wrap:wrap;align-items:center;gap:9px;padding:12px 0;border-bottom:1px solid var(--line)}
.factor .hd .ft{font-weight:700;font-size:15px}
.badge{font-size:11.5px;padding:2px 9px;border-radius:6px;background:#e8eef6;color:var(--navy2);font-weight:600}
.cnt{font-size:12px;color:var(--mut)}
.cnt b.up{color:var(--up)} .cnt b.dn{color:var(--dn)}
ul.ev{list-style:none;margin:10px 0 4px;padding:0}
ul.ev li{padding:7px 0;border-bottom:1px dashed #edf1f5;font-size:13.8px}
ul.ev li:last-child{border-bottom:none}
.mk{font-weight:800;margin-right:6px}
.src{color:var(--mut);font-size:12px;margin-left:6px;white-space:nowrap}
.inv{color:var(--amber);font-size:12px;margin-left:6px}
details.other{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin-top:6px}
details.other summary{cursor:pointer;font-weight:600;color:var(--navy2)}
details.other ul{margin:10px 0 4px;padding-left:20px;font-size:13.5px}
details.other li{padding:3px 0}
.chain{background:#fbfcfe;border:1px solid var(--line);border-radius:10px;padding:6px 16px 12px;margin-bottom:14px}
.chiprow{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0 4px}
.dchip{font-size:12.5px;border-radius:8px;padding:4px 10px;border:1px solid;font-weight:600}
.dchip.up{color:var(--up);background:var(--up-bg);border-color:var(--up-bd)}
.dchip.dn{color:var(--dn);background:var(--dn-bg);border-color:var(--dn-bd)}
.chain p{margin:7px 0;font-size:13.8px}
.chain p b{color:var(--navy2)}
.note{border-left:3px solid var(--amber);background:#fff9ec;padding:8px 12px;border-radius:0 8px 8px 0;
 margin:8px 0;font-size:13.3px;color:#6b5318}
.scen{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.scen .sc{border-radius:12px;padding:14px 16px;border:1px solid;background:var(--card)}
.sc h4{margin:0 0 7px;font-size:14.5px}
.sc.base{border-color:#bcd2ec;background:linear-gradient(180deg,#f4f9ff,#fff)}
.sc.up{border-color:var(--up-bd);background:linear-gradient(180deg,#fff4f3,#fff)}
.sc.dn{border-color:var(--dn-bd);background:linear-gradient(180deg,#f2fbf5,#fff)}
.sc p{margin:0;font-size:13.3px;color:var(--ink2)}
.cal{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
 box-shadow:0 1px 3px rgba(16,40,67,.06)}
.cal .r{display:grid;grid-template-columns:180px 1fr;border-top:1px solid var(--line);font-size:13.6px}
.cal .r:first-child{border-top:none}
.cal .r .t{padding:10px 14px;font-weight:700;color:var(--navy2);background:#f7fafc;border-right:1px solid var(--line)}
.cal .r .v{padding:10px 14px;color:var(--ink2)}
.foot{margin-top:34px;font-size:12.8px;color:var(--mut)}
.foot .box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:12px}
.disc{background:#fff7ec;border:1px solid #f3d8a3;color:#7a5a17;border-radius:10px;padding:12px 16px;font-size:12.8px}
code{background:#eef2f7;padding:1px 6px;border-radius:4px;font-size:12px}
@media (max-width:860px){.cards{grid-template-columns:repeat(2,1fr)}.scen{grid-template-columns:1fr}.cal .r{grid-template-columns:1fr}.cal .r .t{border-right:none;border-bottom:1px solid var(--line)}}
@media print{body{background:#fff}header.hero{box-shadow:none}}
"""


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def safe_url(u: str) -> str:
    u = (u or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def render(ctx: dict) -> str:
    cn: datetime = ctx["cn_time"]
    temp = ctx["analysis"]["temperature"]
    sigs = ctx["analysis"]["signals"]
    news = ctx["news"]
    keys = ["oil", "gas", "coal", "power"]

    H: list[str] = []
    H.append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>")
    H.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    H.append(f"<title>能源电力市场监控日报 {cn.strftime('%Y-%m-%d')}</title>")
    H.append(f"<style>{STYLE}</style></head><body>")

    # ---------- Header ----------
    H.append("<header class='hero'><div class='wrap'>")
    H.append(f"<h1>能源电力市场监控日报 · {cn.strftime('%Y-%m-%d')}</h1>")
    H.append("<div class='sub'>原油 / 天然气 / 煤炭 / 电价 · 事件驱动的边际影响推演（中国 + 欧洲市场）</div>")
    H.append("<div class='chips'>")
    H.append(f"<span class='chip'>生成 <b>{cn.strftime('%H:%M')}</b>（北京）</span>")
    H.append(f"<span class='chip'>第 <b>{ctx['run_no']}</b> 期</span>")
    H.append("<span class='chip'>监控 <b>每 3 小时</b></span>")
    H.append(f"<span class='chip'>新增事件 <b>{news['new_count']}</b></span>")
    H.append(f"<span class='chip'>命中因子 <b>{ctx['analysis']['tagged_count']}</b></span>")
    H.append("</div>")
    if news["first_run"]:
        H.append("<div class='firstrun'>首期运行：事件池含人工核验基线（2026-09-20 前公开信息），此后仅展示监控到的增量信息。</div>")
    if ctx.get("fallback_window"):
        H.append("<div class='firstrun'>本周期无新增重大事件，下列信号基于近 24 小时存量资讯滚动分析。</div>")
    H.append("</div></header>")

    H.append("<div class='wrap'>")

    # ---------- 1 速览卡片 ----------
    H.append("<h2>一、四品种影响速览</h2>")
    H.append("<div class='cards'>")
    for k in keys:
        v = temp[k]
        cls, ar = SIG_META[v["label"]]
        tot = max(v["pos"] + v["neg"], 1)
        up_w, dn_w = v["pos"] / tot * 100, v["neg"] / tot * 100
        top = _top_driver(sigs, k)
        H.append("<div class='card pcard'>")
        H.append(f"<div class='name'><span class='dot' style='background:{_dotcolor(cls)}'></span>{e(v['name'])}</div>")
        H.append(f"<div><span class='pill {cls}'>{ar} {e(v['label'])}</span></div>")
        H.append(f"<div class='score {cls.split()[0].replace('s-','t-')}'>{v['score']}<small>边际评分</small></div>")
        H.append(f"<div class='pn'>利多 {v['pos']} 条 · 利空 {v['neg']} 条</div>")
        H.append("<div class='bar'>")
        if up_w:
            H.append(f"<i class='u' style='width:{up_w:.1f}%'></i>")
        if dn_w:
            H.append(f"<i class='d' style='width:{dn_w:.1f}%'></i>")
        H.append("</div>")
        H.append(f"<div class='driver'>核心驱动：{e(top)}</div>")
        H.append("</div>")
    H.append("</div>")
    H.append("<p class='mut' style='font-size:12.5px;margin-top:9px'>评分 = Σ（因子权重 × 历史影响强度 × 方向），同一因子只计一次；衡量本期新增事件的边际压力与集中度，非点位预测。红=利多/上涨，绿=利空/下跌。</p>")

    # ---------- 2 行情 ----------
    H.append("<h2>二、行情快照</h2>")
    H.append("<h3>2.1 国际期货与宏观（自动抓取）</h3>")
    H.append("<table><thead><tr><th>品种</th><th>最新价</th><th>日涨跌</th><th>单位</th><th>数据源</th><th>时间</th></tr></thead><tbody>")
    for p in ctx["prices"]:
        if p.get("value") is None:
            H.append(f"<tr><td>{e(p['name'])}</td><td class='mut'>抓取失败</td><td>—</td><td>{e(p['unit'])}</td><td colspan='2' class='mut'>见页脚错误日志</td></tr>")
            continue
        chg = _chg_cell(p.get("change_pct"))
        fb = "<span class='tag'>基线报价</span>" if p.get("fallback") else ""
        H.append(f"<tr><td>{e(p['name'])}{fb}</td><td><b>{p['value']}</b></td><td>{chg}</td>"
                 f"<td>{e(p['unit'])}</td><td>{e(p.get('source'))}</td><td class='mut'>{e(_short_ts(p.get('ts')))}</td></tr>")
    H.append("</tbody></table>")

    H.append("<h3>2.2 区域现货参考（新闻文本自动提取）</h3>")
    if ctx["spot"]:
        H.append("<table><thead><tr><th>基准</th><th>报价</th><th>单位</th><th>出处</th><th>时间</th></tr></thead><tbody>")
        for s in ctx["spot"]:
            u = safe_url(s.get("link"))
            ev = e(s["evidence"][:40])
            ev_html = f"<a href='{e(u)}' target='_blank' rel='noopener'>{ev}</a>" if u else ev
            H.append(f"<tr><td>{e(s['name'])}</td><td><b>{s['value']}</b></td><td>{e(s['unit'])}</td>"
                     f"<td>{e(s['source'])}：{ev_html}</td><td class='mut'>{e(s.get('published','')[:16])}</td></tr>")
        H.append("</tbody></table>")
    else:
        H.append("<div class='card mut' style='font-size:13.5px'>本期新闻文本未识别到结构化现货报价。</div>")

    # ---------- 3 事件 ----------
    H.append("<h2>三、本期重大事件（按影响因子分组）</h2>")
    if not sigs:
        H.append("<div class='card mut'>本期新增新闻未命中核心影响因子，可能以噪声 / 价格复述为主。</div>")
    for sg in sigs:
        H.append("<div class='factor'>")
        H.append("<div class='hd'>")
        H.append(f"<span class='ft'>{e(sg['name'])}</span>")
        H.append(f"<span class='badge'>{e(sg['category'])}</span>")
        if sg.get("structural"):
            H.append(f"<span class='cnt'>结构性变化 · {sg['neutral']+sg['up']+sg['down']} 条相关（不计多空评分）</span>")
        else:
            H.append("<span class='cnt'>对商品 <b class='up'>利多 %d</b> / <b class='dn'>利空 %d</b></span>" % (sg["up"], sg["down"]))
        H.append("</div><ul class='ev'>")
        for ev in sg["evidence"]:
            rd = ev.get("real_dir", 0)
            mk = {1: "<span class='mk up-txt'>▲</span>", -1: "<span class='mk dn-txt'>▼</span>"}.get(rd, "<span class='mk mut'>•</span>")
            u = safe_url(ev.get("link"))
            ttl = e(ev["title"])
            link = f"<a href='{e(u)}' target='_blank' rel='noopener'>{ttl}</a>" if u else ttl
            inv = f"<span class='inv'>反转信号：{e(ev['inverter'])}</span>" if ev.get("inverter") else ""
            H.append(f"<li>{mk}{link}<span class='src'>{e(ev.get('source'))} · {e(ev.get('published','')[:16])}</span>{inv}</li>")
        H.append("</ul></div>")

    other = [x for x in news["new_items"] if x.get("channel") != "seed"][:10]
    if other:
        H.append("<details class='other'><summary>其他能源相关资讯（点击展开）</summary><ul>")
        for it in other:
            u = safe_url(it.get("link"))
            ttl = e(it["title"])
            link = f"<a href='{e(u)}' target='_blank' rel='noopener'>{ttl}</a>" if u else ttl
            H.append(f"<li>{link} <span class='src'>{e(it.get('source'))}</span></li>")
        H.append("</ul></details>")

    # ---------- 4 传导 ----------
    H.append("<h2>四、事件 → 价格传导推演（基于历史经验矩阵）</h2>")
    for idx, k in enumerate(keys, 1):
        v = temp[k]
        cls, ar = SIG_META[v["label"]]
        drivers, channels, horizons = _driver_details(sigs, k)
        H.append("<div class='chain'>")
        H.append(f"<h3>4.{idx} {e(v['name'])} <span class='{cls.split()[0].replace('s-','t-')}' style='font-size:14px'>{ar} {e(v['label'])}</span> <span class='mut' style='font-size:12.5px'>（评分 {v['score']}）</span></h3>")
        if drivers:
            H.append("<div class='chiprow'>" + "".join(f"<span class='dchip {'up' if d[0]=='▲' else 'dn'}'>{e(d)}</span>" for d in drivers) + "</div>")
            for ch in channels[:4]:
                H.append(f"<p><b>传导逻辑：</b>{e(ch)}</p>")
            hz = "；".join(horizons[:3])
            if hz:
                H.append(f"<p><b>时滞 / 持续性：</b>{e(hz)}</p>")
        else:
            H.append("<p><b>本期驱动：</b>无显著新增冲击，价格沿存量主线（地缘溢价、季节性与政策预期）运行。</p>")
        if k == "power":
            H.append(f"<div class='note'>中国市场：{e(NOTE_POWER_CN)}</div>")
            H.append(f"<div class='note'>欧洲市场：{e(NOTE_POWER_EU)}</div>")
        if k == "coal":
            H.append(f"<div class='note'>{e(NOTE_COAL)}</div>")
        H.append("</div>")

    # ---------- 5 情景 + 日历 ----------
    H.append("<h2>五、综合研判与情景</h2>")
    geo_on = any(s["id"] == "middle_east" and s["direction"] > 0 for s in sigs)
    H.append("<div class='scen'>")
    if geo_on:
        rows = [
            ("base", "基准情景", "中东局势维持紧张但未进一步断航 → 油价维持地缘溢价、高位震荡；TTF / 欧洲电价易涨难跌；亚太煤价受气煤切换支撑，国内现货煤价随产地约束与补库延续偏强，电价情绪面向暖。"),
            ("up", "上行情景", "霍尔木兹通航进一步受阻或冲突外溢（袭击升级、制裁加码）→ 油气跳涨，煤炭被动跟涨，欧洲冬季电价与国内次年长协预期同步上修。"),
            ("dn", "下行情景", "停火 / 复航 / 谈判进展、OPEC+ 放量或战略储备投放 → 风险溢价快速回吐，气价弹性大于油价，高价煤回落，现货电价情绪转弱。"),
        ]
    else:
        strongest = max(temp.values(), key=lambda x: abs(x["score"]))
        rows = [
            ("base", "基准情景", f"无单一主导冲击，市场按库存 / 天气 / 宏观数据交易；当前边际最强品种为 {strongest['name']}（{strongest['label']}）。"),
            ("up", "上行情景", "库存超预期去化、寒潮/热浪或主要供给国产能事件 → 对应品种快速重新定价。"),
            ("dn", "下行情景", "需求预期下修、宏观转松或供给恢复 → 价格风险溢价回吐。"),
        ]
    for cls, ttl, body in rows:
        H.append(f"<div class='sc {cls}'><h4>{e(ttl)}</h4><p>{e(body)}</p></div>")
    H.append("</div>")

    H.append("<h3 style='margin-top:22px'>关注日历</h3><div class='cal'>")
    for t, v in CALENDAR:
        H.append(f"<div class='r'><div class='t'>{e(t)}</div><div class='v'>{e(v)}</div></div>")
    H.append("</div>")

    # ---------- 6 footer ----------
    H.append("<h2>六、运行信息与免责声明</h2><div class='foot'>")
    H.append("<div class='box'>")
    H.append(f"抓取条目：新增 <b>{news['new_count']}</b> / 近 24h 去重后 <b>{news['total_count']}</b>；未命中因子 {ctx['analysis']['untagged_count']} 条（仅资讯留存，不进评分）。<br>")
    H.append(f"数据源：Google / Bing News RSS（{len(ctx['config']['news']['google_news'])} 组关键词，中英文）、"
             f"公开 RSS {len(ctx['config']['news']['direct_feeds'])} 个、CNBC 行情（Yahoo 备用）。")
    if ctx["errors"]:
        H.append(f"<br>失败源（{len(ctx['errors'])}，已自动跳过）：<code>{e(' · '.join(ctx['errors'][:12]))}</code>")
    else:
        H.append("<br>本次所有数据源请求成功。")
    H.append("</div>")
    H.append("<div class='disc'><b>免责声明：</b>本报告由监控程序基于公开信息与预设的历史传导规则自动生成，仅供交易研究参考，<b>不构成任何投资建议</b>。"
             "规则方向为历史经验的统计性概括，单次事件的实际价格反应受仓位、预期差、政策干预与流动性影响，可能与历史规律偏离，请结合实时盘口独立决策。</div>")
    H.append("</div>")  # /foot

    H.append("</div></body></html>")
    return "".join(H)


def _dotcolor(cls: str) -> str:
    return {"s-up2": "var(--up)", "s-up1": "var(--up)", "s-flat": "var(--flat)",
            "s-dn1": "var(--dn)", "s-dn2": "var(--dn)"}.get(cls.split()[0], "var(--flat)")


def _chg_cell(chg):
    if chg is None:
        return "<span class='mut'>—</span>"
    cls = "up-txt" if chg > 0 else ("dn-txt" if chg < 0 else "mut")
    sign = "+" if chg > 0 else ""
    return f"<span class='{cls}'>{sign}{chg:.2f}%</span>"


def _short_ts(ts):
    if not ts:
        return "-"
    return str(ts).replace("T", " ")[:16]


def _top_driver(signals, ck):
    from .report import _top_driver as _td
    return _td(signals, ck)


def _driver_details(signals, ck):
    from .report import _driver_details as _dd
    return _dd(signals, ck)


def save(md_index_note: str, html: str, cn: datetime) -> dict:
    """写出发布站点：site/index.html、site/archive/YYYY-MM-DD.html、历史目录与 reports/latest.html。"""
    SITE.mkdir(parents=True, exist_ok=True)
    ARCHIVE_WEB.mkdir(parents=True, exist_ok=True)

    day = cn.strftime("%Y-%m-%d")
    (SITE / "index.html").write_text(html, encoding="utf-8")
    (ARCHIVE_WEB / f"{day}.html").write_text(html, encoding="utf-8")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "latest.html").write_text(html, encoding="utf-8")
    _rebuild_web_index()
    return {"site": "site/index.html", "day": f"site/archive/{day}.html"}


def _rebuild_web_index() -> None:
    files = sorted(ARCHIVE_WEB.glob("*.html"), reverse=True)
    H = ["<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width, initial-scale=1'>",
         "<title>日报归档 · 能源电力市场监控</title>", f"<style>{STYLE}</style></head><body>",
         "<header class='hero'><div class='wrap'><h1>日报归档</h1>",
         "<div class='sub'><a style='color:#cfe2f7' href='../index.html'>← 返回最新日报</a></div></div></header>",
         "<div class='wrap'><div class='card'><table><thead><tr><th>日期</th><th>链接</th></tr></thead><tbody>"]
    for f in files:
        H.append(f"<tr><td><b>{e(f.stem)}</b></td><td><a href='{e(f.name)}'>查看当日日报（日内滚动更新至最新一期）</a></td></tr>")
    H.append("</tbody></table></div></div></body></html>")
    (ARCHIVE_WEB / "index.html").write_text("".join(H), encoding="utf-8")
