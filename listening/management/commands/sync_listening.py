"""Persist a Last.fm month, safely skipping events already stored."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils import timezone

from listening.forms import MonthForm
from listening.importer import ImportFailure, import_window
from listening.lastfm import LastFmError
from listening.time_ranges import month_bounds


class Command(BaseCommand):
    help = "Import a calendar month into local SQLite. Repeating an import is safe."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM in Europe/Stockholm; defaults to this month.")
        parser.add_argument("--skip-metadata", action="store_true", help="Import listening history without duration lookups.")

    def handle(self, *args, **options):
        selected = options["month"]
        if selected is None:
            selected = timezone.localdate().strftime("%Y-%m")
        form = MonthForm({"month": selected})
        if not form.is_valid():
            raise CommandError(" ".join(form.errors.get("month", [])))
        start, end = month_bounds(form.cleaned_data["month"], settings.TIME_ZONE)
        try:
            result = import_window(
                settings.LASTFM_USERNAME, start, end,
                fetch_metadata=not options["skip_metadata"],
            )
        except (ImportFailure, LastFmError) as error:
            raise CommandError(str(error)) from None
        except DatabaseError:
            raise CommandError("Could not access local storage. Run manage.py migrate and try again.") from None
        run = result.run
        through = timezone.localtime(run.range_end).strftime("%Y-%m-%d %H:%M")
        self.stdout.write(f"Imported window for {selected}, through {through} ({settings.TIME_ZONE}).")
        self.stdout.write(f"New plays: {run.plays_added}; already saved: {run.plays_existing}; pages: {run.pages_imported}.")
        self.stdout.write(f"Track metadata checked: {result.metadata_updated}; lookup/storage warnings: {result.metadata_errors}.")
        self.stdout.write("The source may have tracking gaps. The browser dashboard still uses sample data.")
        self.stdout.write("Data supplied by Last.fm: https://www.last.fm/")
