"""
Tests for updater module.
"""

import unittest
import updater


class TestUpdater(unittest.TestCase):
    def test_get_current_commit(self):
        commit = updater.get_current_commit()
        self.assertIsInstance(commit, str)
        self.assertNotEqual(commit, "")
        self.assertNotEqual(commit, "unknown")
        self.assertTrue(len(commit) >= 7)


if __name__ == "__main__":
    unittest.main()
