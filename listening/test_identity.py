from unittest import TestCase
from .identity import normalize_name

class NormalizeNameTests(TestCase):
    def test_ignore_case_and_surrounding_spaces(self):
        self.assertEqual(normalize_name("  Alice  "), "alice")

    def test_preserves_distinct_track_versions(self):
        self.assertNotEqual(
            normalize_name("Song"),
            normalize_name("Song (Live)"),
        )
