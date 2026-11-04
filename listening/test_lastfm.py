"""Offline integration checks: no real credentials or Last.fm requests."""
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .lastfm import LastFmClient, LastFmError, MAX_RESPONSE_BYTES

FAKE_KEY = "synthetic-test-key"


def track(name="First Song", *, timestamp=1793703600, artist="Sample Artist", album="Sample Album"):
    row = {"name": name, "artist": {"#text": artist}, "album": {"#text": album}}
    if timestamp is not None:
        row["date"] = {"uts": str(timestamp)}
    return row


def page(rows, *, number=1, pages=1):
    return {"recenttracks": {"track": rows, "@attr": {"page": str(number), "totalPages": str(pages)}}}


def response(payload):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return result


class LastFmClientTests(SimpleTestCase):
    def setUp(self):
        self.opener = patch("listening.lastfm.urlopen")
        self.urlopen = self.opener.start()
        self.addCleanup(self.opener.stop)
        self.sleeper = patch("listening.lastfm.time.sleep")
        self.sleep = self.sleeper.start()
        self.addCleanup(self.sleeper.stop)
        self.client = LastFmClient(FAKE_KEY)

    def test_paginates_and_excludes_currently_playing(self):
        playing = track(timestamp=None)
        playing["@attr"] = {"nowplaying": "true"}
        self.urlopen.side_effect = [
            response(page([playing, track()], pages=2)),
            response(page([track("Second Song", timestamp=1793703500)], number=2, pages=2)),
        ]
        records = self.client.get_recent_tracks("sample-user", limit=2)
        self.assertEqual([row.track for row in records], ["First Song", "Second Song"])
        self.assertEqual(records[0].played_at.tzinfo, timezone.utc)
        queries = [parse_qs(urlsplit(call.args[0].full_url).query) for call in self.urlopen.call_args_list]
        self.assertEqual([query["page"] for query in queries], [["1"], ["2"]])
        self.assertEqual(queries[0]["to"], queries[1]["to"])
        self.assertEqual(queries[0]["method"], ["user.getRecentTracks"])
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 10)

    def test_empty_history_and_currently_playing_only(self):
        playing = track(timestamp=None)
        playing["@attr"] = {"nowplaying": "true"}
        for payload in (page([], pages=0), page([playing])):
            with self.subTest(payload=payload):
                self.urlopen.return_value = response(payload)
                self.assertEqual(self.client.get_recent_tracks("sample-user"), [])

    def test_single_object_track_and_missing_album_are_supported(self):
        row = track(album="")
        self.urlopen.return_value = response(page(row))
        record = self.client.get_recent_tracks("sample-user")[0]
        self.assertEqual(record.album, None)
        self.assertEqual(record.artist, "Sample Artist")

    def test_filters_exact_half_open_interval_and_deduplicates_page_boundary(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        end = datetime(2026, 11, 2, tzinfo=timezone.utc)
        first = track("At Start", timestamp=int(start.timestamp()))
        self.urlopen.side_effect = [
            response(page([track("At End", timestamp=int(end.timestamp())), first], pages=2)),
            response(page([first, track("Before Start", timestamp=int(start.timestamp()) - 1)], number=2, pages=2)),
        ]
        records = self.client.get_recent_tracks("sample-user", start=start, end=end)
        self.assertEqual([record.track for record in records], ["At Start"])
        query = parse_qs(urlsplit(self.urlopen.call_args_list[0].args[0].full_url).query)
        self.assertEqual(query["from"], [str(int(start.timestamp()) - 1)])
        self.assertEqual(query["to"], [str(int(end.timestamp()) + 1)])

    def test_limit_stops_before_an_unneeded_page(self):
        self.urlopen.return_value = response(page([track()], pages=999))
        self.assertEqual(len(self.client.get_recent_tracks("sample-user", limit=1)), 1)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_invalid_key_and_rate_limit_are_not_retried_or_echoed(self):
        for code in (4, 6, 7, 10, 26, 29):
            with self.subTest(code=code):
                self.urlopen.reset_mock()
                self.urlopen.return_value = response({"error": code, "message": FAKE_KEY})
                with self.assertRaises(LastFmError) as error:
                    self.client.get_recent_tracks("sample-user")
                self.assertNotIn(FAKE_KEY, str(error.exception))
                self.assertEqual(self.urlopen.call_count, 1)
                self.sleep.assert_not_called()

    def test_http_error_body_is_handled_without_leaking_request_url(self):
        self.urlopen.side_effect = HTTPError(
            f"https://example.invalid/?api_key={FAKE_KEY}", 403, "Forbidden", {},
            BytesIO(json.dumps({"error": 10, "message": FAKE_KEY}).encode()),
        )
        with self.assertRaisesMessage(LastFmError, "rejected the API key") as error:
            self.client.get_recent_tracks("sample-user")
        self.assertNotIn(FAKE_KEY, str(error.exception))
        self.assertEqual(self.urlopen.call_count, 1)

    def test_http_rate_limit_does_not_retry(self):
        self.urlopen.side_effect = HTTPError("https://example.invalid/", 429, "Too Many Requests", {}, BytesIO())
        with self.assertRaisesMessage(LastFmError, "rate-limiting"):
            self.client.get_recent_tracks("sample-user")
        self.assertEqual(self.urlopen.call_count, 1)
        self.sleep.assert_not_called()

    def test_temporary_api_error_can_recover(self):
        self.urlopen.side_effect = [response({"error": 11}), response(page([track()]))]
        self.assertEqual(len(self.client.get_recent_tracks("sample-user")), 1)
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(0.5)

    def test_http_service_error_retries_are_bounded(self):
        self.urlopen.side_effect = [
            HTTPError("https://example.invalid/", 503, "Unavailable", {}, BytesIO())
            for _ in range(3)
        ]
        with self.assertRaisesMessage(LastFmError, "temporarily unavailable"):
            self.client.get_recent_tracks("sample-user")
        self.assertEqual(self.urlopen.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_connection_failures_are_bounded_and_redacted(self):
        for error in (URLError(f"Connection failed: {FAKE_KEY}"), TimeoutError(FAKE_KEY)):
            with self.subTest(error_type=type(error)):
                self.urlopen.reset_mock()
                self.sleep.reset_mock()
                self.urlopen.side_effect = error
                with self.assertRaises(LastFmError) as caught:
                    self.client.get_recent_tracks("sample-user")
                self.assertNotIn(FAKE_KEY, str(caught.exception))
                self.assertEqual(self.urlopen.call_count, 3)
                self.assertEqual(self.sleep.call_count, 2)

    def test_malformed_responses_fail_instead_of_claiming_empty_history(self):
        bad_payloads = [
            [],
            {"recenttracks": {}},
            page("invalid"),
            page([], number=2),
            page([], pages=-1),
            page([], pages=2),
            page([track(timestamp=None)]),
            page([{"name": "No Artist", "date": {"uts": "1793703600"}}]),
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.urlopen.return_value = response(payload)
                with self.assertRaises(LastFmError):
                    self.client.get_recent_tracks("sample-user")

    def test_invalid_json_and_oversized_response_have_safe_errors(self):
        for body in (b"not json", b"x" * (MAX_RESPONSE_BYTES + 1)):
            with self.subTest(size=len(body)):
                result = MagicMock()
                result.__enter__.return_value.read.return_value = body
                self.urlopen.return_value = result
                with self.assertRaises(LastFmError):
                    self.client.get_recent_tracks("sample-user")

    def test_invalid_configuration_or_bounds_make_no_request(self):
        with self.assertRaisesMessage(LastFmError, "LASTFM_API_KEY"):
            LastFmClient("")
        for options in (
            {"username": ""},
            {"username": "sample-user", "limit": 0},
            {"username": "sample-user", "limit": 201},
            {"username": "sample-user", "start": datetime(2026, 11, 1)},
            {"username": "sample-user", "start": datetime(2026, 11, 2, tzinfo=timezone.utc), "end": datetime(2026, 11, 1, tzinfo=timezone.utc)},
        ):
            with self.subTest(options=options), self.assertRaises(LastFmError):
                self.client.get_recent_tracks(**options)
        self.urlopen.assert_not_called()

    def test_pagination_guard_prevents_an_endless_request(self):
        row = track(timestamp=1793703600)
        self.urlopen.side_effect = [
            response(page([row], number=number, pages=999))
            for number in range(1, 21)
        ]
        with self.assertRaisesMessage(LastFmError, "Stopped after 20 pages"):
            self.client.get_recent_tracks("sample-user", limit=2)
        self.assertEqual(self.urlopen.call_count, 20)


@override_settings(LASTFM_API_KEY=FAKE_KEY, LASTFM_USERNAME="sample-user")
class FetchRecentCommandTests(SimpleTestCase):
    @patch("listening.management.commands.fetch_recent.LastFmClient")
    def test_command_shows_local_times_and_keeps_dashboard_scope_clear(self, client_class):
        from .lastfm import RecordedPlay
        client_class.return_value.get_recent_tracks.return_value = [
            RecordedPlay("Artist\nInjected", "Track\x1b[31m", None, datetime(2026, 11, 1, 12, tzinfo=timezone.utc)),
        ]
        output = StringIO()
        call_command("fetch_recent", stdout=output)
        text = output.getvalue()
        self.assertIn("2026-11-01 13:00", text)
        self.assertIn("Artist Injected", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("dashboard still uses sample data", text)
        self.assertNotIn(FAKE_KEY, text)

    @patch("listening.management.commands.fetch_recent.LastFmClient")
    def test_month_bounds_follow_stockholm_daylight_saving(self, client_class):
        client_class.return_value.get_recent_tracks.return_value = []
        call_command("fetch_recent", month="2026-10", stdout=StringIO())
        bounds = client_class.return_value.get_recent_tracks.call_args.kwargs
        self.assertEqual(bounds["start"].astimezone(timezone.utc), datetime(2026, 9, 30, 22, tzinfo=timezone.utc))
        self.assertEqual(bounds["end"].astimezone(timezone.utc), datetime(2026, 10, 31, 23, tzinfo=timezone.utc))

    @patch("listening.management.commands.fetch_recent.LastFmClient")
    def test_invalid_options_do_not_call_provider(self, client_class):
        for options in ({"limit": 0}, {"limit": 201}, {"month": "2026-99"}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command("fetch_recent", stdout=StringIO(), **options)
        client_class.assert_not_called()

    @override_settings(LASTFM_API_KEY="")
    def test_missing_key_has_an_actionable_error(self):
        with self.assertRaisesMessage(CommandError, "LASTFM_API_KEY"):
            call_command("fetch_recent", stdout=StringIO())

    @patch("listening.management.commands.fetch_recent.LastFmClient")
    def test_empty_history_is_distinct_from_a_provider_error(self, client_class):
        output = StringIO()
        client_class.return_value.get_recent_tracks.return_value = []
        call_command("fetch_recent", stdout=output)
        self.assertIn("No recorded plays returned", output.getvalue())
        client_class.return_value.get_recent_tracks.side_effect = LastFmError("Last.fm is temporarily unavailable.")
        with self.assertRaisesMessage(CommandError, "temporarily unavailable"):
            call_command("fetch_recent", stdout=StringIO())
