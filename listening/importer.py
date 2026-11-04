"""Import pages atomically; never keep a database transaction open over HTTP."""
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from .identity import normalize_name
from .lastfm import LastFmClient, LastFmError
from .models import Listen, ListeningProfile, SyncRun, Track

# Conservative ceiling below Last.fm's documented 100 MB usage cap.
STORAGE_BUDGET_BYTES = 80_000_000
PAGE_RESERVE_PER_RECORD = 65_536
METADATA_LIMIT = 20


class ImportFailure(Exception):
    """Safe import error. A failed window must never be marked complete."""


@dataclass(frozen=True)
class ImportResult:
    run: SyncRun
    metadata_updated: int
    metadata_errors: int


def storage_used_bytes():
    """Count SQLite pages (including pending ones) and transaction sidecars.

    Last.fm records and cached metadata are stored only in this database.
    Synthetic browser QA artifacts contain no Last.fm source data.
    """
    if connection.vendor != "sqlite":
        raise ImportFailure("Storage budgeting currently supports SQLite only.")
    name = str(connection.settings_dict["NAME"])
    if name == ":memory:" or name.startswith("file:memory"):
        return 0
    database = Path(name)
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA page_count")
        pages = cursor.fetchone()[0]
        cursor.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]
    main_bytes = max(pages * page_size, database.stat().st_size if database.exists() else 0)
    sidecars = [Path(name + suffix) for suffix in ("-journal", "-wal", "-shm")]
    return main_bytes + sum(path.stat().st_size for path in sidecars if path.exists())


def check_storage_budget(reserve=0):
    if storage_used_bytes() + reserve >= STORAGE_BUDGET_BYTES:
        raise ImportFailure(
            "Local storage is near its 80 MB safety budget. Import stopped; "
            "existing listening history has not been deleted."
        )


def _save_page(profile, run, records):
    """An entire page and its progress counters either commit together or roll back."""
    check_storage_budget(len(records) * PAGE_RESERVE_PER_RECORD + 1_000_000)
    with transaction.atomic():
        added = existing = 0
        for record in records:
            artist_key = normalize_name(record.artist)
            title_key = normalize_name(record.track)
            album = record.album or ""
            if (
                len(record.artist) > 512 or len(record.track) > 512 or len(album) > 512
                or len(artist_key) > 1024 or len(title_key) > 1024
            ):
                raise ImportFailure("Last.fm returned metadata longer than this importer supports.")
            track, _ = Track.objects.get_or_create(
                artist_key=artist_key, title_key=title_key,
                defaults={"artist": record.artist, "title": record.track},
            )
            listen, created = Listen.objects.get_or_create(
                profile=profile, track=track, played_at=record.played_at,
                defaults={"album": album},
            )
            if created:
                added += 1
            else:
                existing += 1
                if not listen.album and album:
                    listen.album = album
                    listen.save(update_fields=["album"])

        run.pages_imported += 1
        run.plays_added += added
        run.plays_existing += existing
        run.save(update_fields=["pages_imported", "plays_added", "plays_existing"])
        check_storage_budget()


def _mark_incomplete(run, message):
    # Refresh counters in case the current page's transaction rolled back.
    try:
        run.refresh_from_db()
        run.status = SyncRun.Status.INCOMPLETE
        run.finished_at = timezone.now()
        run.error_message = message
        run.save(update_fields=["status", "finished_at", "error_message"])
    except DatabaseError:
        # An unavailable/full database may prevent even saving failure status.
        # The earlier RUNNING state still never claims successful coverage.
        pass


def _cache_durations(client, profile, start, end):
    now = timezone.now()
    due = (
        Q(metadata_checked_at__isnull=True)
        | Q(metadata_status=Track.MetadataStatus.AVAILABLE, metadata_checked_at__lt=now - timedelta(days=30))
        | Q(metadata_status__in=[Track.MetadataStatus.MISSING, Track.MetadataStatus.ERROR],
            metadata_checked_at__lt=now - timedelta(days=1))
    )
    tracks = Track.objects.filter(
        due, listens__profile=profile,
        listens__played_at__gte=start, listens__played_at__lt=end,
    ).distinct().order_by("metadata_checked_at", "pk")[:METADATA_LIMIT]
    updated = errors = 0
    for track in tracks:
        try:
            check_storage_budget(1_000_000)
            duration = client.get_track_duration(track.artist, track.title)
            status = Track.MetadataStatus.AVAILABLE if duration else Track.MetadataStatus.MISSING
        except LastFmError:
            # Preserve an old known duration; cache failure separately for a day.
            duration = track.duration_ms
            status = Track.MetadataStatus.ERROR
            errors += 1
        except ImportFailure:
            return updated, errors + 1
        try:
            with transaction.atomic():
                track.duration_ms = duration
                track.metadata_status = status
                track.metadata_checked_at = now
                track.save(update_fields=["duration_ms", "metadata_status", "metadata_checked_at"])
                check_storage_budget()
        except (DatabaseError, ImportFailure, OSError):
            return updated, errors + 1
        updated += 1
        if status == Track.MetadataStatus.ERROR:
            break  # Stop metadata calls on provider failure, including rate limits.
    return updated, errors


def import_window(username, start, end, *, client=None, fetch_metadata=True):
    """Import a fixed time window. Safe retries start again and skip saved events."""
    if not isinstance(username, str) or not username.strip():
        raise ImportFailure("Set LASTFM_USERNAME in the local .env file first.")
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ImportFailure("Import boundaries must include a timezone.")
    end = min(end, timezone.now())
    if start >= end:
        raise ImportFailure("The import window must start before it ends.")
    client = client or LastFmClient(settings.LASTFM_API_KEY)
    check_storage_budget(1_000_000)
    profile, _ = ListeningProfile.objects.get_or_create(
        username_key=normalize_name(username),
        defaults={"username": username.strip(), "reporting_timezone": settings.TIME_ZONE},
    )
    run = SyncRun.objects.create(profile=profile, range_start=start, range_end=end)
    try:
        for records in client.iter_recent_pages(username, start=start, end=end):
            _save_page(profile, run, records)
        run.status = SyncRun.Status.COMPLETE
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
    except (LastFmError, ImportFailure) as error:
        _mark_incomplete(run, str(error))
        raise ImportFailure(str(error)) from None
    except (DatabaseError, OSError):
        message = "Local storage failed. Earlier pages remain saved; this window is incomplete."
        _mark_incomplete(run, message)
        raise ImportFailure(message) from None
    except KeyboardInterrupt:
        _mark_incomplete(run, "Import interrupted. Earlier pages remain saved; retry is safe.")
        raise

    updated = errors = 0
    if fetch_metadata:
        # Metadata coverage is separate from successful listening-history coverage.
        try:
            updated, errors = _cache_durations(client, profile, start, end)
        except (DatabaseError, OSError):
            errors = 1
    return ImportResult(run=run, metadata_updated=updated, metadata_errors=errors)
