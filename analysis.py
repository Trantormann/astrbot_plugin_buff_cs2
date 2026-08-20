"""价格走势总结、印花溢价率(SP%)计算与购买建议。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# 商品 type 内部名 -> BUFF 品类过滤名（category_group）
WEAPON_CATEGORY_GROUP = {
    "csgo_type_rifle": "rifle",
    "csgo_type_pistol": "pistol",
    "csgo_type_smg": "smg",
    "csgo_type_shotgun": "shotgun",
    "csgo_type_machinegun": "machinegun",
    "csgo_type_knife": "knife",
    "csgo_type_hands": "hands",
}

CATEGORY_GROUP_CN = {
    "rifle": "步枪",
    "pistol": "手枪",
    "smg": "微型冲锋枪",
    "shotgun": "霰弹枪",
    "machinegun": "机枪",
    "knife": "匕首",
    "hands": "手套",
}

WEAR_ORDER = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]


def extract_stickers(asset_info: dict) -> list:
    """从挂单 asset_info 中提取印花列表。"""
    info = (asset_info or {}).get("info") or {}
    return info.get("stickers") or []


def extract_charms(asset_info: dict) -> list:
    """从挂单 asset_info 中提取挂件（CS2 钥匙扣）列表。"""
    info = (asset_info or {}).get("info") or {}
    return info.get("charms") or info.get("keychains") or []


def _sum_reference_price(items: list) -> float:
    total = 0.0
    for it in items:
        try:
            total += float(it.get("sell_reference_price") or 0)
        except (TypeError, ValueError):
            pass
    return total


def compute_sp(order_price: float, base_price: float, charm_value: float, sticker_total: float) -> float | None:
    """印花溢价率 SP% = (出售价格 - 区间底价 - 挂件价格) / 印花总价。

    无印花时返回 None（除数 0）。
    """
    if not sticker_total or sticker_total <= 0:
        return None
    return (order_price - base_price - charm_value) / sticker_total * 100.0


def best_sp_for_orders(orders: list, base_price: float) -> dict | None:
    """从挂单列表中找出 SP 最低的印花单。

    返回 {"sp", "sticker_total", "charm_value", "price", "order"} 或 None。
    """
    best = None
    for order in orders or []:
        stickers = extract_stickers(order.get("asset_info"))
        if not stickers:
            continue
        sticker_total = _sum_reference_price(stickers)
        charm_value = _sum_reference_price(extract_charms(order.get("asset_info")))
        try:
            price = float(order.get("price"))
            base = float(base_price)
        except (TypeError, ValueError):
            continue
        sp = compute_sp(price, base, charm_value, sticker_total)
        if sp is None:
            continue
        if best is None or sp < best["sp"]:
            best = {
                "sp": sp,
                "sticker_total": sticker_total,
                "charm_value": charm_value,
                "price": price,
                "order": order,
            }
    return best


def summarize_trend(points: list) -> dict:
    """30 天在售最低价走势总结，返回文本（含购买建议）。"""
    if not points or len(points) < 2:
        return {
            "text": "近 30 天价格数据不足，暂时无法判断走势。",
            "advice": "数据有限，建议多观察几天再决定。",
        }
    try:
        prices = [float(p[1]) for p in points]
    except (TypeError, ValueError):
        return {"text": "价格数据异常，无法分析走势。", "advice": "建议稍后再试。"}

    start, end = prices[0], prices[-1]
    pmin, pmax = min(prices), max(prices)
    change = (end - start) / start * 100.0 if start else 0.0
    recent = prices[-7:] if len(prices) >= 7 else prices
    recent_change = (recent[-1] - recent[0]) / recent[0] * 100.0 if recent and recent[0] else 0.0

    def _fmt_price(v: float) -> str:
        return f"¥{v:,.2f}" if v >= 1 else f"¥{v:.3f}"

    lines = []
    lines.append(f"近30天走势：起点 {_fmt_price(start)} → 现 {_fmt_price(end)}（{change:+.1f}%）")
    lines.append(f"30天最低 {_fmt_price(pmin)} / 最高 {_fmt_price(pmax)}，近7天 {recent_change:+.1f}%")

    near_low = end <= pmin * 1.02
    near_high = end >= pmax * 0.98

    if change <= -5:
        advice = "整体走低，还没止跌迹象，建议再观望，别急着接刀。"
    elif change >= 8:
        advice = "近期涨了不少，追高风险大，等回调到均线附近再考虑。"
    elif change >= 3:
        advice = "温和上涨中，有货可以拿着，想补仓等小回调。"
    elif change <= -3:
        advice = "小幅下行，可挂低价求购慢慢收，别按在售价追。"
    else:
        advice = "价格平稳，想入手就挂求购价慢慢收，别追高。"
    if near_low and change <= 0:
        advice += " 当前接近30天低点，性价比不错。"
    elif near_high and change >= 0:
        advice += " 当前处于30天高位，谨慎追涨。"

    lines.append("建议：" + advice)
    return {"text": "\n".join(lines), "advice": advice}


def rank_category_items(items: list) -> list:
    """同品类商品排序：低SP(<30%)最优先 -> 低价格 -> 低磨损。"""
    def _wear_rank(wear: str | None) -> int:
        try:
            return WEAR_ORDER.index(wear)
        except (ValueError, TypeError):
            return len(WEAR_ORDER)

    def _key(item: dict):
        sp = item.get("sp")
        if sp is None:
            sp_cat, sp_val = 2, float("inf")
        elif sp < 30:
            sp_cat, sp_val = 0, sp
        else:
            sp_cat, sp_val = 1, sp
        try:
            price = float(item.get("price") or float("inf"))
        except (TypeError, ValueError):
            price = float("inf")
        return (sp_cat, sp_val, price, _wear_rank(item.get("wear")))

    return sorted(items, key=_key)
