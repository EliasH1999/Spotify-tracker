"""Behavior checks for the duration parser, using only synthetic metadata."""
from unittest import TestCase

from .metadata import parse_duration_ms


class ParseDurationTests(TestCase):
    def test_numeric_string_returns_integer_without_changing_units(self):
        result = parse_duration_ms({"duration": "214000"})
        self.assertEqual(result, 214000)
        self.assertIsInstance(result, int)

    def test_missing_duration_returns_none(self):
        for track_info in ({}, {"duration": None}):
            with self.subTest(track_info=track_info):
                self.assertIsNone(parse_duration_ms(track_info))

    def test_zero_duration_returns_none(self):
        for duration in ("0", 0):
            with self.subTest(duration=duration):
                self.assertIsNone(parse_duration_ms({"duration": duration}))

    def test_negative_duration_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_duration_ms({"duration": "-1000"})

    def test_nonnumeric_duration_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_duration_ms({"duration": "unknown"})
