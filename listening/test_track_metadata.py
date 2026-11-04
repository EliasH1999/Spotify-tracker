"""Offline checks for connecting Last.fm track metadata to the duration parser."""
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
import json

from django.test import SimpleTestCase

from .lastfm import LastFmClient, LastFmError

FAKE_KEY = "synthetic-track-metadata-key"


def response(payload):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return result


class TrackMetadataTests(SimpleTestCase):
    def setUp(self):
        opener = patch("listening.lastfm.urlopen")
        self.urlopen = opener.start()
        self.addCleanup(opener.stop)
        self.client = LastFmClient(FAKE_KEY)

    def test_duration_lookup_preserves_units_and_encodes_track_names(self):
        self.urlopen.return_value = response({"track": {"duration": "214000"}})
        result = self.client.get_track_duration(" A & B ", " Small / Hours ")
        self.assertEqual(result, 214000)
        self.assertIsInstance(result, int)
        query = parse_qs(urlsplit(self.urlopen.call_args.args[0].full_url).query)
        self.assertEqual(query["method"], ["track.getInfo"])
        self.assertEqual(query["artist"], ["A & B"])
        self.assertEqual(query["track"], ["Small / Hours"])
        self.assertEqual(query["autocorrect"], ["0"])
        self.assertNotIn("user", query)

    def test_unavailable_duration_returns_none(self):
        for info in ({}, {"duration": None}, {"duration": "0"}, {"duration": 0}):
            with self.subTest(info=info):
                self.urlopen.return_value = response({"track": info})
                self.assertIsNone(self.client.get_track_duration("Sample Artist", "Sample Track"))

    def test_malformed_metadata_has_a_safe_domain_error(self):
        payloads = [
            {},
            {"track": None},
            {"track": []},
            {"track": {"duration": "-1000"}},
            {"track": {"duration": FAKE_KEY}},
            {"track": {"duration": [214000]}},
            {"track": {"duration": True}},
            {"track": {"duration": 214000.5}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.urlopen.return_value = response(payload)
                with self.assertRaises(LastFmError) as error:
                    self.client.get_track_duration("Sample Artist", "Sample Track")
                self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_missing_names_are_rejected_before_requesting(self):
        for artist, track in (("", "Track"), ("Artist", " "), (None, "Track"), ("Artist", None)):
            with self.subTest(artist=artist, track=track), self.assertRaises(LastFmError):
                self.client.get_track_duration(artist, track)
        self.urlopen.assert_not_called()

    def test_missing_track_error_does_not_blame_the_username(self):
        self.urlopen.return_value = response({"error": 6, "message": FAKE_KEY})
        with self.assertRaises(LastFmError) as error:
            self.client.get_track_duration("Sample Artist", "Unknown Track")
        message = str(error.exception)
        self.assertIn("track metadata", message)
        self.assertNotIn("LASTFM_USERNAME", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertEqual(self.urlopen.call_count, 1)
