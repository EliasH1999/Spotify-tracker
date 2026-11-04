from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def month_bounds(month, reporting_timezone="Europe/Stockholm"):
    """Return local calendar boundaries; Django stores their instants in UTC."""
    first = month.replace(day=1)
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    zone = ZoneInfo(reporting_timezone)
    return (
        datetime(first.year, first.month, 1, tzinfo=zone),
        datetime(following.year, following.month, 1, tzinfo=zone),
    )
