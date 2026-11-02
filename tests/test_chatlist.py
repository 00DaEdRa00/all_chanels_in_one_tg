"""
Tests for chatlist slug extraction.
"""

import unittest
import chatlist


class TestChatlistSlugExtraction(unittest.TestCase):
    def test_slug_extractor(self):
        cases = [
            ("https://t.me/addlist/AbCdEf12345", "AbCdEf12345"),
            ("http://t.me/addlist/Test_Slug-99", "Test_Slug-99"),
            ("tg://addlist?slug=SampleSlug12345", "SampleSlug12345"),
            ("t.me/addlist/MySlug123456", "MySlug123456"),
            ("  AbCdEf12345678  ", "AbCdEf12345678"),
            ("https://google.com", None),
            ("", None),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(chatlist.extract_slug(url), expected)


if __name__ == "__main__":
    unittest.main()
