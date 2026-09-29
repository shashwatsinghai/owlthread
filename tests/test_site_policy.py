import unittest

from owlthread.site_policy import HARD_BLOCKED_SITES, is_hard_blocked_host, is_hard_blocked_url


class SitePolicyTests(unittest.TestCase):
    def test_catalog_has_at_least_twenty_immutable_sites(self):
        self.assertGreaterEqual(len(HARD_BLOCKED_SITES), 20)
        self.assertEqual(len(HARD_BLOCKED_SITES), len(set(HARD_BLOCKED_SITES)))
        self.assertIn("youtube.com", HARD_BLOCKED_SITES)

    def test_exact_and_subdomains_block_without_lookalike_false_positive(self):
        self.assertTrue(is_hard_blocked_host("WWW.YouTube.com."))
        self.assertTrue(is_hard_blocked_host("music.youtube.com"))
        self.assertTrue(is_hard_blocked_url("https://m.youtube.com/watch?v=1"))
        self.assertFalse(is_hard_blocked_host("youtube.com.example.org"))
        self.assertFalse(is_hard_blocked_url("https://example.org/?next=youtube.com"))


if __name__ == "__main__":
    unittest.main()
