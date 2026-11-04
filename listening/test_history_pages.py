"""History imports must consume pages safely rather than stop at 200 plays."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from .lastfm import LastFmClient, LastFmError
from .test_lastfm import page, response, track


class HistoryPageTests(SimpleTestCase):
    def setUp(self):
        opener = patch("listening.lastfm.urlopen")
        self.urlopen = opener.start()
        self.addCleanup(opener.stop)
        self.client = LastFmClient("synthetic-history-key")

    def test_history_can_exceed_the_preview_limit(self):
        rows = [track(timestamp=1793703600 - offset) for offset in range(250)]
        self.urlopen.side_effect = [
            response(page(rows[:100], number=1, pages=3)),
            response(page(rows[100:200], number=2, pages=3)),
            response(page(rows[200:], number=3, pages=3)),
        ]
        pages = list(self.client.iter_recent_pages("sample-user", page_size=100))
        self.assertEqual([len(records) for records in pages], [100, 100, 50])
        self.assertEqual(sum(len(records) for records in pages), 250)
        queries = [parse_qs(urlsplit(call.args[0].full_url).query) for call in self.urlopen.call_args_list]
        self.assertEqual([query["page"] for query in queries], [["1"], ["2"], ["3"]])
        self.assertEqual(len({query["to"][0] for query in queries}), 1)

    def test_next_page_is_requested_only_when_consumed(self):
        self.urlopen.side_effect = [
            response(page([track()], number=1, pages=2)),
            response(page([track(timestamp=1793703500)], number=2, pages=2)),
        ]
        pages = self.client.iter_recent_pages("sample-user")
        self.urlopen.assert_not_called()
        self.assertEqual(len(next(pages)), 1)
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(len(next(pages)), 1)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_later_failure_keeps_the_first_page_available(self):
        self.urlopen.side_effect = [
            response(page([track()], number=1, pages=2)),
            response({"error": 29}),
        ]
        pages = self.client.iter_recent_pages("sample-user")
        first_page = next(pages)
        with self.assertRaisesMessage(LastFmError, "rate-limiting"):
            next(pages)
        self.assertEqual(len(first_page), 1)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_page_limit_raises_instead_of_claiming_complete_history(self):
        self.urlopen.side_effect = [
            response(page([track()], number=1, pages=3)),
            response(page([track(timestamp=1793703500)], number=2, pages=3)),
        ]
        pages = self.client.iter_recent_pages("sample-user", max_pages=2)
        next(pages)
        next(pages)
        with self.assertRaisesMessage(LastFmError, "Stopped after 2 pages"):
            next(pages)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_invalid_page_limits_do_not_request_data(self):
        for options in (
            {"page_size": 0}, {"page_size": 201}, {"page_size": True},
            {"max_pages": 0}, {"max_pages": 201}, {"max_pages": True},
        ):
            with self.subTest(options=options), self.assertRaises(LastFmError):
                list(self.client.iter_recent_pages("sample-user", **options))
        self.urlopen.assert_not_called()
