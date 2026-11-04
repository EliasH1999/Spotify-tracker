"""Read already saved listening history without contacting Last.fm."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils import timezone

from listening.identity import normalize_name
from listening.terminal import one_line
from listening.models import Listen


class Command(BaseCommand):
    help = "Show saved recorded plays from SQLite. No Last.fm request is made."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5, help="Records to show, from 1 to 200.")

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 200:
            raise CommandError("Choose --limit between 1 and 200.")
        if not settings.LASTFM_USERNAME.strip():
            raise CommandError("Set LASTFM_USERNAME in the local .env file first.")
        try:
            records = list(Listen.objects.filter(
                profile__username_key=normalize_name(settings.LASTFM_USERNAME),
            ).select_related("track")[:limit])
        except DatabaseError:
            raise CommandError("Could not access local storage. Run manage.py migrate and try again.") from None
        count = 0
        for record in records:
            local_time = timezone.localtime(record.played_at).strftime("%Y-%m-%d %H:%M")
            self.stdout.write(f"{local_time} | {one_line(record.track.artist)} - {one_line(record.track.title)}")
            count += 1
        self.stdout.write(f"Showing {count} saved records ({settings.TIME_ZONE}). No network request was made.")
