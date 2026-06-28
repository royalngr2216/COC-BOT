"""
database/db.py — Async MongoDB database layer via motor.
Replaces the previous aiosqlite/SQLite implementation.
All methods return plain dicts (or lists of dicts) so existing cog code
(`row["field"]`) works without any changes.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import motor.motor_asyncio

log = logging.getLogger("db")


def _clean(doc: Optional[dict]) -> Optional[dict]:
    """Strip MongoDB's internal _id field before returning a document."""
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


class Database:
    def __init__(self):
        self._client: motor.motor_asyncio.AsyncIOMotorClient = None
        self._db: motor.motor_asyncio.AsyncIOMotorDatabase = None

    async def init(self):
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI environment variable is not set.")

        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self._db = self._client["coc_bot"]

        # Create indexes
        await self._db.player_links.create_index("discord_id", unique=True)
        await self._db.player_links.create_index("player_tag", unique=True)
        await self._db.village_snapshots.create_index(
            [("player_tag", 1), ("snapshot_time", -1)]
        )
        await self._db.monthly_snapshots.create_index(
            [("player_tag", 1), ("month", 1)], unique=True
        )
        await self._db.war_history.create_index("war_id", unique=True)
        await self._db.player_war_stats.create_index(
            [("player_tag", 1), ("war_id", 1)], unique=True
        )
        await self._db.upgrade_log.create_index(
            [("player_tag", 1), ("detected_at", -1)]
        )
        await self._db.member_log.create_index("event_time")

        log.info("MongoDB database initialised.")

    # ── Config ────────────────────────────────────────────────────────────────

    async def get_config(self) -> Optional[dict]:
        doc = await self._db.clan_config.find_one({"_id": "config"})
        if doc is None:
            return None
        doc.pop("_id", None)
        return doc

    async def set_config(self, **kwargs):
        await self._db.clan_config.update_one(
            {"_id": "config"},
            {"$set": kwargs},
            upsert=True,
        )

    # ── Player Links ──────────────────────────────────────────────────────────

    async def link_player(self, discord_id: int, player_tag: str, player_name: str):
        await self._db.player_links.update_one(
            {"discord_id": discord_id},
            {"$set": {
                "discord_id": discord_id,
                "player_tag": player_tag,
                "player_name": player_name,
                "linked_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    async def get_link_by_discord(self, discord_id: int) -> Optional[dict]:
        return _clean(await self._db.player_links.find_one({"discord_id": discord_id}))

    async def get_link_by_tag(self, player_tag: str) -> Optional[dict]:
        return _clean(await self._db.player_links.find_one({"player_tag": player_tag}))

    async def get_all_links(self) -> List[dict]:
        cursor = self._db.player_links.find({})
        return [_clean(doc) async for doc in cursor]

    async def update_notif_settings(self, discord_id: int, **kwargs):
        await self._db.player_links.update_one(
            {"discord_id": discord_id},
            {"$set": kwargs},
        )

    async def unlink_player(self, discord_id: int):
        await self._db.player_links.delete_one({"discord_id": discord_id})

    # ── Snapshots ─────────────────────────────────────────────────────────────

    async def save_snapshot(self, player_tag: str, data: dict):
        now = datetime.now(timezone.utc).isoformat()
        await self._db.village_snapshots.insert_one({
            "player_tag": player_tag,
            "snapshot_time": now,
            "data": data,
        })
        # Keep only the 50 most recent snapshots per player
        docs = await self._db.village_snapshots.find(
            {"player_tag": player_tag},
            {"_id": 1},
        ).sort("snapshot_time", -1).skip(50).to_list(length=None)
        if docs:
            ids = [d["_id"] for d in docs]
            await self._db.village_snapshots.delete_many({"_id": {"$in": ids}})

    async def get_latest_snapshot(self, player_tag: str) -> Optional[dict]:
        doc = await self._db.village_snapshots.find_one(
            {"player_tag": player_tag},
            sort=[("snapshot_time", -1)],
        )
        return doc["data"] if doc else None

    async def get_snapshot_at(self, player_tag: str, before: str) -> Optional[dict]:
        """Get the snapshot taken just before the given ISO timestamp."""
        doc = await self._db.village_snapshots.find_one(
            {"player_tag": player_tag, "snapshot_time": {"$lt": before}},
            sort=[("snapshot_time", -1)],
        )
        return doc["data"] if doc else None

    # ── Monthly Snapshots ─────────────────────────────────────────────────────

    async def ensure_monthly_snapshot(self, player_tag: str, completion: float, data: dict):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        # Only insert if this (player_tag, month) pair doesn't exist yet
        try:
            await self._db.monthly_snapshots.update_one(
                {"player_tag": player_tag, "month": month},
                {"$setOnInsert": {
                    "player_tag": player_tag,
                    "month": month,
                    "completion_pct": completion,
                    "snapshot_data": data,
                }},
                upsert=True,
            )
        except Exception:
            pass  # Duplicate key on race condition — safe to ignore

    async def get_monthly_snapshot(self, player_tag: str, month: str) -> Optional[dict]:
        return _clean(await self._db.monthly_snapshots.find_one(
            {"player_tag": player_tag, "month": month}
        ))

    # ── Upgrade Log ───────────────────────────────────────────────────────────

    async def log_upgrade(
        self, player_tag: str, upgrade_type: str, item_name: str,
        old_level: int, new_level: int
    ):
        await self._db.upgrade_log.insert_one({
            "player_tag": player_tag,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "upgrade_type": upgrade_type,
            "item_name": item_name,
            "old_level": old_level,
            "new_level": new_level,
        })

    async def get_upgrade_log(self, player_tag: str, limit: int = 20) -> List[dict]:
        cursor = self._db.upgrade_log.find(
            {"player_tag": player_tag}
        ).sort("detected_at", -1).limit(limit)
        return [_clean(doc) async for doc in cursor]

    # ── War History ───────────────────────────────────────────────────────────

    async def save_war(self, war_data: dict):
        war_id = war_data.get("war_id")
        await self._db.war_history.update_one(
            {"war_id": war_id},
            {"$set": war_data},
            upsert=True,
        )

    async def get_war_history(self, limit: int = 10) -> List[dict]:
        cursor = self._db.war_history.find({}).sort("start_time", -1).limit(limit)
        return [_clean(doc) async for doc in cursor]

    async def save_player_war_stats(self, player_tag: str, war_id: str, stats: dict):
        # Denormalize result + start_time from war_history so we don't need a join
        war = _clean(await self._db.war_history.find_one({"war_id": war_id}))
        await self._db.player_war_stats.update_one(
            {"player_tag": player_tag, "war_id": war_id},
            {"$set": {
                "player_tag": player_tag,
                "war_id": war_id,
                "attacks_used": stats.get("attacks_used", 0),
                "attacks_allowed": stats.get("attacks_allowed", 2),
                "stars_earned": stats.get("stars_earned", 0),
                "destruction": stats.get("destruction", 0.0),
                # Denormalized from war_history for easy retrieval
                "result": war.get("result") if war else None,
                "start_time": war.get("start_time") if war else None,
            }},
            upsert=True,
        )

    async def get_player_war_stats(self, player_tag: str) -> List[dict]:
        cursor = self._db.player_war_stats.find(
            {"player_tag": player_tag}
        ).sort("start_time", -1)
        return [_clean(doc) async for doc in cursor]

    # ── Member Event Log ──────────────────────────────────────────────────────

    async def log_member_event(
        self, player_tag: str, player_name: str, event_type: str,
        old_role: str = None, new_role: str = None
    ):
        await self._db.member_log.insert_one({
            "player_tag": player_tag,
            "player_name": player_name,
            "event_type": event_type,
            "old_role": old_role,
            "new_role": new_role,
            "event_time": datetime.now(timezone.utc).isoformat(),
        })

    async def get_member_log(self, limit: int = 20) -> List[dict]:
        cursor = self._db.member_log.find({}).sort("event_time", -1).limit(limit)
        return [_clean(doc) async for doc in cursor]

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def close(self):
        if self._client:
            self._client.close()
