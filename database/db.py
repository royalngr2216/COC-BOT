"""
database/db.py — Async SQLite database layer via aiosqlite.
Stores snapshots, member links, clan config, war history, and more.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

log = logging.getLogger("db")

DB_PATH = "coc_bot.db"


class Database:
    def __init__(self):
        self.conn: aiosqlite.Connection = None

    async def init(self):
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        await self._create_tables()
        log.info("Database initialised.")

    async def _create_tables(self):
        await self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            -- Clan configuration (single row)
            CREATE TABLE IF NOT EXISTS clan_config (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                clan_tag        TEXT,
                guild_id        INTEGER,
                village_channel INTEGER,
                war_channel     INTEGER,
                logs_channel    INTEGER,
                reminder_channel INTEGER,
                tracker_channel INTEGER,
                scan_interval   INTEGER DEFAULT 30,
                dm_notifications INTEGER DEFAULT 1,
                village_updates  INTEGER DEFAULT 1,
                war_reminders    INTEGER DEFAULT 1,
                milestone_notifs INTEGER DEFAULT 1,
                setup_complete   INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            -- Discord ↔ CoC player links
            CREATE TABLE IF NOT EXISTS player_links (
                discord_id      INTEGER PRIMARY KEY,
                player_tag      TEXT UNIQUE NOT NULL,
                player_name     TEXT,
                linked_at       TEXT DEFAULT (datetime('now')),
                dm_notifs       INTEGER DEFAULT 1,
                village_notifs  INTEGER DEFAULT 1,
                war_notifs      INTEGER DEFAULT 1,
                milestone_notifs INTEGER DEFAULT 1
            );

            -- Village snapshots (JSON blob per player per scan)
            CREATE TABLE IF NOT EXISTS village_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                player_tag      TEXT NOT NULL,
                snapshot_time   TEXT NOT NULL,
                data            TEXT NOT NULL   -- JSON
            );
            CREATE INDEX IF NOT EXISTS idx_snap_tag_time
                ON village_snapshots(player_tag, snapshot_time DESC);

            -- Monthly snapshots (first snapshot of each month)
            CREATE TABLE IF NOT EXISTS monthly_snapshots (
                player_tag      TEXT NOT NULL,
                month           TEXT NOT NULL,   -- YYYY-MM
                completion_pct  REAL,
                snapshot_data   TEXT,            -- JSON
                PRIMARY KEY (player_tag, month)
            );

            -- War history
            CREATE TABLE IF NOT EXISTS war_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                war_id          TEXT UNIQUE,      -- opponent tag + start time
                start_time      TEXT,
                end_time        TEXT,
                team_size       INTEGER,
                our_stars       INTEGER,
                our_destruction REAL,
                opp_stars       INTEGER,
                opp_destruction REAL,
                result          TEXT,             -- win / lose / tie
                data            TEXT             -- full JSON
            );

            -- Player war stats (aggregated)
            CREATE TABLE IF NOT EXISTS player_war_stats (
                player_tag      TEXT NOT NULL,
                war_id          TEXT NOT NULL,
                attacks_used    INTEGER DEFAULT 0,
                attacks_allowed INTEGER DEFAULT 2,
                stars_earned    INTEGER DEFAULT 0,
                destruction     REAL DEFAULT 0,
                PRIMARY KEY (player_tag, war_id)
            );

            -- Upgrade log (individual upgrade events)
            CREATE TABLE IF NOT EXISTS upgrade_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                player_tag      TEXT NOT NULL,
                detected_at     TEXT NOT NULL,
                upgrade_type    TEXT,   -- building/hero/troop/spell/wall/pet/equipment
                item_name       TEXT,
                old_level       INTEGER,
                new_level       INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_ulog_tag
                ON upgrade_log(player_tag, detected_at DESC);

            -- Member join/leave/promotion log
            CREATE TABLE IF NOT EXISTS member_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                player_tag      TEXT NOT NULL,
                player_name     TEXT,
                event_type      TEXT,   -- joined/left/promoted/demoted
                old_role        TEXT,
                new_role        TEXT,
                event_time      TEXT DEFAULT (datetime('now'))
            );
        """)
        await self.conn.commit()

    # ── Config ────────────────────────────────────────────────────────────────

    async def get_config(self) -> Optional[aiosqlite.Row]:
        async with self.conn.execute("SELECT * FROM clan_config WHERE id=1") as cur:
            return await cur.fetchone()

    async def set_config(self, **kwargs):
        cfg = await self.get_config()
        if cfg is None:
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            await self.conn.execute(
                f"INSERT INTO clan_config (id, {cols}) VALUES (1, {placeholders})",
                list(kwargs.values()),
            )
        else:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            await self.conn.execute(
                f"UPDATE clan_config SET {sets} WHERE id=1",
                list(kwargs.values()),
            )
        await self.conn.commit()

    # ── Player Links ──────────────────────────────────────────────────────────

    async def link_player(self, discord_id: int, player_tag: str, player_name: str):
        await self.conn.execute(
            """INSERT INTO player_links (discord_id, player_tag, player_name)
               VALUES (?, ?, ?)
               ON CONFLICT(discord_id) DO UPDATE SET player_tag=excluded.player_tag,
                   player_name=excluded.player_name""",
            (discord_id, player_tag, player_name),
        )
        await self.conn.commit()

    async def get_link_by_discord(self, discord_id: int) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM player_links WHERE discord_id=?", (discord_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_link_by_tag(self, player_tag: str) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM player_links WHERE player_tag=?", (player_tag,)
        ) as cur:
            return await cur.fetchone()

    async def get_all_links(self) -> List[aiosqlite.Row]:
        async with self.conn.execute("SELECT * FROM player_links") as cur:
            return await cur.fetchall()

    async def update_notif_settings(self, discord_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        await self.conn.execute(
            f"UPDATE player_links SET {sets} WHERE discord_id=?",
            [*kwargs.values(), discord_id],
        )
        await self.conn.commit()

    # ── Snapshots ─────────────────────────────────────────────────────────────

    async def save_snapshot(self, player_tag: str, data: dict):
        await self.conn.execute(
            "INSERT INTO village_snapshots (player_tag, snapshot_time, data) VALUES (?, ?, ?)",
            (player_tag, datetime.utcnow().isoformat(), json.dumps(data)),
        )
        await self.conn.commit()
        # Prune old snapshots (keep last 50 per player)
        await self.conn.execute(
            """DELETE FROM village_snapshots WHERE id NOT IN (
                SELECT id FROM village_snapshots WHERE player_tag=?
                ORDER BY snapshot_time DESC LIMIT 50
            ) AND player_tag=?""",
            (player_tag, player_tag),
        )
        await self.conn.commit()

    async def get_latest_snapshot(self, player_tag: str) -> Optional[dict]:
        async with self.conn.execute(
            "SELECT data FROM village_snapshots WHERE player_tag=? ORDER BY snapshot_time DESC LIMIT 1",
            (player_tag,),
        ) as cur:
            row = await cur.fetchone()
            return json.loads(row["data"]) if row else None

    async def get_snapshot_at(self, player_tag: str, before: str) -> Optional[dict]:
        """Get the snapshot just before a given ISO timestamp."""
        async with self.conn.execute(
            """SELECT data FROM village_snapshots
               WHERE player_tag=? AND snapshot_time < ?
               ORDER BY snapshot_time DESC LIMIT 1""",
            (player_tag, before),
        ) as cur:
            row = await cur.fetchone()
            return json.loads(row["data"]) if row else None

    # ── Monthly snapshots ─────────────────────────────────────────────────────

    async def ensure_monthly_snapshot(self, player_tag: str, completion: float, data: dict):
        month = datetime.utcnow().strftime("%Y-%m")
        async with self.conn.execute(
            "SELECT 1 FROM monthly_snapshots WHERE player_tag=? AND month=?",
            (player_tag, month),
        ) as cur:
            exists = await cur.fetchone()
        if not exists:
            await self.conn.execute(
                """INSERT INTO monthly_snapshots (player_tag, month, completion_pct, snapshot_data)
                   VALUES (?, ?, ?, ?)""",
                (player_tag, month, completion, json.dumps(data)),
            )
            await self.conn.commit()

    async def get_monthly_snapshot(self, player_tag: str, month: str) -> Optional[dict]:
        async with self.conn.execute(
            "SELECT * FROM monthly_snapshots WHERE player_tag=? AND month=?",
            (player_tag, month),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Upgrade Log ───────────────────────────────────────────────────────────

    async def log_upgrade(
        self, player_tag: str, upgrade_type: str, item_name: str,
        old_level: int, new_level: int
    ):
        await self.conn.execute(
            """INSERT INTO upgrade_log
               (player_tag, detected_at, upgrade_type, item_name, old_level, new_level)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (player_tag, datetime.utcnow().isoformat(), upgrade_type, item_name, old_level, new_level),
        )
        await self.conn.commit()

    async def get_upgrade_log(self, player_tag: str, limit: int = 20) -> List[aiosqlite.Row]:
        async with self.conn.execute(
            """SELECT * FROM upgrade_log WHERE player_tag=?
               ORDER BY detected_at DESC LIMIT ?""",
            (player_tag, limit),
        ) as cur:
            return await cur.fetchall()

    # ── War History ───────────────────────────────────────────────────────────

    async def save_war(self, war_data: dict):
        war_id = war_data.get("war_id")
        await self.conn.execute(
            """INSERT OR REPLACE INTO war_history
               (war_id, start_time, end_time, team_size, our_stars, our_destruction,
                opp_stars, opp_destruction, result, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                war_id,
                war_data.get("start_time"),
                war_data.get("end_time"),
                war_data.get("team_size"),
                war_data.get("our_stars"),
                war_data.get("our_destruction"),
                war_data.get("opp_stars"),
                war_data.get("opp_destruction"),
                war_data.get("result"),
                json.dumps(war_data),
            ),
        )
        await self.conn.commit()

    async def get_war_history(self, limit: int = 10) -> List[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM war_history ORDER BY start_time DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

    async def save_player_war_stats(self, player_tag: str, war_id: str, stats: dict):
        await self.conn.execute(
            """INSERT OR REPLACE INTO player_war_stats
               (player_tag, war_id, attacks_used, attacks_allowed, stars_earned, destruction)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                player_tag, war_id,
                stats.get("attacks_used", 0),
                stats.get("attacks_allowed", 2),
                stats.get("stars_earned", 0),
                stats.get("destruction", 0.0),
            ),
        )
        await self.conn.commit()

    async def get_player_war_stats(self, player_tag: str) -> List[aiosqlite.Row]:
        async with self.conn.execute(
            """SELECT pws.*, wh.result, wh.start_time
               FROM player_war_stats pws
               JOIN war_history wh ON pws.war_id = wh.war_id
               WHERE pws.player_tag=?
               ORDER BY wh.start_time DESC""",
            (player_tag,),
        ) as cur:
            return await cur.fetchall()

    # ── Member Event Log ──────────────────────────────────────────────────────

    async def log_member_event(
        self, player_tag: str, player_name: str, event_type: str,
        old_role: str = None, new_role: str = None
    ):
        await self.conn.execute(
            """INSERT INTO member_log
               (player_tag, player_name, event_type, old_role, new_role)
               VALUES (?, ?, ?, ?, ?)""",
            (player_tag, player_name, event_type, old_role, new_role),
        )
        await self.conn.commit()

    async def get_member_log(self, limit: int = 20) -> List[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM member_log ORDER BY event_time DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

    async def close(self):
        if self.conn:
            await self.conn.close()
