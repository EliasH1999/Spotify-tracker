"""Preview real recorded plays without writing to the listening database."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from listening.forms import MonthForm
from listening.lastfm import LastFmClient, LastFmError
from listening.terminal import one_line


class Command(BaseCommand):
    help = "Fetch a preview of real Last.fm recorded plays. No listening data is saved."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Number of recorded plays to show (1–200).")
        parser.add_argument("--month", help="Optional calendar month, YYYY-MM, in Europe/Stockholm.")

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 200:
            raise CommandError("Choose --limit between 1 and 200.")
        selected_month = options["month"]
        start = end = None
        if selected_month is not None:
            form = MonthForm({"month": selected_month})
            if not form.is_valid():
                message = " ".join(form.errors.get("month", []))
                raise CommandError(message)
            month = form.cleaned_data["month"]
            next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            local_timezone = ZoneInfo(settings.TIME_ZONE)
            start = datetime(month.year, month.month, 1, tzinfo=local_timezone)
            end = datetime(next_month.year, next_month.month, 1, tzinfo=local_timezone)

        try:
            client = LastFmClient(settings.LASTFM_API_KEY)
            records = client.get_recent_tracks(
                settings.LASTFM_USERNAME, limit=limit, start=start, end=end,
            )
        except LastFmError as error:
            # Underlying request URLs can contain a key. Keep them out of tracebacks.
            raise CommandError(str(error)) from None

        if not records:
            self.stdout.write("No recorded plays returned for this request. No listening data was saved.")
            self.stdout.write("Currently-playing tracks are excluded. Verify scrobbling and the selected date range.")
        else:
            self.stdout.write(f"Fetched {len(records)} recorded plays. Times shown in {settings.TIME_ZONE}.")
            for record in records:
                local_time = timezone.localtime(record.played_at).strftime("%Y-%m-%d %H:%M")
                self.stdout.write(f"{local_time} | {one_line(record.artist)} — {one_line(record.track)}")
            self.stdout.write("Preview only: no listening data was saved. The dashboard still uses sample data.")
        self.stdout.write("Data supplied by Last.fm: https://www.last.fm/")
