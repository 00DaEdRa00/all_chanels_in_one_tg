"""
Telegram Feed Aggregator Bot
Merges multiple Telegram channels from shared chatlist folders (t.me/addlist/...)
into a single customizable personal feed with folder and channel-level filters.
"""

import asyncio
import logging
import sys
from typing import Dict, Any

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    UserIsBlockedError,
    InputUserDeactivatedError,
)

import config
import database as db
import chatlist

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FeedAggregator")

# Telethon Clients
# 1. User Client (MTProto): Inspects chatlist links and receives channel posts
if config.USER_SESSION_STRING:
    user_client = TelegramClient(
        StringSession(config.USER_SESSION_STRING), config.API_ID, config.API_HASH
    )
else:
    user_client = TelegramClient(config.USER_SESSION, config.API_ID, config.API_HASH)

# 2. Bot Client (Bot API): Interacts with users via keyboard and delivers the feed
bot = TelegramClient(config.BOT_SESSION, config.API_ID, config.API_HASH)

# In-memory storage for pending folder update actions: { "user_id_folder_id": state_dict }
pending_updates: Dict[str, Dict[str, Any]] = {}

# User state for search prompts: { user_id: True }
user_search_states: Dict[int, bool] = {}


# ==============================================================================
# UI Keyboard Builders
# ==============================================================================

async def build_folders_menu(user_id: int, query: str = None) -> list:
    """Builds inline keyboard listing user's folders with active status indicators."""
    folders = await db.get_user_folders(user_id, query)
    buttons = []

    if folders:
        for f in folders:
            status = "✅" if f["is_active"] else "❌"
            title = f["title"]
            if len(title) > 28:
                title = title[:25] + "..."
            buttons.append([
                Button.inline(f"{status} 📁 {title}", data=f"open_f:{f['id']}")
            ])
    else:
        buttons.append([
            Button.inline("ℹ️ Папок не найдено", data="noop")
        ])

    nav_row = [
        Button.inline("🔍 Поиск", data="search_folders"),
        Button.inline("🔄 Все папки", data="list_folders"),
    ]
    buttons.append(nav_row)
    return buttons


async def build_folder_details_menu(folder_id: int) -> tuple[str, list]:
    """Builds details view for a specific folder: toggles for folder and individual channels."""
    folder = await db.get_folder_by_id(folder_id)
    if not folder:
        return "❌ Папка не найдена.", [[Button.inline("⬅️ Назад", data="list_folders")]]

    channels = await db.get_folder_channels(folder_id)

    f_active = bool(folder["is_active"])
    f_status_text = "ВКЛЮЧЕНА (показывается в ленте)" if f_active else "ВЫКЛЮЧЕНА (скрыта)"
    f_toggle_btn = "🔴 Скрыть всю папку" if f_active else "🟢 Включить всю папку"

    text = (
        f"📁 **Раздел:** {folder['title']}\n"
        f"📊 **Статус раздела:** {f_status_text}\n"
        f"📢 **Каналов подключено:** {len(channels)}\n\n"
        f"💡 Нажмите на кнопку канала, чтобы включить (✅) или отключить (❌) его в вашей ленте:"
    )

    buttons = [
        [Button.inline(f_toggle_btn, data=f"tog_f:{folder_id}")],
        [Button.inline("────── Список каналов ──────", data="noop")]
    ]

    for ch in channels:
        ch_status = "✅" if ch["is_active"] else "❌"
        ch_name = ch["title"]
        if len(ch_name) > 24:
            ch_name = ch_name[:22] + ".."
        buttons.append([
            Button.inline(f"{ch_status} 📢 {ch_name}", data=f"tog_ch:{folder_id}:{ch['id']}")
        ])

    buttons.append([Button.inline("⬅️ Назад ко всем папкам", data="list_folders")])
    return text, buttons


# ==============================================================================
# Telegram Bot Commands & Handlers
# ==============================================================================

@bot.on(events.NewMessage(pattern=r"^/start"))
async def cmd_start(event):
    """Welcome message and instructions."""
    text = (
        "👋 **Добро пожаловать в агрегатор Telegram-каналов!**\n\n"
        "Соберите все ваши каналы из разных папок в единую удобную ленту здесь:\n\n"
        "🔗 **Как добавить каналы:**\n"
        "1. В Telegram перейдите в **Настройки → Папки с чатами**.\n"
        "2. Выберите папку, нажмите **«Поделиться»** и скопируйте ссылку.\n"
        "3. Отправьте ссылку вида `https://t.me/addlist/...` прямо в этот чат.\n\n"
        "⚙️ **Управление и фильтры:**\n"
        "• /filters — открыть интерактивное меню папок и каналов.\n"
        "• /search `<запрос>` — быстрый поиск по вашим папкам.\n"
        "• /help — подробная справка."
    )
    await event.respond(text)


@bot.on(events.NewMessage(pattern=r"^/help"))
async def cmd_help(event):
    """Help guide."""
    text = (
        "📖 **Справка по работе с ботом:**\n\n"
        "• **Каждая папка — это отдельный раздел.** При добавлении ссылки бот считывает все каналы внутри неё.\n"
        "• **Фильтрация:** В меню `/filters` вы можете в 1 клик отключить всю папку или выборочные каналы внутри неё.\n"
        "• **Обновление папок:** Если состав каналов в Telegram изменился, просто пришлите ссылку на папку снова — бот предложит добавить только новинки либо провести полную синхронизацию.\n"
        "• **Лента:** Все новые посты из включённых каналов мгновенно пересылаются сюда с указанием папки и канала-источника."
    )
    await event.respond(text)


@bot.on(events.NewMessage(pattern=r"^/filters"))
async def cmd_filters(event):
    """Opens filters control panel."""
    buttons = await build_folders_menu(event.sender_id)
    await event.respond("🗂 **Ваши папки и фильтры ленты:**", buttons=buttons)


@bot.on(events.NewMessage(pattern=r"^/search(?:\s+(.+))?"))
async def cmd_search(event):
    """Searches folders by title query."""
    query = event.pattern_match.group(1)
    if not query:
        user_search_states[event.sender_id] = True
        await event.respond("🔍 Введите название папки для поиска:")
        return

    buttons = await build_folders_menu(event.sender_id, query.strip())
    await event.respond(f"🔎 Результаты поиска по запросу **«{query.strip()}»**:", buttons=buttons)


# ==============================================================================
# Addlist Link Receiver & Diff Management
# ==============================================================================

@bot.on(events.NewMessage)
async def handle_incoming_text(event):
    """Listens for chatlist invite links or active search prompts."""
    # Ignore slash commands
    if event.text and event.text.startswith("/"):
        return

    user_id = event.sender_id

    # Handle active search input
    if user_search_states.get(user_id):
        user_search_states.pop(user_id, None)
        query = event.text.strip()
        buttons = await build_folders_menu(user_id, query)
        await event.respond(f"🔎 Результаты поиска по запросу **«{query}»**:", buttons=buttons)
        return

    # Check if text contains a chatlist URL
    slug = chatlist.extract_slug(event.text or "")
    if not slug:
        return

    status_msg = await event.respond("⏳ Считываю данные папки через Telegram API...")

    try:
        title, channels = await chatlist.inspect_chatlist(user_client, slug)
    except Exception as err:
        logger.error(f"Error inspecting chatlist {slug}: {err}", exc_info=True)
        await status_msg.edit(f"❌ Не удалось прочитать папку: {err}\nПроверьте корректность ссылки.")
        return

    if not channels:
        await status_msg.edit("⚠️ В этой папке нет доступных каналов или чатов.")
        return

    existing_folder = await db.get_folder_by_slug(user_id, slug)

    if not existing_folder:
        # Brand new folder
        folder_id = await db.add_folder_with_channels(user_id, title, slug, channels)
        success_text = (
            f"✅ **Папка подключена как раздел!**\n\n"
            f"📁 **Раздел:** «{title}»\n"
            f"📢 **Каналов подключено:** {len(channels)}\n\n"
            f"Новые публикации начнут поступать в этот чат. "
            f"Для настройки отображения откройте /filters."
        )
        await status_msg.edit(success_text)
    else:
        # Folder already registered: compute channel diff
        folder_id = existing_folder["id"]
        added, removed_ids, common = await chatlist.diff_folder_channels(folder_id, channels)

        update_key = f"{user_id}_{folder_id}"
        pending_updates[update_key] = {
            "folder_id": folder_id,
            "title": title,
            "new_channels": channels,
            "added": added,
            "removed_count": len(removed_ids),
        }

        diff_text = (
            f"⚠️ **Папка «{title}» уже есть в вашей базе!**\n\n"
            f"📊 **Сравнение со ссылкой:**\n"
            f"• Без изменений: **{len(common)}**\n"
            f"• Новых каналов: **+{len(added)}**\n"
            f"• Удалено из папки: **-{len(removed_ids)}**\n\n"
            f"Выберите действие по обновлению:"
        )

        buttons = [
            [Button.inline(f"➕ Добавить только новые (+{len(added)})", data=f"upd_add:{update_key}")],
            [Button.inline("🔄 Полная синхронизация (заменить всё)", data=f"upd_sync:{update_key}")],
            [Button.inline("❌ Отмена", data="cancel_update")]
        ]
        await status_msg.edit(diff_text, buttons=buttons)


# ==============================================================================
# Callback Query Handlers (Interactive Menus)
# ==============================================================================

@bot.on(events.CallbackQuery)
async def handle_callback_queries(event):
    """Processes button clicks."""
    data = event.data.decode("utf-8")
    user_id = event.sender_id

    if data == "noop":
        await event.answer()
        return

    if data == "list_folders":
        buttons = await build_folders_menu(user_id)
        await event.edit("🗂 **Ваши папки и фильтры ленты:**", buttons=buttons)

    elif data == "search_folders":
        user_search_states[user_id] = True
        await event.answer("Напишите поисковый запрос в чат", alert=False)
        await event.respond("🔍 Отправьте название папки для поиска:")

    elif data.startswith("open_f:"):
        folder_id = int(data.split(":")[1])
        text, buttons = await build_folder_details_menu(folder_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith("tog_f:"):
        folder_id = int(data.split(":")[1])
        new_status = await db.toggle_folder(folder_id)
        status_word = "включен" if new_status else "выключен"
        await event.answer(f"Раздел {status_word}!")
        text, buttons = await build_folder_details_menu(folder_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith("tog_ch:"):
        _, folder_id_str, channel_id_str = data.split(":")
        folder_id, channel_id = int(folder_id_str), int(channel_id_str)
        new_status = await db.toggle_channel_in_folder(folder_id, channel_id)
        status_word = "включен" if new_status else "отключен"
        await event.answer(f"Канал {status_word}!")
        text, buttons = await build_folder_details_menu(folder_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith("upd_add:"):
        key = data.split(":", 1)[1]
        state = pending_updates.pop(key, None)
        if not state:
            await event.edit("⌛ Срок действия действия истек.")
            return

        added_count = await db.add_channels_to_folder(state["folder_id"], state["added"])
        await event.edit(
            f"✅ **Успешно добавлено {added_count} новых каналов** в раздел «{state['title']}»!"
        )

    elif data.startswith("upd_sync:"):
        key = data.split(":", 1)[1]
        state = pending_updates.pop(key, None)
        if not state:
            await event.edit("⌛ Срок действия действия истек.")
            return

        await db.sync_folder_channels(state["folder_id"], state["new_channels"])
        await event.edit(
            f"🔄 **Раздел «{state['title']}» полностью синхронизирован** со ссылкой "
            f"({len(state['new_channels'])} каналов)."
        )

    elif data == "cancel_update":
        await event.edit("❌ Обновление папки отменено.")


# ==============================================================================
# Real-Time Channel Post Forwarder
# ==============================================================================

@user_client.on(events.NewMessage)
async def channel_post_listener(event):
    """Listens to all posts in channels joined by the MTProto client and routes them to users."""
    if not event.is_channel:
        return

    # Extract integer ID
    channel_id = event.chat_id
    # Normalize ID: Telethon chat_id might have -100 prefix or not
    normalized_id = int(str(channel_id).replace("-100", ""))

    recipients = await db.get_active_recipients_for_channel(normalized_id)
    if not recipients:
        return

    chat = await event.get_chat()
    channel_title = getattr(chat, "title", "Канал")

    for r in recipients:
        user_id = r["user_id"]
        folder_title = r["folder_title"]
        header = f"📁 **{folder_title}** | 📢 **{channel_title}**\n\n"

        try:
            if event.message.media:
                caption = header + (event.message.text or "")
                await bot.send_file(user_id, event.message.media, caption=caption)
            elif event.message.text:
                await bot.send_message(user_id, header + event.message.text)
        except FloodWaitError as e:
            logger.warning(f"Flood wait {e.seconds}s on user {user_id}")
            await asyncio.sleep(e.seconds)
        except (UserIsBlockedError, InputUserDeactivatedError):
            logger.info(f"User {user_id} blocked bot or account deactivated.")
        except Exception as e:
            logger.error(f"Failed to deliver post to {user_id}: {e}")


# ==============================================================================
# Service Lifecycle
# ==============================================================================

async def main():
    logger.info("Initializing SQLite database...")
    await db.init_db()

    logger.info("Starting User MTProto client...")
    await user_client.start()
    logger.info("User MTProto client active.")

    logger.info("Starting Telegram Bot interface...")
    await bot.start(bot_token=config.BOT_TOKEN)
    logger.info("Bot interface active and listening.")

    # Concurrently run both clients
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot.run_until_disconnected(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
