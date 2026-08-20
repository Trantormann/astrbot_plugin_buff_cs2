"""CS 饰品 - BUFF 平台商品询价（AstrBot 插件）。

指令：
  /buff [枪名] [皮肤名] [磨损]
  /buff ak 燃料喷射器 久经
  /buff AK-47 燃料喷射器 fn
"""
from __future__ import annotations

import asyncio
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message import Image, MessageChain, Plain
from astrbot.api.star import Context, Star, filter, register

from .analysis import WEAPON_CATEGORY_GROUP
from .buff_client import BuffClient, BuffError
from .parser import parse_command
from .service import fetch_category_attention, fetch_price_message, format_attention_text, resolve_goods

HELP_TEXT = (
    "用法：/buff [枪名] [皮肤名] [磨损]\n"
    "例子：/buff ak 燃料喷射器 久经\n"
    "      /buff awp 二西莫夫\n"
    "磨损可写：崭新/fn、略有/mw、久经/ft、破损/ww、战痕/bs，不写则列出全部磨损\n"
    "武器类会自动追加同品类最值得关注的三件物品（低印花溢价优先）"
)


@register(
    "astrbot_plugin_buff_cs2",
    "CS 饰品 - BUFF 平台商品询价",
    "查询 CS2 饰品价格 / 走势 / 同品类值得关注商品",
    version="0.1.0",
    author="Trantormann",
)
class BuffPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context, config)
        self._client: BuffClient | None = None
        self._cooldowns: dict[str, float] = {}
        self._scan_cache: dict[str, tuple] = {}

    # ---------------- 基础工具 ----------------

    def _get_client(self) -> BuffClient:
        if self._client is None:
            self._client = BuffClient(
                cookie=self.config.get("buff_cookie", ""),
                request_delay=self.config.get("request_delay", 0.8),
                max_retries=self.config.get("max_retries", 3),
            )
        return self._client

    def _check_cooldown(self, sender_id: str) -> int:
        """返回需等待的秒数，0 表示可查询。"""
        cd = int(self.config.get("cooldown_seconds", 5))
        now = time.time()
        last = self._cooldowns.get(sender_id, 0.0)
        wait = int(cd - (now - last)) + 1
        if wait > 0 and last != 0.0:
            return wait
        self._cooldowns[sender_id] = now
        return 0

    async def terminate(self):
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass

    # ---------------- 指令 ----------------

    @filter.command("buff")
    async def buff(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        for prefix in ("/buff", "buff"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        if not text:
            yield event.plain_result(HELP_TEXT)
            return

        sender = event.get_sender_id() or "0"
        wait = self._check_cooldown(sender)
        if wait:
            yield event.plain_result(f"查询太快啦，{wait} 秒后再试喵")
            return

        parsed = parse_command(text)
        if parsed.error:
            yield event.plain_result(parsed.error)
            return

        client = self._get_client()
        if not client.has_cookie:
            yield event.plain_result(
                "还没配置 BUFF Cookie：请在插件配置里填写 buff_cookie（buff.163.com 的 session 值）后再查询。"
            )
            return

        # 1. 解析出 goods_id（或列出磨损让用户选）
        try:
            kind, payload = await resolve_goods(client, parsed.weapon_name, parsed.skin, parsed.wear)
        except BuffError as e:
            yield event.plain_result(f"查询出错：{e}")
            return
        except Exception as e:
            logger.error(f"[buff_cs2] resolve_goods 异常: {e}")
            yield event.plain_result("查询时出了点问题，稍后再试喵")
            return

        if kind == "not_found":
            yield event.plain_result(str(payload))
            return

        if kind == "wear_list":
            lines = [f"找到「{parsed.weapon_name} {parsed.skin}」的以下磨损，带上磨损再查一次喵：", ""]
            for i, w in enumerate(payload, start=1):
                try:
                    price = f"¥{float(w['price']):,.2f}"
                except (TypeError, ValueError):
                    price = "价格未知"
                lines.append(f"{i}. {w['wear']}（{price}）")
                lines.append(f"   → /buff {parsed.weapon_name} {parsed.skin} {w['wear']}")
            yield event.plain_result("\n".join(lines))
            return

        # 2. 消息一：基础信息 + 走势
        try:
            msg = await fetch_price_message(client, str(payload))
        except BuffError as e:
            yield event.plain_result(f"查询出错：{e}")
            return
        except Exception as e:
            logger.error(f"[buff_cs2] fetch_price_message 异常: {e}")
            yield event.plain_result("查询时出了点问题，稍后再试喵")
            return

        chain = MessageChain()
        if msg["image_url"]:
            chain.append(Image(url=msg["image_url"]))
        chain.append(Plain(msg["text"]))
        yield event.chain_result(chain)

        # 3. 消息二：武器类扫描同品类
        type_internal = msg.get("type_internal") or ""
        if type_internal not in WEAPON_CATEGORY_GROUP:
            return

        category_group = WEAPON_CATEGORY_GROUP[type_internal]
        scan_num = int(self.config.get("scan_num", 30))
        cache_ttl = int(self.config.get("cache_ttl", 600))

        cached = self._scan_cache.get(category_group)
        if cached and (time.time() - cached[0]) < cache_ttl:
            top3 = cached[1]
        else:
            yield event.plain_result(f"正在扫描 {scan_num} 件同品类商品并计算印花溢价，稍等几秒喵…")
            queue: asyncio.Queue = asyncio.Queue()

            async def _scan():
                try:
                    top3 = await fetch_category_attention(
                        client,
                        type_internal,
                        scan_num,
                        progress_cb=lambda i, t, n: queue.put(("p", i, t, n)),
                    )
                    await queue.put(("done", top3))
                except Exception as e:  # noqa: BLE001
                    await queue.put(("err", e))

            task = asyncio.create_task(_scan())
            top3 = None
            while True:
                kind, *args = await queue.get()
                if kind == "p":
                    i, t, _ = args
                    if i == 1 or i % 10 == 0 or i == t:
                        yield event.plain_result(f"扫描进度 {i}/{t}…")
                elif kind == "err":
                    logger.error(f"[buff_cs2] 同品类扫描失败: {args[0]}")
                    yield event.plain_result("同品类扫描失败，稍后再试喵")
                    return
                else:
                    top3 = args[0]
                    break
            await task
            if top3 is None:
                return
            self._scan_cache[category_group] = (time.time(), top3)

        text = format_attention_text(category_group, top3)
        yield event.plain_result(text)
