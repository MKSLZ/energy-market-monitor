"""现货报价跨期持久化。

国内煤价 / 区域现货等无稳定免费接口，依赖新闻文本正则提取，单一 3 小时窗口可能恰好
没有带明确报价的报道。这里把每期提取到的报价写入 data/spot_state.json，后续各期沿用
最近一次（TTL 内）的值，避免国内电价推演因“某期没抓到数字”而归零；沿用值会被标注
为非当期（_fresh=False）及报价日期，供渲染层提示口径。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "spot_state.json"
CN_TZ = timezone(timedelta(hours=8))
TTL_DAYS = 10
_FIELDS = ("id", "name", "unit", "value", "evidence", "source", "published", "link")


def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s)[:25])
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=CN_TZ)


def merge(fresh: list[dict], now: datetime) -> list[dict]:
    """合并当期报价到状态，返回 TTL 内的有效报价列表（带 _fresh 标志）。"""
    state = _load()
    for f in fresh:
        state[f["id"]] = {k: f.get(k) for k in _FIELDS}

    effective: list[dict] = []
    kept: dict[str, dict] = {}
    for sid, rec in state.items():
        dt = _parse_dt(rec.get("published"))
        if dt is not None and now - dt.astimezone(CN_TZ) > timedelta(days=TTL_DAYS):
            continue  # 过期丢弃
        rec = dict(rec)
        rec["_fresh"] = sid in {x["id"] for x in fresh}
        effective.append(rec)
        kept[sid] = {k: rec.get(k) for k in _FIELDS}

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return effective
