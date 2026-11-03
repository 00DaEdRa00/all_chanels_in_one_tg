"""
Tests for Telegram Feed Aggregator Database and Diff Logic.
"""

import asyncio
import os
import unittest
import aiosqlite

# Set test DB path before importing db modules
TEST_DB = "test_feed_bot.db"
import config
config.DB_PATH = TEST_DB

import database as db
import chatlist


class TestFeedDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        await db.init_db()

    async def asyncTearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    async def test_folder_crud_and_toggles(self):
        user_id = 12345
        channels = [
            {"id": 1001, "title": "Tech News", "username": "technews"},
            {"id": 1002, "title": "AI Research", "username": "airesearch"},
        ]

        # 1. Add folder
        folder_id = await db.add_folder_with_channels(user_id, "Technology", "slug123", channels)
        self.assertIsNotNone(folder_id)

        # 2. Retrieve folders
        folders = await db.get_user_folders(user_id)
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["title"], "Technology")
        self.assertEqual(folders[0]["is_active"], 1)

        # 3. Toggle folder
        new_status = await db.toggle_folder(folder_id)
        self.assertEqual(new_status, 0)

        # 4. Toggle channel
        ch_status = await db.toggle_channel_in_folder(folder_id, 1001)
        self.assertEqual(ch_status, 0)

        # 5. Search folder
        found = await db.get_user_folders(user_id, query="Tech")
        self.assertEqual(len(found), 1)
        not_found = await db.get_user_folders(user_id, query="Crypto")
        self.assertEqual(len(not_found), 0)

    async def test_channel_diff(self):
        user_id = 9999
        initial_channels = [
            {"id": 2001, "title": "Channel A", "username": "ch_a"},
            {"id": 2002, "title": "Channel B", "username": "ch_b"},
        ]
        folder_id = await db.add_folder_with_channels(user_id, "News", "newsslug", initial_channels)

        # New state from link: Channel B kept, Channel A removed, Channel C added
        updated_channels = [
            {"id": 2002, "title": "Channel B", "username": "ch_b"},
            {"id": 2003, "title": "Channel C", "username": "ch_c"},
        ]

        added, removed_ids, common = await chatlist.diff_folder_channels(folder_id, updated_channels)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["id"], 2003)
        self.assertEqual(removed_ids, {2001})
        self.assertEqual(len(common), 1)
        self.assertEqual(common[0]["id"], 2002)

    async def test_deduplication_and_settings(self):
        user_id = 7777

        # Target channel setting
        await db.set_user_target_channel(user_id, "@my_hub")
        target = await db.get_user_target_channel(user_id)
        self.assertEqual(target, "@my_hub")

        # De-duplication check
        channel_id = 55555
        message_id = 101

        self.assertFalse(await db.is_post_forwarded(channel_id, message_id))
        await db.mark_post_forwarded(channel_id, message_id)
        self.assertTrue(await db.is_post_forwarded(channel_id, message_id))

        # Channel removal test
        channels = [{"id": channel_id, "title": "Closed Ch", "username": None}]
        folder_id = await db.add_folder_with_channels(user_id, "Folder", "slug777", channels)
        cur_chans = await db.get_folder_channels(folder_id)
        self.assertEqual(len(cur_chans), 1)

        await db.remove_channel_from_system(channel_id)
        after_chans = await db.get_folder_channels(folder_id)
        self.assertEqual(len(after_chans), 0)


if __name__ == "__main__":
    unittest.main()
