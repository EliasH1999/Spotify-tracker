def parse_duration_ms(track_info):
    """Read and validate a track duration already expressed in milliseconds."""
    track_duration = track_info.get("duration")
    if track_duration is None:
        return None
    duration_ms = int(track_duration)

    if duration_ms == 0:
        return None

    if duration_ms < 0:
        raise ValueError("Duration cannot be negative")

    return duration_ms
