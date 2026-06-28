"""
utils/coc_api.py — Async CoC API wrapper with in-memory caching.
Respects rate limits and minimises redundant requests.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

log = logging.getLogger("coc_api")

BASE_URL = "https://api.clashofclans.com/v1"


class CoCAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"CoC API {status}: {message}")


class CoCAPI:
    def __init__(self, api_key: str, db):
        self.api_key = api_key
        self.db = db
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, tuple] = {}  # url -> (data, expires_at)
        self._cache_ttl = 60  # seconds
        self._semaphore = asyncio.Semaphore(5)  # max 5 concurrent requests

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(
                headers=self.headers, timeout=timeout
            )
        return self._session

    def _cache_key(self, url: str) -> str:
        return url

    def _get_cached(self, url: str) -> Optional[Any]:
        entry = self._cache.get(url)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        return None

    def _set_cache(self, url: str, data: Any, ttl: int = None):
        ttl = ttl or self._cache_ttl
        self._cache[url] = (data, time.monotonic() + ttl)

    async def _get(self, path: str, ttl: int = None) -> dict:
        url = f"{BASE_URL}{path}"
        cached = self._get_cached(url)
        if cached is not None:
            return cached

        async with self._semaphore:
            session = await self._get_session()
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._set_cache(url, data, ttl)
                        return data
                    elif resp.status == 404:
                        raise CoCAPIError(404, "Not found")
                    elif resp.status == 403:
                        raise CoCAPIError(403, "Invalid API key or IP not whitelisted")
                    elif resp.status == 429:
                        log.warning("Rate limited by CoC API — sleeping 2s")
                        await asyncio.sleep(2)
                        raise CoCAPIError(429, "Rate limited")
                    else:
                        text = await resp.text()
                        raise CoCAPIError(resp.status, text[:200])
            except aiohttp.ClientError as e:
                raise CoCAPIError(0, str(e))

    # ── Clan ──────────────────────────────────────────────────────────────────

    async def get_clan(self, clan_tag: str) -> dict:
        tag = clan_tag.replace("#", "%23")
        return await self._get(f"/clans/{tag}", ttl=120)

    async def get_clan_members(self, clan_tag: str) -> List[dict]:
        tag = clan_tag.replace("#", "%23")
        data = await self._get(f"/clans/{tag}/members", ttl=60)
        return data.get("items", [])

    async def get_current_war(self, clan_tag: str) -> dict:
        tag = clan_tag.replace("#", "%23")
        return await self._get(f"/clans/{tag}/currentwar", ttl=30)

    async def get_war_league(self, clan_tag: str) -> dict:
        tag = clan_tag.replace("#", "%23")
        try:
            return await self._get(f"/clans/{tag}/currentwar/leaguegroup", ttl=120)
        except CoCAPIError:
            return {}

    async def get_clan_games(self, clan_tag: str) -> dict:
        # Clan games are part of clan info
        return await self.get_clan(clan_tag)

    async def get_capital_raid_seasons(self, clan_tag: str) -> dict:
        tag = clan_tag.replace("#", "%23")
        return await self._get(f"/clans/{tag}/capitalraidseasons?limit=1", ttl=120)

    # ── Player ────────────────────────────────────────────────────────────────

    async def get_player(self, player_tag: str) -> dict:
        tag = player_tag.replace("#", "%23")
        return await self._get(f"/players/{tag}", ttl=60)

    async def verify_player_token(self, player_tag: str, token: str) -> bool:
        tag = player_tag.replace("#", "%23")
        url = f"{BASE_URL}/players/{tag}/verifytoken"
        session = await self._get_session()
        async with session.post(url, json={"token": token}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("status") == "ok"
            return False

    async def invalidate_cache(self, path: str):
        url = f"{BASE_URL}{path}"
        self._cache.pop(url, None)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
