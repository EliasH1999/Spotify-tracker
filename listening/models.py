"""Persistent listening history. Django's ORM maps these classes to tables."""
from django.db import models
from django.db.models import F, Q


class ListeningProfile(models.Model):
    username = models.CharField(max_length=255)
    username_key = models.CharField(max_length=512, unique=True)
    reporting_timezone = models.CharField(max_length=64, default="Europe/Stockholm")


class Track(models.Model):
    class MetadataStatus(models.TextChoices):
        UNKNOWN = "unknown", "Not checked"
        AVAILABLE = "available", "Duration available"
        MISSING = "missing", "No duration available"
        ERROR = "error", "Lookup failed"

    artist = models.CharField(max_length=512)
    title = models.CharField(max_length=512)
    artist_key = models.CharField(max_length=1024)
    title_key = models.CharField(max_length=1024)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    metadata_checked_at = models.DateTimeField(null=True, blank=True)
    metadata_status = models.CharField(max_length=12, choices=MetadataStatus, default=MetadataStatus.UNKNOWN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["artist_key", "title_key"], name="track_identity_unique"),
            models.CheckConstraint(condition=Q(duration_ms__isnull=True) | Q(duration_ms__gt=0), name="track_duration_positive"),
        ]


class Listen(models.Model):
    profile = models.ForeignKey(ListeningProfile, on_delete=models.CASCADE, related_name="listens")
    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name="listens")
    played_at = models.DateTimeField()
    album = models.CharField(max_length=512, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "track", "played_at"], name="listen_identity_unique"),
        ]
        indexes = [models.Index(fields=["profile", "played_at"], name="listen_profile_time")]
        ordering = ["-played_at", "-pk"]


class SyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running or interrupted"
        COMPLETE = "complete", "Import window complete"
        INCOMPLETE = "incomplete", "Incomplete"

    profile = models.ForeignKey(ListeningProfile, on_delete=models.CASCADE, related_name="sync_runs")
    range_start = models.DateTimeField()
    range_end = models.DateTimeField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.RUNNING)
    pages_imported = models.PositiveIntegerField(default=0)
    plays_added = models.PositiveIntegerField(default=0)
    plays_existing = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(range_end__gt=F("range_start")), name="sync_range_increasing"),
        ]
