"""Command behavior using mocked imports and invented local listening records."""
from datetime import date, datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from .importer import ImportFailure
from .lastfm import LastFmError
from .models import Listen, ListeningProfile, Track


@override_settings(LASTFM_USERNAME="sample-listener")
class SyncCommandTests(SimpleTestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.localdate", return_value=date(2026, 11, 4))
        clock.start()
        self.addCleanup(clock.stop)
        self.result = SimpleNamespace(
            run=SimpleNamespace(
                range_end=datetime(2026, 11, 4, 12, tzinfo=timezone.utc),
                plays_added=2, plays_existing=3, pages_imported=1,
            ),
            metadata_updated=2,
            metadata_errors=0,
        )
        service = patch("listening.management.commands.sync_listening.import_window", return_value=self.result)
        self.service = service.start()
        self.addCleanup(service.stop)

    def test_default_month_uses_local_calendar_boundaries(self):
        output = StringIO()
        call_command("sync_listening", stdout=output)
        username, start, end = self.service.call_args.args
        self.assertEqual(username, "sample-listener")
        self.assertEqual(start.astimezone(timezone.utc), datetime(2026, 10, 31, 23, tzinfo=timezone.utc))
        self.assertEqual(end.astimezone(timezone.utc), datetime(2026, 11, 30, 23, tzinfo=timezone.utc))
        self.assertTrue(self.service.call_args.kwargs["fetch_metadata"])
        self.assertIn("New plays: 2; already saved: 3", output.getvalue())

    def test_selected_month_handles_daylight_saving_and_skip_metadata(self):
        call_command("sync_listening", month="2026-10", skip_metadata=True, stdout=StringIO())
        _, start, end = self.service.call_args.args
        self.assertEqual(start.astimezone(timezone.utc), datetime(2026, 9, 30, 22, tzinfo=timezone.utc))
        self.assertEqual(end.astimezone(timezone.utc), datetime(2026, 10, 31, 23, tzinfo=timezone.utc))
        self.assertFalse(self.service.call_args.kwargs["fetch_metadata"])

    def test_invalid_and_future_months_do_not_start_an_import(self):
        for month in ("", "2026-99", "2026-12", "not-a-month"):
            with self.subTest(month=month), self.assertRaises(CommandError):
                call_command("sync_listening", month=month, stdout=StringIO())
        self.service.assert_not_called()

    def test_service_errors_have_actionable_messages(self):
        for failure, expected in (
            (ImportFailure("Import window is incomplete."), "incomplete"),
            (LastFmError("Set LASTFM_API_KEY first."), "LASTFM_API_KEY"),
            (OperationalError("private database details"), "Run manage.py migrate"),
        ):
            with self.subTest(error_type=type(failure)):
                self.service.side_effect = failure
                with self.assertRaises(CommandError) as error:
                    call_command("sync_listening", stdout=StringIO())
                self.assertIn(expected, str(error.exception))
                self.assertNotIn("private database details", str(error.exception))

    def test_metadata_warning_does_not_turn_history_success_into_failure(self):
        self.result.metadata_errors = 1
        output = StringIO()
        call_command("sync_listening", stdout=output)
        self.assertIn("lookup/storage warnings: 1", output.getvalue())
        self.assertIn("New plays: 2", output.getvalue())


@override_settings(LASTFM_USERNAME="sample-listener", LASTFM_API_KEY="")
class ShowSavedCommandTests(TestCase):
    def setUp(self):
        self.profile = ListeningProfile.objects.create(
            username="sample-listener", username_key="sample-listener",
        )
        other = ListeningProfile.objects.create(username="someone-else", username_key="someone-else")
        track = Track.objects.create(
            artist="Sample Artist", title="Sample Track",
            artist_key="sample artist", title_key="sample track",
        )
        private_track = Track.objects.create(
            artist="Other Artist", title="Other Listener Song",
            artist_key="other artist", title_key="other listener song",
        )
        for hour in (12, 13):
            Listen.objects.create(
                profile=self.profile, track=track,
                played_at=datetime(2026, 11, 1, hour, tzinfo=timezone.utc),
            )
        Listen.objects.create(
            profile=other, track=private_track,
            played_at=datetime(2026, 11, 1, 14, tzinfo=timezone.utc),
        )

    def show_saved(self, **options):
        output = StringIO()
        call_command("show_listens", stdout=output, **options)
        return output.getvalue()

    def test_reads_saved_plays_without_api_access_or_an_api_key(self):
        with patch("listening.lastfm.urlopen", side_effect=AssertionError("Unexpected network call.")) as request:
            text = self.show_saved()
        self.assertIn("Sample Track", text)
        self.assertIn("Showing 2 saved records", text)
        request.assert_not_called()

    def test_only_the_configured_profiles_records_are_displayed(self):
        text = self.show_saved()
        self.assertNotIn("Other Listener Song", text)
        self.assertNotIn("Other Artist", text)

    def test_limit_order_and_local_timezone_are_respected(self):
        text = self.show_saved(limit=1)
        self.assertIn("2026-11-01 14:00", text)
        self.assertNotIn("2026-11-01 13:00", text)
        self.assertIn("Showing 1 saved records", text)

    def test_invalid_limits_are_rejected(self):
        for limit in (0, 201):
            with self.subTest(limit=limit), self.assertRaises(CommandError):
                self.show_saved(limit=limit)

    @override_settings(LASTFM_USERNAME="empty-history")
    def test_no_saved_history_is_an_empty_result(self):
        self.assertIn("Showing 0 saved records", self.show_saved())

    @override_settings(LASTFM_USERNAME=" ")
    def test_missing_username_has_a_configuration_message(self):
        with self.assertRaisesMessage(CommandError, "LASTFM_USERNAME"):
            self.show_saved()

    def test_database_failure_does_not_show_internal_details(self):
        with patch(
            "listening.management.commands.show_listens.Listen.objects.filter",
            side_effect=OperationalError("private database details"),
        ):
            with self.assertRaises(CommandError) as error:
                self.show_saved()
        self.assertIn("Run manage.py migrate", str(error.exception))
        self.assertNotIn("private database details", str(error.exception))
