"""Database behavior checks using invented profiles and listening records."""
from datetime import datetime, timedelta, timezone

from django.db import IntegrityError
from django.test import TransactionTestCase

from .models import Listen, ListeningProfile, Track


class ListenUniquenessTests(TransactionTestCase):
    def setUp(self):
        self.profile = ListeningProfile.objects.create(
            username="sample-listener",
            username_key="sample-listener",
        )
        self.track = Track.objects.create(
            artist="Sample Artist",
            title="Sample Track",
            artist_key="sample artist",
            title_key="sample track",
        )
        self.played_at = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

        # This play already exists before the test starts.
        Listen.objects.create(
            profile=self.profile,
            track=self.track,
            played_at=self.played_at,
        )

    def test_rejects_duplicate_play(self):
        """The database should reject a duplicate play record."""
        with self.assertRaises(IntegrityError):
            Listen.objects.create(
                profile=self.profile,
                track=self.track,
                played_at=self.played_at,
            )

    def test_allows_same_track_at_a_later_time(self):
        """A second listening event is valid when its timestamp differs."""
        Listen.objects.create(
            profile=self.profile,
            track=self.track,
            played_at=self.played_at + timedelta(minutes=4),
        )

        self.assertEqual(
            Listen.objects.filter(profile=self.profile, track=self.track).count(),
            2,
        )
