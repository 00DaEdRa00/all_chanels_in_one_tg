"""
Background workers for automated tasks:
1. Periodic git repo update checker & self-updater.
2. Periodic folder channel sync detector (alerts user if new channels were added in Telegram).
"""

import asyncio
import logging
from telethon import Button
from typing import Dict, Any

import config
import database as db
import chatlist
import updater

logger = logging.getLogger("SyncWorker")


async def periodic_code_update_worker(bot_client, admin_id: int, interval_hours: int, auto_apply: bool):
    """Periodically checks GitHub for new commits."""
    if not admin_id:
        logger.info("ADMIN_ID not configured, skipping background code update worker.")
        return

    logger.info(f"Code updater worker started (interval: {interval_hours}h, auto_apply: {auto_apply}).")
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            has_update, commit_msg, count = await updater.check_git_updates()
            if has_update:
                logger.info(f"New updates detected on GitHub: {count} commits. ({commit_msg})")
                if auto_apply:
                    await bot_client.send_message(
                        admin_id,
                        f"🚀 **Автообновление:** обнаружено {count} новых коммитов в репозитории!\n"
                        f"• `{commit_msg}`\n\nПрименяю обновление и перезапускаю бота..."
                    )
                    success, msg = await updater.apply_git_update()
                    if success:
                        updater.restart_service(notify_chat_id=admin_id)
                    else:
                        await bot_client.send_message(admin_id, f"❌ Ошибка применения обновления: {msg}")
                else:
                    buttons = [
                        [Button.inline(f"🚀 Обновить до {commit_msg.split(':')[0]}", data="admin_apply_update")],
                        [Button.inline("❌ Пропустить", data="admin_dismiss_update")]
                    ]
                    await bot_client.send_message(
                        admin_id,
                        f"🔔 **Доступно обновление бота!**\n\n"
                        f"В репозитории появилось **{count}** новых коммитов:\n"
                        f"• `{commit_msg}`\n\n"
                        f"Нажмите кнопку ниже для применения:",
                        buttons=buttons
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic_code_update_worker: {e}", exc_info=True)


async def periodic_folder_sync_worker(
    user_client, bot_client, interval_hours: int, pending_updates: Dict[str, Any]
):
    """
    Periodically checks all saved chatlists for changes (e.g. author added new channels in Telegram).
    Alerts the user if additions or removals were detected.
    """
    logger.info(f"Folder sync worker started (interval: {interval_hours}h).")
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            logger.info("Scanning folders for channel updates...")

            # Get all folders across users
            async with db.aiosqlite.connect(db.get_db_path()) as conn:
                conn.row_factory = db.aiosqlite.Row
                cur = await conn.execute("SELECT id, user_id, title, slug FROM folders WHERE is_active = 1")
                folders = await cur.fetchall()

            for f in folders:
                folder_id = f["id"]
                user_id = f["user_id"]
                slug = f["slug"]
                title = f["title"]

                try:
                    _, channels, private_channels = await chatlist.inspect_chatlist(user_client, slug)

                    # Handle and warn about closed channels
                    if private_channels:
                        for priv in private_channels:
                            await db.remove_channel_from_system(priv["id"])
                            await bot_client.send_message(
                                user_id,
                                f"⚠️ **Внимание:** Канал «{priv['title']}» является закрытым и не поддерживается.\n"
                                f"Он был автоматически удалён из папки «{title}»."
                            )

                    added, removed_ids, common = await chatlist.diff_folder_channels(folder_id, channels)

                    if added or removed_ids:
                        logger.info(f"Changes detected in folder '{title}' (User: {user_id}): +{len(added)}, -{len(removed_ids)}")
                        update_key = f"{user_id}_{folder_id}"
                        pending_updates[update_key] = {
                            "folder_id": folder_id,
                            "title": title,
                            "new_channels": channels,
                            "added": added,
                            "removed_count": len(removed_ids),
                        }

                        text = (
                            f"🔔 **В вашей папке «{title}» изменился состав каналов!**\n\n"
                            f"• Новых каналов в папке: **+{len(added)}**\n"
                            f"• Удалено из папки: **-{len(removed_ids)}**\n"
                            f"• Без изменений: **{len(common)}**\n\n"
                            f"Хотите синхронизировать ленту?"
                        )
                        buttons = [
                            [Button.inline(f"➕ Добавить только новые (+{len(added)})", data=f"upd_add:{update_key}")],
                            [Button.inline("🔄 Полная синхронизация", data=f"upd_sync:{update_key}")],
                            [Button.inline("❌ Пропустить", data="cancel_update")]
                        ]
                        await bot_client.send_message(user_id, text, buttons=buttons)

                    # Polite sleep between folders to prevent Telegram rate limits
                    await asyncio.sleep(5)
                except Exception as err:
                    logger.warning(f"Failed to check folder {slug} for user {user_id}: {err}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic_folder_sync_worker: {e}", exc_info=True)
