# 🏰 Clash of Clans Discord Bot

A premium, private Discord bot for **one Clash of Clans clan**. Built with Python, discord.py v2, slash commands, interactive embeds, buttons, select menus, pagination, and a persistent SQLite database.

---

## Features

| Category | What it does |
|---|---|
| **Auto Scanner** | Scans all members every 30–60 min, detects upgrades, posts combined embed |
| **Village Completion** | Per-category progress bars, tabbed navigation via dropdown |
| **Clan Leaderboard** | All members ranked by village completion % |
| **Monthly Progress** | Track who improved the most since the start of the month |
| **War System** | Current war overview, attack log, missing attacks, live Pillow scoreboard image |
| **War Reminders** | Auto-pings at 6h / 2h / 30m with @mentions |
| **Clan War League (CWL)** | Group overview, round-by-round opponent breakdown (their TH comp, stars, destruction), missing attacks per round, full group standings — all with a generated scoreboard image |
| **Member Profile** | TH, heroes, war stats, donations — tabbed card |
| **Clan Dashboard** | Level, war record, capital, members overview |
| **Donations** | Donated / Received / Ratio leaderboards |
| **Clan Games** | Points, top contributors, who is below target |
| **Clan Capital** | Raid medals, attack tracker, who still has attacks |
| **Member Tracker** | Auto-posts joins, leaves, promotions, demotions |
| **Notifications** | Per-user toggles for DMs, village, war, milestones |
| **Admin Panel** | Set channels, scan interval, global toggles |

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/yourusername/your-bot-repo.git
cd your-bot-repo
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your tokens
```

| Variable | Where to get it |
|---|---|
| `DISCORD_TOKEN` | Discord Developer Portal > Bot > Token |
| `DISCORD_GUILD_ID` | Right-click server > Copy ID (Developer Mode) |
| `COC_API_KEY` | developer.clashofclans.com — whitelist your IP |

### 3. Discord bot permissions

In the Developer Portal:
- Bot tab: enable **Server Members Intent** and **Message Content Intent**
- OAuth2 scopes: `bot`, `applications.commands`
- Bot permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Mention Everyone`

### 4. Run locally

```bash
python bot.py
```

### 5. First-time setup in Discord

```
/setup clan_tag:#YOURCLANTAG
/admin channel channel_type:Village Updates  channel:#village-updates
/admin channel channel_type:War Channel      channel:#war-chat
/admin channel channel_type:War Reminders    channel:#war-reminders
/admin channel channel_type:Member Tracker   channel:#member-log
```

---

## Deploy to Render

1. Push code to GitHub
2. Render > New > **Background Worker**
3. Connect your repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `python bot.py`
6. Add environment variables (`DISCORD_TOKEN`, `COC_API_KEY`, `DISCORD_GUILD_ID`)
7. Add a **Disk** (1 GB minimum, mount at `/opt/render/project/src`) — required for SQLite persistence
8. Deploy

> Without the disk, the database resets on every deploy. Always add it.

---

## Command Reference

### Setup & Linking
| Command | Description |
|---|---|
| `/setup` | Link the clan (admin, run once) |
| `/link` | Link Discord to CoC account |
| `/unlink` | Remove your account link |
| `/whois` | Look up a member's linked CoC account |

### Village & Progress
| Command | Description |
|---|---|
| `/village` | Completion breakdown with category tabs |
| `/progress` | Monthly progress + recent upgrades |
| `/profile` | Full tabbed member card |

### Clan
| Command | Description |
|---|---|
| `/clan` | Clan dashboard with tabs |
| `/leaderboard` | Village completion ranking |
| `/monthlyranks` | Most improved this month |
| `/donations` | Donation / ratio leaderboards |

### War
| Command | Description |
|---|---|
| `/war` | Current war with tabs + scoreboard image |
| `/warhistory` | Last 10 wars |
| `/warstats` | A player's war record |
| `/cwl` | CWL group overview, per-round opponent breakdown, live standings |

### Activities
| Command | Description |
|---|---|
| `/clangames` | Clan Games progress |
| `/capital` | Capital raid weekend |

### Settings
| Command | Description |
|---|---|
| `/notifications` | Toggle personal notification preferences |
| `/admin status` | View full config |
| `/admin channel` | Set a channel |
| `/admin interval` | Set scan interval (10–120 min) |
| `/admin toggle` | Enable/disable global notification types |
| `/admin scan` | Manual scan trigger |
| `/admin memberlog` | View member event log |
| `/admin resetclan` | Reset clan config |

---

## Project Structure

```
coc-bot/
├── bot.py                  Entry point
├── requirements.txt
├── render.yaml             Render deployment config
├── .env.example
├── database/
│   └── db.py               Async SQLite (aiosqlite), all tables and queries
├── utils/
│   ├── coc_api.py          CoC API wrapper with caching + rate limiting
│   ├── embeds.py           Premium embed factory, color palette, progress bars
│   ├── images.py           Pillow scoreboard/banner + CWL standings renderer
│   ├── completion.py       Village completion calculator + snapshot diffing
│   └── pagination.py       Button-based embed paginator
└── cogs/
    ├── setup.py            /setup /link /unlink /whois
    ├── village.py          /village /progress
    ├── profile.py          /profile
    ├── clan.py             /clan
    ├── leaderboard.py      /leaderboard /monthlyranks
    ├── war.py              /war /warhistory /warstats + auto reminders
    ├── cwl.py              /cwl — group, rounds, opponents, standings
    ├── donations.py        /donations
    ├── capital.py          /capital
    ├── games.py            /clangames
    ├── notifications.py    /notifications
    ├── admin.py            /admin command group
    ├── scanner.py          Background village scanner loop
    └── tracker.py          Member roster change tracker
```

---

## Technical Notes

- **Database:** SQLite via aiosqlite — zero setup, WAL mode, auto-prunes old snapshots
- **API Cache:** In-memory cache with 60s TTL, separate TTLs per endpoint
- **Rate limiting:** Asyncio semaphore limits to 5 concurrent CoC API calls
- **Non-blocking:** Scanner and tracker run as background task loops
- **Modular:** Each feature is an independent cog, easy to extend
