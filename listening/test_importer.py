"""Importer behavior checks with a fake Last.fm client and a test database."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils.timezone import now

from .importer import ImportFailure, STORAGE_BUDGET_BYTES, import_window
from .lastfm import LastFmClient, LastFmError, RecordedPlay
from .models import Listen, ListeningProfile, SyncRun, Track


class ImportWindowTests(TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.record = RecordedPlay(
            artist="Sample Artist",
            track="Sample Track",
            album="Sample Album",
            played_at=self.start + timedelta(hours=12),
        )

        # Repeated calls return the same invented API page, without any HTTP.
        self.lastfm = Mock(spec=LastFmClient)
        self.lastfm.iter_recent_pages.return_value = [[self.record]]

    def import_sample(self, *, fetch_metadata=False):
        return import_window(
            "sample-listener",
            self.start,
            self.end,
            client=self.lastfm,
            fetch_metadata=fetch_metadata,
        )

    def test_repeated_import_does_not_duplicate_plays(self):
        """The importer should not create duplicate listening records."""
        self.import_sample()
        self.import_sample()

        self.assertEqual(Listen.objects.count(), 1)

    def test_failed_later_page_preserves_progress_and_can_be_retried(self):
        later = replace(self.record, track="Second Track", played_at=self.record.played_at + timedelta(minutes=4))

        def interrupted_pages(*args, **kwargs):
            yield [self.record]
            raise LastFmError("Last.fm is temporarily unavailable.")

        self.lastfm.iter_recent_pages.side_effect = interrupted_pages
        with self.assertRaises(ImportFailure):
            self.import_sample()
        failed = SyncRun.objects.get()
        self.assertEqual(failed.status, SyncRun.Status.INCOMPLETE)
        self.assertEqual(failed.pages_imported, 1)
        self.assertEqual(failed.plays_added, 1)
        self.assertEqual(Listen.objects.count(), 1)

        self.lastfm.iter_recent_pages.side_effect = None
        self.lastfm.iter_recent_pages.return_value = [[self.record], [later]]
        result = self.import_sample()
        self.assertEqual(result.run.status, SyncRun.Status.COMPLETE)
        self.assertEqual(result.run.plays_added, 1)
        self.assertEqual(result.run.plays_existing, 1)
        self.assertEqual(Listen.objects.count(), 2)
        failed.refresh_from_db()
        self.assertEqual(failed.status, SyncRun.Status.INCOMPLETE)

    def test_full_storage_stops_before_another_request_and_preserves_history(self):
        self.import_sample()
        self.lastfm.iter_recent_pages.reset_mock()
        with patch("listening.importer.storage_used_bytes", return_value=STORAGE_BUDGET_BYTES):
            with self.assertRaises(ImportFailure):
                self.import_sample()
        self.lastfm.iter_recent_pages.assert_not_called()
        self.assertEqual(Listen.objects.count(), 1)
        self.assertEqual(SyncRun.objects.count(), 1)
        self.assertEqual(SyncRun.objects.get().status, SyncRun.Status.COMPLETE)

    def test_current_page_rolls_back_if_its_storage_check_fails(self):
        later = replace(self.record, track="Second Track", played_at=self.record.played_at + timedelta(minutes=4))
        self.lastfm.iter_recent_pages.return_value = [[self.record], [later]]
        checks = [None, None, None, None, ImportFailure("Storage budget exceeded.")]
        with patch("listening.importer.check_storage_budget", side_effect=checks):
            with self.assertRaises(ImportFailure):
                self.import_sample()
        self.assertEqual(Listen.objects.count(), 1)
        self.assertEqual(Track.objects.count(), 1)
        failed = SyncRun.objects.get()
        self.assertEqual(failed.status, SyncRun.Status.INCOMPLETE)
        self.assertEqual(failed.pages_imported, 1)
        self.assertEqual(failed.plays_added, 1)

    def test_known_duration_is_cached_across_repeated_imports(self):
        self.lastfm.get_track_duration.return_value = 214000
        first = self.import_sample(fetch_metadata=True)
        second = self.import_sample(fetch_metadata=True)
        saved = Track.objects.get()
        self.assertEqual(saved.duration_ms, 214000)
        self.assertEqual(saved.metadata_status, Track.MetadataStatus.AVAILABLE)
        self.assertEqual(first.metadata_updated, 1)
        self.assertEqual(second.metadata_updated, 0)
        self.lastfm.get_track_duration.assert_called_once_with("Sample Artist", "Sample Track")

    def test_missing_duration_is_cached_without_inventing_a_value(self):
        self.lastfm.get_track_duration.return_value = None
        self.import_sample(fetch_metadata=True)
        self.import_sample(fetch_metadata=True)
        saved = Track.objects.get()
        self.assertIsNone(saved.duration_ms)
        self.assertEqual(saved.metadata_status, Track.MetadataStatus.MISSING)
        self.assertEqual(self.lastfm.get_track_duration.call_count, 1)

    def test_metadata_failure_does_not_invalidate_imported_history(self):
        self.lastfm.get_track_duration.side_effect = LastFmError("Last.fm is temporarily unavailable.")
        result = self.import_sample(fetch_metadata=True)
        self.assertEqual(result.run.status, SyncRun.Status.COMPLETE)
        self.assertEqual(result.metadata_errors, 1)
        self.assertEqual(Listen.objects.count(), 1)
        self.assertEqual(Track.objects.get().metadata_status, Track.MetadataStatus.ERROR)
        self.import_sample(fetch_metadata=True)
        self.assertEqual(self.lastfm.get_track_duration.call_count, 1)

    def test_expired_duration_cache_is_refreshed(self):
        self.lastfm.get_track_duration.return_value = 214000
        self.import_sample(fetch_metadata=True)
        Track.objects.update(metadata_checked_at=now() - timedelta(days=31))
        self.lastfm.get_track_duration.return_value = 200000
        self.import_sample(fetch_metadata=True)
        self.assertEqual(Track.objects.get().duration_ms, 200000)
        self.assertEqual(self.lastfm.get_track_duration.call_count, 2)

    def test_same_event_for_different_profiles_remains_separate(self):
        self.import_sample()
        import_window("another-listener", self.start, self.end, client=self.lastfm, fetch_metadata=False)
        self.assertEqual(Listen.objects.count(), 2)
        self.assertEqual(ListeningProfile.objects.count(), 2)
        self.assertEqual(Track.objects.count(), 1)

    def test_empty_history_is_recorded_as_a_completed_empty_window(self):
        self.lastfm.iter_recent_pages.return_value = [[]]
        result = self.import_sample()
        self.assertEqual(result.run.status, SyncRun.Status.COMPLETE)
        self.assertEqual(result.run.plays_added, 0)
        self.assertEqual(Listen.objects.count(), 0)
