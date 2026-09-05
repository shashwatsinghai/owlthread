"""Unit tests for BufferManager (chunked rolling buffer per project + source_app)."""

import unittest

from owlthread.extraction.buffer import BufferManager


class TestCaptureBuffer(unittest.TestCase):
    """Test suite for capture buffering."""

    def setUp(self):
        # Set small threshold of 20 words for fast threshold testing
        self.mgr = BufferManager(word_threshold=20)

    def test_buffer_accumulation_per_project_and_source(self):
        """Verify buffers are isolated per (project_id, source_app)."""
        # Project 1, cursor (5 words)
        batch1 = self.mgr.add_capture(project_id=1, source_app="cursor", raw_text="one two three four five")
        self.assertIsNone(batch1)

        # Project 2, cursor (5 words)
        batch2 = self.mgr.add_capture(project_id=2, source_app="cursor", raw_text="apple banana orange grape pear")
        self.assertIsNone(batch2)

        stats = self.mgr.get_stats()
        self.assertEqual(stats["project_1:cursor"]["word_count"], 5)
        self.assertEqual(stats["project_2:cursor"]["word_count"], 5)

    def test_buffer_auto_flush_on_5000_words_threshold(self):
        """Verify automatic flush when word count meets or exceeds threshold."""
        mgr = BufferManager(word_threshold=5000)
        
        # Add 3000 words
        text_3000 = "word " * 3000
        batch1 = mgr.add_capture(project_id=1, source_app="cursor", raw_text=text_3000)
        self.assertIsNone(batch1)

        # Add 2500 words (total 5500 >= 5000)
        text_2500 = "token " * 2500
        batch2 = mgr.add_capture(project_id=1, source_app="cursor", raw_text=text_2500)
        self.assertIsNotNone(batch2)
        self.assertEqual(batch2.project_id, 1)
        self.assertEqual(batch2.source_app, "cursor")
        self.assertEqual(batch2.word_count, 5500)
        self.assertTrue(batch2.flush_timestamp)

        # Buffer should now be cleared
        stats = mgr.get_stats()
        self.assertNotIn("project_1:cursor", stats)

    def test_explicit_flush_all(self):
        """Verify flush_all flushes all active buffers across all keys."""
        self.mgr.add_capture(project_id=1, source_app="clipboard", raw_text="clip text 1 2 3")
        self.mgr.add_capture(project_id=2, source_app="cli", raw_text="cli text 4 5 6")

        flushed = self.mgr.flush_all()
        self.assertEqual(len(flushed), 2)
        
        # Second flush should be empty
        flushed_again = self.mgr.flush_all()
        self.assertEqual(len(flushed_again), 0)


if __name__ == "__main__":
    unittest.main()
