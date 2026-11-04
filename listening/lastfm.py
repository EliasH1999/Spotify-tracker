"""Read-only Last.fm client. This module never stores or prints an API key."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .metadata import parse_duration_ms

API_URL = "https://ws.audioscrobbler.com/2.0/"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 20
MAX_ATTEMPTS = 3


class LastFmError(Exception):
    """A safe, user-facing error without request URLs or credentials."""


class _TemporaryError(LastFmError):
    """Internal signal: retry a temporary provider failure."""


@dataclass(frozen=True)
class RecordedPlay:
    artist: str
    track: str
    album: str | None
    played_at: datetime


def _decode_response(body):
    if len(body) > MAX_RESPONSE_BYTES:
        raise LastFmError("Last.fm's response was too large. Try a smaller request.")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise LastFmError("Last.fm returned an unreadable response. Try again later.") from None
    if not isinstance(payload, dict):
        raise LastFmError("Last.fm returned an unexpected response format.")
    return payload


def _check_api_error(payload, method=None):
    if "error" not in payload:
        return
    try:
        code = int(payload["error"])
    except (TypeError, ValueError, OverflowError):
        raise LastFmError("Last.fm returned an invalid error response.") from None
    messages = {
        4: "Last.fm refused access to this profile.",
        6: "Last.fm rejected the request. Check LASTFM_USERNAME in your local .env file.",
        7: "Last.fm could not find that profile. Check LASTFM_USERNAME.",
        10: "Last.fm rejected the API key. Check LASTFM_API_KEY in your local .env file.",
        26: "Last.fm has suspended this API key. Check its status on Last.fm.",
        29: "Last.fm is rate-limiting requests. Wait before trying again.",
    }
    if method == "track.getInfo":
        messages[6] = "Last.fm could not find track metadata for that artist and track."
        messages[7] = "Last.fm could not find track metadata for that artist and track."
    if code in (8, 11, 16):
        raise _TemporaryError("Last.fm is temporarily unavailable. Try again shortly.")
    raise LastFmError(messages.get(code, f"Last.fm rejected the request (error {code})."))


def _source_text(value):
    """Last.fm represents artist/album names as text or a #text object."""
    if isinstance(value, dict):
        value = value.get("#text", "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LastFmError("Last.fm returned invalid track metadata.")
    return value.strip()


def _recorded_play(row):
    if not isinstance(row, dict):
        raise LastFmError("Last.fm returned an invalid listening record.")
    attributes = row.get("@attr", {})
    if not isinstance(attributes, dict):
        raise LastFmError("Last.fm returned invalid track attributes.")
    if attributes.get("nowplaying") in ("true", True):
        return None

    try:
        timestamp = int(row["date"]["uts"])
        played_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise LastFmError("Last.fm returned a recorded play without a valid timestamp.") from None
    artist = _source_text(row.get("artist"))
    track = _source_text(row.get("name"))
    album = _source_text(row.get("album")) or None
    if not artist or not track:
        raise LastFmError("Last.fm returned a recorded play without an artist or track name.")
    return RecordedPlay(artist=artist, track=track, album=album, played_at=played_at)


class LastFmClient:
    def __init__(self, api_key):
        if not isinstance(api_key, str) or not api_key.strip():
            raise LastFmError("Set LASTFM_API_KEY in the local .env file first.")
        self._api_key = api_key.strip()

    def _request(self, parameters):
        # Build the query here; never put the URL into a log or user-facing error.
        query = urlencode({**parameters, "api_key": self._api_key, "format": "json"})
        request = Request(
            f"{API_URL}?{query}",
            headers={"User-Agent": "ListeningDashboard/0.1 (personal noncommercial project)"},
        )
        for attempt in range(MAX_ATTEMPTS):
            try:
                try:
                    with urlopen(request, timeout=10) as response:
                        body = response.read(MAX_RESPONSE_BYTES + 1)
                except HTTPError as error:
                    with error:
                        if error.code == 429:
                            raise LastFmError("Last.fm is rate-limiting requests. Wait before trying again.") from None
                        if error.code in (500, 502, 503, 504):
                            raise _TemporaryError("Last.fm is temporarily unavailable. Try again shortly.") from None
                        payload = _decode_response(error.read(MAX_RESPONSE_BYTES + 1))
                        _check_api_error(payload, parameters.get("method"))
                        raise LastFmError(f"Last.fm rejected the request (HTTP {error.code}).") from None
                payload = _decode_response(body)
                _check_api_error(payload, parameters.get("method"))
                return payload
            except (URLError, TimeoutError, ConnectionError, OSError, _TemporaryError) as error:
                if attempt == MAX_ATTEMPTS - 1:
                    message = str(error) if isinstance(error, _TemporaryError) else (
                        "Could not reach Last.fm after 3 attempts. Check your connection and try again."
                    )
                    raise LastFmError(message) from None
                time.sleep(0.5 * (attempt + 1))

    def get_track_duration(self, artist, track):
        """Fetch one track's metadata and validate its duration using our parser."""
        if not all(isinstance(value, str) and value.strip() for value in (artist, track)):
            raise LastFmError("Provide both an artist and a track name for the metadata lookup.")
        payload = self._request({
            "method": "track.getInfo",
            "artist": artist.strip(),
            "track": track.strip(),
            "autocorrect": 0,
        })
        track_info = payload.get("track")
        if not isinstance(track_info, dict):
            raise LastFmError("Last.fm returned an invalid track metadata response.")
        duration = track_info.get("duration")
        if duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, (str, int))
        ):
            raise LastFmError("Last.fm returned an invalid track duration.")
        try:
            return parse_duration_ms(track_info)
        except (TypeError, ValueError, OverflowError):
            raise LastFmError("Last.fm returned an invalid track duration.") from None

    def get_recent_tracks(self, username, *, limit=10, start=None, end=None):
        """Return up to 200 recorded plays, with optional [start, end) filtering.

        Fix the upper time bound before pagination so new scrobbles do not
        shift the requested history between pages. Bounds must be timezone-aware.
        """
        if not isinstance(username, str) or not username.strip():
            raise LastFmError("Set LASTFM_USERNAME in the local .env file first.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise LastFmError("Choose a limit between 1 and 200 recorded plays.")
        for boundary in (start, end):
            if boundary is not None and (
                not isinstance(boundary, datetime) or boundary.utcoffset() is None
            ):
                raise LastFmError("Date bounds must include a timezone.")
        snapshot_end = min(end, datetime.now(timezone.utc)) if end else datetime.now(timezone.utc)
        if start and start >= snapshot_end:
            raise LastFmError("The start of the requested range must precede its end.")

        parameters = {
            "method": "user.getRecentTracks",
            "user": username.strip(),
            "limit": min(50, limit + 1),
            # Pad strict API bounds, then apply our exact half-open interval below.
            "to": int(snapshot_end.timestamp()) + 1,
        }
        if start:
            parameters["from"] = int(start.timestamp()) - 1

        records = []
        seen = set()
        for page in range(1, MAX_PAGES + 1):
            payload = self._request({**parameters, "page": page})
            try:
                recent = payload["recenttracks"]
                rows = recent["track"]
                page_number = int(recent["@attr"]["page"])
                total_pages = int(recent["@attr"]["totalPages"])
            except (KeyError, TypeError, ValueError, OverflowError):
                raise LastFmError("Last.fm returned incomplete pagination information.") from None
            if page_number != page or total_pages < 0:
                raise LastFmError("Last.fm returned inconsistent pagination information.")
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                raise LastFmError("Last.fm returned an invalid track list.")
            if not rows and page < total_pages:
                raise LastFmError("Last.fm returned an empty page before the end of its history. Try again.")

            for row in rows:
                record = _recorded_play(row)
                if record is None:
                    continue
                if record.played_at >= snapshot_end or (start and record.played_at < start):
                    continue
                identity = (record.artist.casefold(), record.track.casefold(), record.played_at)
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(record)
                if len(records) == limit:
                    return records

            if page >= total_pages:
                return records
        raise LastFmError("Stopped after 20 pages. Request a smaller date range and try again.")
