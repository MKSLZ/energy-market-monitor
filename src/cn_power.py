"""国内电价（中国）专项推演：把国际油/气/煤价格与事件映射到国内电价。

机制锚点：
- 煤电是电量与边际定价主体（占发电量约六成），但长协煤约占电厂采购 80%，对冲掉大部分现货煤波动；
- 油电占比≈0，国际油价对国内上网电价几乎无直接传导；
- 气电占比约 3.5%，集中在沿海调峰，国际气价主要影响其在电力紧张时段的“尖峰边际成本”；
- 价格分四层：日前/实时现货（弹性最大）→ 月度中长期 → 次年年度长协（慢变量，受成本监审决定）→ 终端代理购电（滞后）。
所有“分/千瓦时”均为成本端推力测算（行业经验参数），非电价预测点位。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "config" / "cn_power.json"

# 与 impact_matrix 中影响国内电价最直接的因子
COAL_FACTORS = {"cn_coal_constraint", "indonesia_coal", "shipping_disruption"}
GAS_FACTORS = {"middle_east", "eu_gas_squeeze", "lng_outage", "russia_supply"}
DEMAND_FACTORS = {"heatwave", "cold_weather", "macro_demand"}
HYDRO_FACTORS = {"hydro_output"}
POLICY_UP = {"cn_power_price_policy"}
STRUCTURAL = {"spot_market_expand", "capacity_price", "negative_price_floor", "renewables_curtail"}

SPOT_MWH_RE = re.compile(
    r"(?:日前|实时|日内|现货)[^。；;，,]{0,18}?(?:均价|出清均价|出清价|平均价|加权价|成交价)[^。；;，,]{0,12}?"
    r"(?<![\d.])(\d{2,4}(?:\.\d{1,2})?)\s*元\s*/\s*兆瓦时"
)
ANNUAL_KWH_RE = re.compile(
    r"(?:年度长期|年度长协|年度交易|年度集中竞价|长协)[^。；;，,]{0,26}?"
    r"(?:成交均价|成交电价|成交价|均价|电价)[^。；;，,]{0,12}?"
    r"(?<![\d.])(0\.\d{2,4})\s*元\s*/\s*(?:千瓦时|千瓦|度)"
)


def load_cfg() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def _bracket(q5500: float | None, brackets: list[dict]) -> dict | None:
    if q5500 is None:
        return None
    for b in brackets:
        lo = b.get("min", -1e9)
        hi = b.get("max", 1e9)
        if lo <= q5500 < hi:
            return b
    return None


def _factor_map(signals: list[dict]) -> dict[str, dict]:
    return {s["id"]: s for s in signals}


def _extract_domestic_prices(items: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for it in items:
        text = f"{it['title']}。{it.get('summary','')}"
        for kind, rx, lo, hi, unit in (
            ("province_spot", SPOT_MWH_RE, 10, 1500, "元/兆瓦时"),
            ("annual_longterm", ANNUAL_KWH_RE, 0.20, 0.60, "元/千瓦时"),
        ):
            m = rx.search(text)
            if not m:
                continue
            try:
                val = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not (lo <= val <= hi):
                continue
            key = f"{kind}:{val}"
            out.setdefault(kind, {"value": val, "unit": unit, "evidence": it["title"],
                                  "source": it.get("source", ""), "published": it.get("published", "")})
    return list(out.values())


def build_view(prices: list[dict], spot: list[dict], signals: list[dict],
               temperature: dict, news_items: list[dict]) -> dict:
    cfg = load_cfg()
    cp = cfg["coal_power"]
    gp = cfg["gas_power"]
    fmap = _factor_map(signals)

    spot_by_id = {s["id"]: s for s in spot}

    def _meta(sid: str):
        r = spot_by_id.get(sid) or {}
        return r.get("value"), (r.get("published") or "")[:10], bool(r.get("_fresh", True))

    q5500, q_date, q_fresh = _meta("qhd5500")
    ttf, t_date, t_fresh = _meta("ttf")
    newcastle, n_date, _ = _meta("newcastle")

    def _cd(fid: str, ck: str) -> int:
        """因子 fid 对商品 ck 的实际多空方向：原始效应方向 × 叙事方向（含反转词）。"""
        s = fmap.get(fid)
        if not s:
            return 0
        eff = s.get("effects", {}).get(ck)
        if not eff or not eff.get("dir") or not eff.get("mag"):
            return 0
        return 1 if eff["dir"] * s.get("direction", 1) > 0 else -1

    def up(fid: str, ck: str) -> int:
        return 1 if _cd(fid, ck) > 0 else 0

    def down(fid: str, ck: str) -> int:
        return 1 if _cd(fid, ck) < 0 else 0

    # ---------- 煤：定价主体（成本端测算） ----------
    anchor = cp["longcontract_anchor_price"]
    ton_kwh = cp["ton_per_kwh"]
    mton_kwh = cp["marginal_ton_per_kwh"]
    lc_share = cp["longcontract_coal_share"]

    coal_block = {"q5500": q5500, "anchor": anchor, "bracket": None,
                  "q_date": q_date, "q_fresh": q_fresh,
                  "marginal_fuel_cost": None, "marginal_gap_fen": None,
                  "blended_gap_fen": None, "scenarios": []}
    if q5500 is not None:
        brk = _bracket(q5500, cfg["price_brackets_q5500"])
        coal_block["bracket"] = brk["label"] if brk else None
        coal_block["marginal_fuel_cost"] = round(q5500 * mton_kwh, 3)
        gap_ton = q5500 - anchor
        coal_block["marginal_gap_fen"] = round(gap_ton * mton_kwh * 100, 1)          # 边际煤机 vs 长协锚
        coal_block["blended_gap_fen"] = round((1 - lc_share) * gap_ton * ton_kwh * 100, 1)  # 综合电量(长协煤对冲后)
        for scen in (anchor, q5500, q5500 + 100):
            coal_block["scenarios"].append({
                "coal_price": round(scen),
                "marginal_fuel": round(scen * mton_kwh, 3),
                "blended_fuel": round((lc_share * anchor + (1 - lc_share) * scen) * ton_kwh, 3),
            })

    # 分时间维度的“成本推力”方向与幅度（分/千瓦时，相对长协煤锚）
    pt = cfg["pass_through"]
    base_gap = coal_block["marginal_gap_fen"] or 0.0
    coal_up = sum(up(f, "coal") for f in COAL_FACTORS)
    coal_dn = sum(down(f, "coal") for f in COAL_FACTORS)
    hydro_dn = sum(down(f, "power") for f in HYDRO_FACTORS)  # 丰水=空
    hydro_up = sum(up(f, "power") for f in HYDRO_FACTORS)    # 偏枯=多
    demand_up = sum(up(f, "power") for f in DEMAND_FACTORS)
    demand_dn = sum(down(f, "power") for f in DEMAND_FACTORS)
    policy_up = sum(up(f, "power") for f in POLICY_UP)
    gas_intl_up = any(_cd(f, "gas") > 0 for f in GAS_FACTORS)

    def _band(gap_fen: float, lo: float, hi: float):
        return (round(max(gap_fen, 0) * lo, 1), round(max(gap_fen, 0) * hi, 1))

    spot_b = _band(base_gap, *pt["day_ahead_spot"])
    month_b = _band(base_gap, *pt["monthly_medium_long"])
    year_b = _band(base_gap, *pt["annual_longterm_nextyear"])

    # ---------- 国内现货电价压力指数（0-100） ----------
    score = 0
    if q5500 is not None:
        brk = _bracket(q5500, cfg["price_brackets_q5500"])
        score += {0: 0, 1: 22, 2: 40, 3: 55}.get(brk["spot_pressure"] if brk else 0, 0)
    score += 10 * coal_up + 7 * demand_up + 7 * hydro_up + 12 * policy_up
    score += 8 if (ttf and ttf >= 60) else 0       # 高气价→沿海气电尖峰
    score -= 8 * coal_dn + 8 * demand_dn + 6 * hydro_dn
    score = max(0, min(100, score))
    if q5500 is None and score == 0:
        label = "信号不足·暂中性看待"
    else:
        label = ("上行压力强" if score >= 60 else "温和上行" if score >= 35 else
                 "多空平衡" if score >= 20 else "偏弱")

    # ---------- 天然气（只决定沿海尖峰，不主导综合电价） ----------
    gas_block = {
        "ttf": ttf, "ttf_date": t_date, "t_fresh": t_fresh,
        "gas_share": cfg["generation_mix"]["gas_share"],
        "gas_use_m3": gp["gas_use_m3_per_kwh"],
        "cost_per_1yuan": round(gp["gas_use_m3_per_kwh"] * 100, 1),  # 气价每涨1元/方→度电成本(分)
        "intl_up": gas_intl_up,
        "verdict": ("国际气价高位，沿海 LNG 现货电厂与顶峰气电变动成本抬升，在晚高峰/紧张时段推高尖峰电价；"
                    "但气电电量占比仅约3.5%且非沿海省份以长协气/保供气为主，对全国综合电价影响有限。")
        if (ttf and ttf >= 60) or gas_intl_up else
        "国际气价温和，沿海气电尖峰成本无显著额外推力。",
    }

    # ---------- 石油（几乎无直接传导） ----------
    oil_price = next((p["value"] for p in prices if "Brent" in p["name"] and p.get("value")), None)
    oil_block = {
        "brent": oil_price, "oil_share": cfg["generation_mix"]["oil_share"],
        "verdict": ("中国石油发电占比≈0，国际油价不直接进入上网电价；主要通过运输/化工成本与输入性 PPI 间接影响，"
                    "且成品油由发改委调价机制平滑。对国内电价的直接影响可忽略，仅作为宏观通胀与情绪变量。"),
    }

    # ---------- 结构性政策提示 ----------
    struct_notes = []
    name_map = {s["id"]: s for s in signals}
    for fid, note_key in (
        ("cn_power_price_policy", "anti_involution"),
        ("capacity_price", "coal_capacity_price"),
        ("negative_price_floor", None),
        ("spot_market_expand", "spot_2027"),
        ("renewables_curtail", "doc_136"),
    ):
        if fid in name_map:
            if note_key and note_key in cfg["mechanism"]:
                struct_notes.append(cfg["mechanism"][note_key])
    # 136/容量电价即便没有新新闻也固定提示一次（长期机制）
    for k in ("doc_136", "coal_capacity_price", "spot_2027"):
        if cfg["mechanism"][k] not in struct_notes:
            struct_notes.append(cfg["mechanism"][k])

    horizons = [
        {"key": "day_ahead_spot", "name": "日前 / 实时现货",
         "dir": _dir(base_gap, coal_up + demand_up, coal_dn + demand_dn + hydro_dn, strong=True),
         "push_fen": spot_b,
         "note": "边际煤机/气电报价主导，成本与供需几乎即时反映；当前燃料成本端推力最大，但实际出清还取决于新能源出力与负荷。"},
        {"key": "monthly", "name": "月度中长期",
         "dir": _dir(base_gap, coal_up, coal_dn + hydro_dn),
         "push_fen": month_b,
         "note": "中长期合约对冲掉部分燃料波动，方向跟随但幅度约为现货的一半。"},
        {"key": "annual_nextyear", "name": "次年(2027)年度长协",
         "dir": "上行" if policy_up or (q5500 and q5500 >= 850) else "中性",
         "push_fen": year_b,
         "note": "慢变量，由全年煤价中枢+成本监审/反内卷决定；高煤价年份后年度长协中枢通常上修（2026Q2已现约+1.1分/千瓦时改善）。"},
        {"key": "retail", "name": "终端工商业(代理购电)",
         "dir": "滞后上行" if (base_gap > 0 or policy_up) else "基本平稳",
         "push_fen": None,
         "note": "滞后发电侧约1-2个月，并叠加容量电价补偿、系统调节与输配费用。"},
    ]

    domestic_quotes = _extract_domestic_prices(news_items)

    q_when = f"{q_date}报价" if q_date else "最近一期报价"
    q_lead = "当前秦港Q5500约" if q_fresh else f"沿用{q_when}，秦港Q5500约"
    summary = (
        f"国内电价以煤为锚：{q_lead} {q5500:.0f} 元/吨（{coal_block['bracket']}），"
        f"较长协锚 {anchor:.0f} 元高 {q5500-anchor:.0f} 元，边际煤机燃料成本端压力约 "
        f"{coal_block['marginal_gap_fen']:.0f} 分/千瓦时；经长协煤（约{int(lc_share*100)}%）对冲后，"
        f"综合上网电量成本压力约 {coal_block['blended_gap_fen']:.1f} 分/千瓦时。"
        "国际油价对国内电价几乎无直接影响，国际气价主要推沿海尖峰。"
        + ("" if q_fresh else "（本期未抓到新煤价，采用 TTL 内最近值，方向判断仍有效、幅度需以最新报价校准）")
    ) if q5500 is not None else (
        "本期及近10日均未取到秦港Q5500报价，国内电价以信号方向定性判断：煤价/政策是核心变量，"
        "国际油气直接传导有限。"
    )

    return {
        "score": score, "label": label,
        "coal": coal_block, "gas": gas_block, "oil": oil_block,
        "horizons": horizons,
        "regions": cfg["regional"],
        "indicators": cfg["indicators"],
        "struct_notes": struct_notes[:4],
        "domestic_quotes": domestic_quotes,
        "summary": summary,
        "params": {"coal_share": cfg["generation_mix"]["coal_share"],
                   "gas_share": cfg["generation_mix"]["gas_share"],
                   "oil_share": cfg["generation_mix"]["oil_share"],
                   "newcastle": newcastle, "newcastle_date": n_date},
    }


def _dir(gap: float, ups: int, dns: int, strong: bool = False) -> str:
    if gap > 0 and ups >= dns:
        return "上行"
    if gap > 0:
        return "温和上行"
    if ups > dns:
        return "温和上行"
    if dns > ups:
        return "偏弱"
    return "中性"
