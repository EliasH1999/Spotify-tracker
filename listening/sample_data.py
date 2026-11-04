"""Invented monthly summaries for learning. These are not Last.fm records.

Only this month and last month have samples. Other past months demonstrate
the empty state. Real history and statistics belong to later milestones.
"""
from calendar import monthrange
from collections import Counter
from datetime import timedelta

# title, artist, album, recorded plays, duration in milliseconds
SAMPLE_TRACKS = [
    ("After the Rain", "Paper Satellites", "Soft Focus", 28, 214_000),
    ("Bloom Again", "Mira Sol", "Small Hours", 23, 185_000),
    ("City Lights", "Northbound", "Night Drive", 18, 242_000),
    ("Daydream Radio", "Sunday Arcade", "Afterglow", 16, 196_000),
    ("Blue Hour", "June Atlas", "Blue Hour", 12, 228_000),
    ("Second Sun", "Paper Satellites", "Soft Focus", 11, None),
    ("Stay Awhile", "Mira Sol", "Small Hours", 9, 203_000),
    ("New Ways Home", "Northbound", "Night Drive", 7, 199_000),
]


def previous_month(today):
    return today.replace(day=1) - timedelta(days=1)


def build_sample_dashboard(month, today):
    """Prepare template-friendly sample summaries without network or database calls."""
    current_month = today.replace(day=1)
    prior_month = previous_month(today).replace(day=1)
    if month not in (current_month, prior_month):
        return None

    tracks = []
    artists = Counter()
    albums = Counter()
    known_duration_plays = 0
    duration_ms = 0

    for title, artist, album, plays, track_duration in SAMPLE_TRACKS:
        # Give the other sample month a different, reproducible set of counts.
        count = plays if month == current_month else max(1, plays - 3)
        tracks.append({"title": title, "artist": artist, "album": album, "plays": count})
        artists[artist] += count
        albums[album] += count
        if track_duration:
            known_duration_plays += count
            duration_ms += count * track_duration

    total_plays = sum(track["plays"] for track in tracks)
    month_days = monthrange(month.year, month.month)[1]
    available_days = today.day if month == current_month else month_days

    # Distribute the invented total into invented daily counts that sum correctly.
    weights = [(day * 7) % 11 + 3 for day in range(1, available_days + 1)]
    daily_counts = [total_plays * weight // sum(weights) for weight in weights]
    for index in range(total_plays - sum(daily_counts)):
        daily_counts[index] += 1
    peak = max(daily_counts)

    activity = [
        {
            "day": day,
            "plays": daily_counts[day - 1] if day <= available_days else None,
            "height": round(daily_counts[day - 1] / peak * 100) if day <= available_days else 0,
            "label": day in (1, 5, 10, 15, 20, 25, month_days),
        }
        for day in range(1, month_days + 1)
    ]

    artist_rows = [
        {
            "name": name,
            "plays": count,
            "initials": "".join(word[0] for word in name.split()[:2]),
            "width": round(count / max(artists.values()) * 100),
            "color": index,
        }
        for index, (name, count) in enumerate(sorted(artists.items(), key=lambda row: (-row[1], row[0])))
    ]
    return {
        "plays": total_plays,
        "estimated_minutes": round(duration_ms / 60_000),
        "duration_coverage": round(known_duration_plays / total_plays * 100, 1),
        "known_duration_plays": known_duration_plays,
        "artist_count": len(artists),
        "album_count": len(albums),
        "artists": artist_rows,
        "albums": sorted(albums.items(), key=lambda row: (-row[1], row[0])),
        "tracks": sorted(tracks, key=lambda row: (-row["plays"], row["title"])),
        "activity": activity,
        "available_days": available_days,
        "month_days": month_days,
    }
