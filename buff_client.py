"""网易 BUFF 异步接口客户端。

封装 BUFF 常用查询接口，统一处理：随机 UA、请求间隔节流、
失败重试（含 429 限流退避）、登录校验与错误转换。
"""
from __future__ import annotations

import asyncio
import random
import time

import aiohttp

from astrbot.api import logger

BASE = "https://buff.163.com/api/market"
DEFAULT_REFERER = "https://buff.163.com/"


class BuffError(Exception):
    """BUFF 接口异常。"""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def random_ua() -> str:
    """生成一个随机的 Chrome UA，降低被反爬识别的概率。"""
    first_num = random.randint(55, 62)
    third_num = random.randint(0, 3200)
    fourth_num = random.randint(0, 140)
    os_type = [
        "(Windows NT 6.1; WOW64)",
        "(Windows NT 10.0; WOW64)",
        "(X11; Linux x86_64)",
        "(Macintosh; Intel Mac OS X 10_12_6)",
    ]
    chrome = f"Chrome/{first_num}.0.{third_num}.{fourth_num}"
    return " ".join(
        [
            "Mozilla/5.0",
            random.choice(os_type),
            "AppleWebKit/537.36",
            "(KHTML, like Gecko)",
            chrome,
            "Safari/537.36",
        ]
    )


class BuffClient:
    """BUFF 接口客户端（异步）。"""

    def __init__(
        self,
        cookie: str = "",
        request_delay: float = 0.8,
        max_retries: int = 3,
    ):
        self.cookie = (cookie or "").strip()
        self.request_delay = max(0.0, float(request_delay))
        self.max_retries = max(0, int(max_retries))
        self._session: aiohttp.ClientSession | None = None
        self._last_request_at = 0.0

    @property
    def has_cookie(self) -> bool:
        return bool(self.cookie)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _throttle(self):
        """保证两次请求之间至少间隔 request_delay 秒。"""
        now = time.monotonic()
        wait = self._last_request_at + self.request_delay - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    async def _request(self, path: str, params: dict | None, referer: str = DEFAULT_REFERER) -> dict:
        url = f"{BASE}{path}"
        headers = {
            "User-Agent": random_ua(),
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.cookie:
            headers["Cookie"] = f"session={self.cookie}"

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._throttle()
            try:
                session = await self._ensure_session()
                async with session.get(
                    url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 429:
                        wait_extra = 2 * (attempt + 1)
                        logger.warning(
                            f"[buff_cs2] BUFF 限流(429)，{wait_extra}s 后重试 ({attempt + 1}/{self.max_retries + 1})"
                        )
                        await asyncio.sleep(wait_extra)
                        continue
                    if resp.status != 200:
                        text = (await resp.text())[:200]
                        raise BuffError(f"BUFF 接口返回 HTTP {resp.status}: {text}")
                    data = await resp.json()
                    code = data.get("code")
                    if code and code != "OK":
                        err = data.get("error") or data.get("msg") or str(code)
                        raise BuffError(f"BUFF 接口错误: {err}", code=str(code))
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                logger.warning(
                    f"[buff_cs2] BUFF 请求失败({type(e).__name__})，重试 {attempt + 1}/{self.max_retries + 1}"
                )
                await asyncio.sleep(1.0 * (attempt + 1))

        raise BuffError(f"BUFF 请求多次失败: {last_err}")

    async def search_suggest(self, text: str, game: str = "csgo") -> list:
        """搜索联想。返回 suggestions 列表，每项含 option 与 goods_ids。"""
        data = await self._request("/search/suggest", {"text": text, "game": game})
        return (data.get("data") or {}).get("suggestions") or []

    async def get_goods_info(self, goods_id) -> dict:
        """商品详情（名称、图片、在售/求购价等）。"""
        data = await self._request(
            "/goods/info",
            {"game": "csgo", "goods_id": goods_id},
            f"https://buff.163.com/goods/{goods_id}",
        )
        return data.get("data") or {}

    async def get_sell_orders(self, goods_id, page_num: int = 1, sort_by: str = "default") -> list:
        """在售挂单列表（每单含 price、asset_info、sticker 等）。"""
        data = await self._request(
            "/goods/sell_order",
            {
                "game": "csgo",
                "goods_id": goods_id,
                "page_num": page_num,
                "sort_by": sort_by,
            },
            f"https://buff.163.com/goods/{goods_id}",
        )
        return (data.get("data") or {}).get("items") or []

    async def get_buy_orders(self, goods_id, page_num: int = 1) -> list:
        """求购挂单列表。"""
        data = await self._request(
            "/goods/buy_order",
            {"game": "csgo", "goods_id": goods_id, "page_num": page_num},
            f"https://buff.163.com/goods/{goods_id}",
        )
        return (data.get("data") or {}).get("items") or []

    async def get_price_history(self, goods_id, days: int = 30) -> list:
        """BUFF 人民币在售最低价历史，返回 [[timestamp_ms, price], ...]。"""
        data = await self._request(
            "/goods/price_history/buff/v2",
            {"game": "csgo", "goods_id": goods_id, "days": days},
            f"https://buff.163.com/goods/{goods_id}",
        )
        lines = (data.get("data") or {}).get("lines") or []
        for line in lines:
            if line.get("key") == "sell_min_price_history":
                return line.get("points") or []
        return []

    async def get_category_goods(self, category_group: str, page_num: int = 1, page_size: int = 30) -> list:
        """同品类商品列表（category_group 如 rifle/pistol/knife）。"""
        data = await self._request(
            "/goods",
            {
                "game": "csgo",
                "category_group": category_group,
                "page_num": page_num,
                "page_size": page_size,
            },
            "https://buff.163.com/market/csgo",
        )
        return (data.get("data") or {}).get("items") or []
