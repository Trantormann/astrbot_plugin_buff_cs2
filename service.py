"""业务组装：搜索匹配商品、构建查询结果与同品类关注清单。"""
from __future__ import annotations

import asyncio
from typing import Any

from . import analysis
from .buff_client import BuffClient, BuffError
from .parser import WEAR_ORDER, extract_wear_from_name


# ------------------------- 搜索匹配 -------------------------

async def _search_suggest_with_fallback(client: BuffClient, query: str, skin: str) -> list:
    """先按「枪名+皮肤」搜索，失败再退化为纯皮肤名搜索。"""
    sugs = await client.search_suggest(query)
    if not sugs:
        sugs = await client.search_suggest(skin)
    return sugs


def _parse_suggestions(suggestions: list) -> list[dict]:
    """把 suggest 结果归一化为 [{name, goods_id, wear, stat}]。"""
    cands = []
    seen = set()
    for sug in suggestions:
        option = sug.get("option") or ""
        gid = str(sug.get("goods_ids") or "").strip()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        wear = extract_wear_from_name(option)
        cands.append(
            {
                "name": option,
                "goods_id": gid,
                "wear": wear,
                "stat": "stattrak" in option.lower(),
            }
        )
    return cands


async def resolve_goods(
    client: BuffClient,
    weapon_name: str,
    skin: str,
    wear: str | None,
    stat_trak: bool = False,
):
    """解析出目标 goods_id。

    返回 (kind, payload)：
      kind="ok"        -> payload=goods_id
      kind="wear_list" -> payload=[{wear, goods_id, price, name}, ...]（需用户补磨损）
      kind="not_found" -> payload=错误提示 str
    """
    query = f"{weapon_name} {skin}".strip() if weapon_name else skin
    suggestions = await _search_suggest_with_fallback(client, query, skin)
    if not suggestions:
        return (
            "not_found",
            "没找到匹配的商品。换个关键词试试，例如 /buff ak 燃料喷射器 久经",
        )

    cands = _parse_suggestions(suggestions)
    if not cands:
        return ("not_found", "解析搜索结果失败，换个关键词试试")

    def _pick(items: list) -> list:
        """按是否 StatTrak 过滤；目标版本不存在时回退为其他版本。"""
        want = [c for c in items if c["stat"] == stat_trak]
        return want if want else items

    if wear:
        exact = _pick([c for c in cands if c["wear"] == wear])
        if exact:
            return ("ok", exact[0]["goods_id"])
        # 指定磨损没匹配到 -> 列出实际可选的磨损
        return await _build_wear_list(client, cands, query, stat_trak)

    # 未指定磨损
    wears = {c["wear"] for c in cands if c["wear"]}
    if len(wears) == 1 and None not in [c["wear"] for c in cands]:
        return ("ok", _pick(cands)[0]["goods_id"])
    return await _build_wear_list(client, cands, query, stat_trak)


async def _build_wear_list(client: BuffClient, cands: list, query: str, stat_trak: bool = False):
    """构建磨损候选列表（优先取目标版本，目标版本不存在时回退普通版，并抓底价）。"""
    picked: dict[str, dict] = {}
    for c in cands:
        if not c["wear"] or c["wear"] in picked:
            continue
        if c["stat"] == stat_trak:
            picked[c["wear"]] = {"wear": c["wear"], "goods_id": c["goods_id"], "name": c["name"]}
    if not picked:
        for c in cands:
            if not c["wear"] or c["wear"] in picked:
                continue
            picked[c["wear"]] = {"wear": c["wear"], "goods_id": c["goods_id"], "name": c["name"]}
    result = []
    for w in WEAR_ORDER:
        if w in picked:
            info = await client.get_goods_info(picked[w]["goods_id"])
            result.append(
                {
                    "wear": w,
                    "goods_id": picked[w]["goods_id"],
                    "price": info.get("sell_min_price"),
                    "name": info.get("name") or picked[w]["name"],
                }
            )
    if not result:
        return ("not_found", f"没找到「{query}」对应的磨损版本，换个关键词试试")
    return ("wear_list", result)


# ------------------------- 消息一：基础信息 + 走势 -------------------------

async def fetch_price_message(client: BuffClient, goods_id: str) -> dict:
    """抓取并组装消息一。返回 {"text", "image_url"}。"""
    info = await client.get_goods_info(goods_id)
    goods_info = info.get("goods_info") or {}
    gi_info = goods_info.get("info") or {}
    name = info.get("name") or "未知商品"
    sell_min = info.get("sell_min_price")
    buy_max = info.get("buy_max_price")
    steam_price = info.get("steam_price_cny")
    icon_url = (
        goods_info.get("original_icon_url")
        or goods_info.get("icon_url")
        or ""
    )
    tags = gi_info.get("tags") or {}
    type_tag = tags.get("type") or {}
    weapon = tags.get("weapon") or {}
    exterior = tags.get("exterior") or {}

    lines = [f"【{name}】"]
    if weapon.get("localized_name"):
        lines.append(f"武器：{weapon.get('localized_name')}")
    if "stattrak" in (info.get("name") or "").lower():
        lines.append("版本：StatTrak™ 计数器")

    # 在售最低
    if sell_min is not None:
        lines.append(f"在售最低：¥{float(sell_min):,.2f}")
    else:
        lines.append("在售最低：暂无人挂单")
    # 求购
    try:
        buy_orders = await client.get_buy_orders(goods_id)
    except BuffError:
        buy_orders = []
    if buy_max is not None and float(buy_max) > 0:
        lines.append(f"最高求购：¥{float(buy_max):,.2f}（{len(buy_orders)} 个求购单）")
    else:
        lines.append("最高求购：暂无人求购")
    if steam_price:
        lines.append(f"Steam 参考价：¥{float(steam_price):,.2f}")

    # 走势
    try:
        history = await client.get_price_history(goods_id, days=30)
        trend = analysis.summarize_trend(history)
        lines.append("")
        lines.append(trend["text"])
    except BuffError as e:
        lines.append("")
        lines.append(f"走势获取失败：{e}")

    return {"text": "\n".join(lines), "image_url": icon_url, "type_internal": type_tag.get("internal_name") or ""}


# ------------------------- 消息二：同品类关注清单 -------------------------

async def fetch_category_attention(
    client: BuffClient,
    type_internal: str,
    scan_num: int,
    progress_cb=None,
) -> list | None:
    """扫描同品类，返回排序后的推荐清单（取前三），非武器返回 None。

    每项: {name, wear, price, sp, sticker_total, charm_value, order_price, goods_id}
    """
    category_group = analysis.WEAPON_CATEGORY_GROUP.get(type_internal)
    if not category_group:
        return None

    try:
        items = await client.get_category_goods(category_group, page_num=1, page_size=scan_num)
    except BuffError:
        return []

    results = []
    total = len(items)
    for idx, it in enumerate(items, start=1):
        gid = it.get("id")
        if not gid:
            continue
        try:
            base = float(it.get("sell_min_price") or 0)
        except (TypeError, ValueError):
            base = 0.0
        if progress_cb:
            ret = progress_cb(idx, total, it.get("name") or "")
            if asyncio.iscoroutine(ret):
                await ret
        try:
            orders = await client.get_sell_orders(gid)
        except BuffError:
            orders = []
        best = analysis.best_sp_for_orders(orders, base)
        itags = ((it.get("goods_info") or {}).get("info") or {}).get("tags") or {}
        results.append(
            {
                "name": it.get("name") or "",
                "goods_id": gid,
                "wear": (itags.get("exterior") or {}).get("localized_name"),
                "price": base,
                "sp": best["sp"] if best else None,
                "sticker_total": best["sticker_total"] if best else 0.0,
                "charm_value": best["charm_value"] if best else 0.0,
                "order_price": best["price"] if best else None,
            }
        )
    ranked = analysis.rank_category_items(results)
    return ranked[:3]


def format_attention_text(category_group: str, top3: list) -> str:
    """把推荐清单渲染为消息二文本。"""
    cn = analysis.CATEGORY_GROUP_CN.get(category_group, category_group)
    if not top3:
        return f"{cn}类目下暂无可推荐的商品。"
    lines = [f"【{cn}类 · 值得关注 Top 3】", ""]
    for i, item in enumerate(top3, start=1):
        name = item["name"] or "未知"
        wear = item.get("wear")
        if wear and wear not in name:
            name = f"{name}（{wear}）"
        sp = item.get("sp")
        lines.append(f"{i}. {name}")
        try:
            lines.append(f"   底价 ¥{float(item['price']):,.2f}")
        except (TypeError, ValueError):
            lines.append("   底价 -")
        if sp is not None:
            lines.append(f"   印花溢价 SP {sp:+.1f}%（印花总价 ¥{item['sticker_total']:,.2f}）")
        else:
            lines.append("   无印花（普通低磨损底价件）")
    return "\n".join(lines)
