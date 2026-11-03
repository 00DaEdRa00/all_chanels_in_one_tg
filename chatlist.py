"""
Chatlist inspector and diff calculator.
Uses Telethon MTProto API to resolve shareable folder links (t.me/addlist/...).
Filters public (open) channels from private (closed) channels.
"""

import re
from typing import Optional, Tuple, List, Dict, Set, Any
from telethon import TelegramClient
from telethon.tl.functions.chatlists import CheckChatlistInviteRequest
import aiosqlite
import config


def extract_slug(link_or_text: str) -> Optional[str]:
    """
    Extracts the chatlist slug from various formats:
    - https://t.me/addlist/AbCdEf12345
    - tg://addlist?slug=AbCdEf12345
    - t.me/addlist/AbCdEf12345
    - AbCdEf12345 (if alphanumeric slug)
    """
    if not link_or_text:
        return None

    # Matches https://t.me/addlist/<slug> or tg://addlist?slug=<slug>
    match = re.search(r"(?:t\.me/addlist/|slug=)([a-zA-Z0-9_-]+)", link_or_text)
    if match:
        return match.group(1)

    # If user sent just the slug
    cleaned = link_or_text.strip()
    if re.match(r"^[a-zA-Z0-9_-]{10,40}$", cleaned):
        return cleaned

    return None


async def inspect_chatlist(
    client: TelegramClient, slug: str
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Resolves the Telegram chatlist invite link without joining.
    Separates public (open) channels from private (closed) channels.
    Returns: (folder_title, public_channels, private_channels)
    """
    result = await client(CheckChatlistInviteRequest(slug=slug))
    folder_title = result.title if hasattr(result, "title") else "Папка"

    public_channels = []
    private_channels = []

    # Map chats by ID
    chats_by_id = {c.id: c for c in getattr(result, "chats", [])}

    for peer in getattr(result, "peers", []):
        peer_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
        if peer_id and peer_id in chats_by_id:
            chat = chats_by_id[peer_id]
            username = getattr(chat, "username", None)
            title = getattr(chat, "title", f"Chat {chat.id}")

            channel_info = {
                "id": chat.id,
                "title": title,
                "username": username,
            }

            # If username is present, it's an open (public) channel
            if username:
                public_channels.append(channel_info)
            else:
                private_channels.append(channel_info)

    return folder_title, public_channels, private_channels


async def diff_folder_channels(
    folder_id: int, new_channels: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Set[int], List[Dict[str, Any]]]:
    """
    Compares existing channels of a folder in DB against the newly extracted channels.
    Returns:
      added: list of new channels to add
      removed_ids: set of channel IDs no longer present in the chatlist link
      common: list of channels already existing in both
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT channel_id FROM folder_channels WHERE folder_id = ?",
            (folder_id,)
        )
        rows = await cur.fetchall()
        old_ids = {r["channel_id"] for r in rows}

    new_ids = {c["id"] for c in new_channels}

    added = [c for c in new_channels if c["id"] not in old_ids]
    removed_ids = old_ids - new_ids
    common = [c for c in new_channels if c["id"] in old_ids]

    return added, removed_ids, common
