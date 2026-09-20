"""事件分类 + 传导分析引擎（规则驱动，可选 LLM 增强）。

规则：新闻文本命中 impact_matrix 主题关键词 -> 判定方向（inverters 反转）->
按 主题权重×影响强度×方向 汇总到油/气/煤/电四品种，生成市场温度与推演依据。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MATRIX_PATH = ROOT / "config" / "impact_matrix.json"

COMMODITIES = [
    ("oil", "原油"),
    ("gas", "天然气"),
    ("coal", "煤炭"),
    ("power", "电力"),
]


def load_matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def classify(text: str, themes: list[dict]) -> list[dict]:
    """返回文本命中的主题及其方向乘数（-1 表示命中反向词）。"""
    hits = []
    low = text.lower()
    for th in themes:
        kws = [k.lower() for k in th.get("keywords", [])]
        if not any(k in low for k in kws):
            continue
        mult = 1
        matched_inverter = ""
        for inv in th.get("inverters", []):
            if inv.lower() in low:
                mult = -1
                matched_inverter = inv
                break
        hits.append({"id": th["id"], "name": th["name"], "mult": mult, "inverter": matched_inverter})
    return hits


def analyze(news_items: list[dict], matrix: dict, new_hashes: set | None = None) -> dict:
    """对给定事件窗口做因子归类与评分。

    news_items 为参与评分的事件窗口（近 24h 滚动窗口 → 市场态势；或仅本周期新增 → 边际）。
    new_hashes 非空时，用于在证据上标注哪些属于“本周期新增”（new=True）。
    """
    new_hashes = new_hashes or set()
    themes = matrix["themes"]
    theme_by_id = {t["id"]: t for t in themes}

    theme_agg: dict[str, dict] = {}
    pos_events = {k: 0 for k, _ in COMMODITIES}
    neg_events = {k: 0 for k, _ in COMMODITIES}

    tagged_count = 0
    for item in news_items:
        text = f"{item['title']} {item.get('summary', '')}"
        hits = classify(text, themes)
        if not hits:
            continue
        tagged_count += 1
        for h in hits:
            th = theme_by_id[h["id"]]
            non_zero_dirs = [e["dir"] for e in th["effects"].values() if e.get("dir") and e.get("mag")]
            native = non_zero_dirs[0] if non_zero_dirs and all(d == non_zero_dirs[0] for d in non_zero_dirs) else 0
            agg = theme_agg.setdefault(
                h["id"],
                {"id": h["id"], "name": th["name"], "category": th["category"],
                 "up": 0, "down": 0, "neutral": 0, "structural": native == 0,
                 "mup": 0, "mdown": 0,
                 "evidence": [], "effects": th["effects"], "weight": th["weight"]},
            )
            if h["mult"] > 0:
                agg["mup"] += 1
            else:
                agg["mdown"] += 1
            real_dir = native * h["mult"]
            if real_dir > 0:
                agg["up"] += 1
            elif real_dir < 0:
                agg["down"] += 1
            else:
                agg["neutral"] += 1
            if len(agg["evidence"]) < 12:
                agg["evidence"].append(
                    {"title": item["title"], "link": item.get("link", ""),
                     "source": item.get("source", ""), "mult": h["mult"], "real_dir": real_dir,
                     "inverter": h["inverter"], "published": item.get("published", ""),
                     "new": item.get("hash") in new_hashes}
                )
            for ck, _ in COMMODITIES:
                eff = th["effects"].get(ck, {"dir": 0, "mag": 0})
                if eff["dir"] == 0 or eff["mag"] == 0:
                    continue
                if h["mult"] * eff["dir"] > 0:
                    pos_events[ck] += 1
                else:
                    neg_events[ck] += 1

    # direction：主题叙事方向（标准叙事 vs 反转叙事），供打分使用；up/down 为对商品的实际多空计数
    for agg in theme_agg.values():
        agg["direction"] = 1 if agg["mup"] >= agg["mdown"] else -1
        # 证据精选：本周期新增(new)优先，其次时间倒序；确保最新边际驱动（含利空反转）不被旧证据淹没
        agg["evidence"].sort(key=lambda e: (bool(e.get("new")), e.get("published", "")), reverse=True)
        agg["evidence"] = agg["evidence"][:6]

    signals = sorted(
        theme_agg.values(),
        key=lambda a: (a["up"] + a["down"], abs(a["up"] - a["down"])),
        reverse=True,
    )

    # 打分：同一因子（主题）只计一次，权重×历史强度×综合方向；避免同事件簇多篇报道重复放大
    scores = {k: 0.0 for k, _ in COMMODITIES}
    for agg in signals:
        for ck, _ in COMMODITIES:
            eff = agg["effects"].get(ck, {"dir": 0, "mag": 0})
            if eff["dir"] == 0 or eff["mag"] == 0:
                continue
            scores[ck] += agg["weight"] * eff["mag"] * eff["dir"] * agg["direction"]

    temperature = {}
    for ck, cn in COMMODITIES:
        temperature[ck] = {
            "name": cn,
            "score": round(scores[ck], 1),
            "label": _label(scores[ck]),
            "pos": pos_events[ck],
            "neg": neg_events[ck],
        }

    return {
        "signals": signals,
        "temperature": temperature,
        "tagged_count": tagged_count,
        "untagged_count": len(news_items) - tagged_count,
    }


def _label(score: float) -> str:
    if score >= 12:
        return "强烈看涨"
    if score >= 5:
        return "偏强"
    if score > -5:
        return "中性（多空交织）"
    if score > -12:
        return "偏弱"
    return "强烈看弱"


def extract_spot_prices(news_items: list[dict], patterns_cfg: list[dict]) -> list[dict]:
    """从新闻文本中提取现货/区域基准报价（带来源证据）。"""
    found = {}
    for item in news_items:
        text = f"{item['title']}。{item.get('summary', '')}"
        for sp in patterns_cfg:
            for pat in sp["patterns"]:
                m = re.search(pat, text)
                if m:
                    val = m.group(m.lastindex)
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        continue
                    # 合理性过滤
                    if not (5 < val < 5000):
                        continue
                    cur = found.get(sp["id"])
                    if cur is None or item.get("published", "") >= cur["published"]:
                        found[sp["id"]] = {
                            "id": sp["id"], "name": sp["name"], "unit": sp["unit"],
                            "value": val, "evidence": item["title"],
                            "source": item.get("source", ""), "published": item.get("published", ""),
                            "link": item.get("link", ""),
                        }
                    break
    return list(found.values())


def llm_commentary(analysis: dict, news_items: list[dict], prices: list[dict]) -> str | None:
    """可选：OpenAI 兼容接口生成综合研判。需要 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。"""
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    temp_lines = [f"- {v['name']}：{v['label']}（评分{v['score']}，利多{v['pos']}/利空{v['neg']}条）"
                  for v in analysis["temperature"].values()]
    headlines = "\n".join(f"- {x['title']}（{x.get('source','')}）" for x in news_items[:25])
    price_lines = [f"- {p['name']}: {p.get('value')} {p['unit']}" for p in prices if p.get("value")]

    prompt = f"""你是能源电力交易主管。基于以下机器监控信息，输出 250-400 字中文\"综合研判\"，
要求：1) 区分原油/天然气/煤炭/电力（含中国与欧洲市场差异）；2) 说明核心驱动与传导链条；
3) 给出未来3小时-3个交易日的关注点与上下行风险；4) 不做确定性投资承诺，措辞专业克制。

【行情】
{chr(10).join(price_lines)}

【机器信号】
{chr(10).join(temp_lines)}

【新闻标题】
{headlines}
"""
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.4, "max_tokens": 800},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return None
