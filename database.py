"""
Database layer for Telegram Feed Aggregator Bot.
Uses aiosqlite with SQLite WAL mode for async concurrency.
Manages folders, public channels, forwarded posts de-duplication, and user target settings.
"""

import aiosqlite
from typing import List, Dict, Optional, Tuple, Any
import config


def get_db_path() -> str:
    return config.DB_PATH


async def init_db() -> None:
    """Initialize database tables and indexes."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            slug TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, slug)
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            username TEXT,
            is_public INTEGER NOT NULL DEFAULT 1
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS folder_channels (
            folder_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (folder_id, channel_id),
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
        );
        """)

        # User settings table (target channel for forwarding)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            target_channel TEXT
        );
        """)

        # Forwarded posts table to prevent duplicate reposts
        await db.execute("""
        CREATE TABLE IF NOT EXISTS forwarded_posts (
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            forwarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, message_id)
        );
        """)

        # Indexes for fast lookup
        await db.execute("CREATE INDEX IF NOT EXISTS idx_folders_user ON folders(user_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fc_channel ON folder_channels(channel_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fwd_posts ON forwarded_posts(channel_id, message_id);")
        await db.commit()


async def get_user_folders(user_id: int, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all folders for a specific user, with optional search query."""
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        if query and query.strip():
            cur = await db.execute(
                "SELECT * FROM folders WHERE user_id = ? AND title LIKE ? ORDER BY id DESC",
                (user_id, f"%{query.strip()}%")
            )
        else:
            cur = await db.execute(
                "SELECT * FROM folders WHERE user_id = ? ORDER BY id DESC",
                (user_id,)
            )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def get_folder_by_id(folder_id: int) -> Optional[Dict[str, Any]]:
    """Fetch folder by its primary key ID."""
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_folder_by_slug(user_id: int, slug: str) -> Optional[Dict[str, Any]]:
    """Fetch folder by user ID and chatlist slug."""
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM folders WHERE user_id = ? AND slug = ?", (user_id, slug))
        row = await cur.fetchone()
        return dict(row) if row else None


async def toggle_folder(folder_id: int) -> int:
    """Toggle folder active status (1 -> 0 or 0 -> 1). Returns new status."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "UPDATE folders SET is_active = 1 - is_active WHERE id = ?",
            (folder_id,)
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT is_active FROM folders WHERE id = ?", (folder_id,))
        row = await cur.fetchone()
        return row["is_active"] if row else 0


async def get_folder_channels(folder_id: int) -> List[Dict[str, Any]]:
    """Fetch all channels linked to a folder with their active status."""
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT c.id, c.title, c.username, fc.is_active 
            FROM channels c
            JOIN folder_channels fc ON c.id = fc.channel_id
            WHERE fc.folder_id = ?
            ORDER BY c.title COLLATE NOCASE ASC
        """, (folder_id,))
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def toggle_channel_in_folder(folder_id: int, channel_id: int) -> int:
    """Toggle channel active status within a folder. Returns new status."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "UPDATE folder_channels SET is_active = 1 - is_active WHERE folder_id = ? AND channel_id = ?",
            (folder_id, channel_id)
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT is_active FROM folder_channels WHERE folder_id = ? AND channel_id = ?",
            (folder_id, channel_id)
        )
        row = await cur.fetchone()
        return row["is_active"] if row else 0


async def add_folder_with_channels(user_id: int, title: str, slug: str, channels: List[Dict[str, Any]]) -> int:
    """Add a new folder and link open/public channels to it."""
    async with aiosqlite.connect(get_db_path()) as db:
        cur = await db.execute(
            "INSERT INTO folders (user_id, title, slug) VALUES (?, ?, ?)",
            (user_id, title, slug)
        )
        folder_id = cur.lastrowid
        for ch in channels:
            await db.execute(
                "INSERT OR REPLACE INTO channels (id, title, username, is_public) VALUES (?, ?, ?, 1)",
                (ch["id"], ch["title"], ch.get("username"))
            )
            await db.execute(
                "INSERT OR IGNORE INTO folder_channels (folder_id, channel_id, is_active) VALUES (?, ?, 1)",
                (folder_id, ch["id"])
            )
        await db.commit()
        return folder_id


async def add_channels_to_folder(folder_id: int, channels: List[Dict[str, Any]]) -> int:
    """Add new public channels to an existing folder."""
    count = 0
    async with aiosqlite.connect(get_db_path()) as db:
        for ch in channels:
            await db.execute(
                "INSERT OR REPLACE INTO channels (id, title, username, is_public) VALUES (?, ?, ?, 1)",
                (ch["id"], ch["title"], ch.get("username"))
            )
            cur = await db.execute(
                "INSERT OR IGNORE INTO folder_channels (folder_id, channel_id, is_active) VALUES (?, ?, 1)",
                (folder_id, ch["id"])
            )
            if cur.rowcount > 0:
                count += 1
        await db.commit()
    return count


async def sync_folder_channels(folder_id: int, new_channels: List[Dict[str, Any]]) -> None:
    """Replace all channels in folder with new list of public channels."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("DELETE FROM folder_channels WHERE folder_id = ?", (folder_id,))
        for ch in new_channels:
            await db.execute(
                "INSERT OR REPLACE INTO channels (id, title, username, is_public) VALUES (?, ?, ?, 1)",
                (ch["id"], ch["title"], ch.get("username"))
            )
            await db.execute(
                "INSERT INTO folder_channels (folder_id, channel_id, is_active) VALUES (?, ?, 1)",
                (folder_id, ch["id"])
            )
        await db.commit()


async def remove_channel_from_system(channel_id: int) -> None:
    """Completely removes a closed/unsupported channel from all folders and database."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("DELETE FROM folder_channels WHERE channel_id = ?", (channel_id,))
        await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await db.commit()


async def set_user_target_channel(user_id: int, target_channel: str) -> None:
    """Stores or updates the destination channel where posts will be forwarded."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "INSERT INTO user_settings (user_id, target_channel) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET target_channel = excluded.target_channel",
            (user_id, target_channel)
        )
        await db.commit()


async def get_user_target_channel(user_id: int) -> Optional[str]:
    """Retrieves user destination channel (e.g. '@my_target_channel' or '-100...')."""
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT target_channel FROM user_settings WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row["target_channel"] if row and row["target_channel"] else None


async def is_post_forwarded(channel_id: int, message_id: int) -> bool:
    """Checks if message from channel has already been forwarded."""
    async with aiosqlite.connect(get_db_path()) as db:
        cur = await db.execute(
            "SELECT 1 FROM forwarded_posts WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id)
        )
        row = await cur.fetchone()
        return bool(row)


async def mark_post_forwarded(channel_id: int, message_id: int) -> None:
    """Marks message as forwarded to avoid duplicate reposts."""
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "INSERT OR IGNORE INTO forwarded_posts (channel_id, message_id) VALUES (?, ?)",
            (channel_id, message_id)
        )
        await db.commit()


async def get_active_recipients_for_channel(channel_id: int) -> List[Dict[str, Any]]:
    """
    Find all users whose folders include this channel and both
    the folder and the channel are set to active (is_active = 1).
    Also joins user_settings to know each user's custom target channel.
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT f.user_id, f.title AS folder_title, us.target_channel
            FROM folders f
            JOIN folder_channels fc ON f.id = fc.folder_id
            LEFT JOIN user_settings us ON f.user_id = us.user_id
            WHERE fc.channel_id = ? AND f.is_active = 1 AND fc.is_active = 1
        """, (channel_id,))
        rows = await cur.fetchall()
        return [dict(row) for row in rows]
