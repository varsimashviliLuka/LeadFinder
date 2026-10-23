"""Reading the opening hours saved from Google Maps, e.g. {"ორშაბათი": "10AM-8PM"}."""

import re

DAY_INDEX = {
    "ორშაბათი": 0, "სამშაბათი": 1, "ოთხშაბათი": 2, "ხუთშაბათი": 3, "პარასკევი": 4, "შაბათი": 5, "კვირა": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
CLOSED_WORDS = ("closed", "დაკეტ", "დახურ")
ALL_DAY_WORDS = ("24 hours", "24 საათ")
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", re.IGNORECASE)
CLOSES_SOON_MINUTES = 30


def _minutes(hour, minute, meridiem):
    hour, minute = int(hour), int(minute or 0)
    if meridiem:
        hour = hour % 12 + (12 if meridiem.upper() == "PM" else 0)
    return hour * 60 + minute


def parse_ranges(text):
    """'10AM-8PM' -> [(600, 1200)]; ranges past midnight end above 1440.
    Returns [] for closed and None if the text can't be read."""
    value = (text or "").strip().lower()
    if not value:
        return None
    if any(word in value for word in CLOSED_WORDS):
        return []
    if any(word in value for word in ALL_DAY_WORDS):
        return [(0, 1440)]
    ranges = []
    for part in re.split(r"[,;]", text):
        bounds = re.split(r"\s*[-–—]\s*", part.strip().replace("\u202f", " ").replace("\xa0", " "))
        if len(bounds) != 2:
            return None
        start, end = (TIME_RE.match(b.strip()) for b in bounds)
        if not start or not end:
            return None
        end_min = _minutes(*end.groups())
        if start.group(3) or not end.group(3):
            start_min = _minutes(*start.groups())
        else:
            # "9-10AM", "12-8AM", "11-1PM": the first time shares the second's AM/PM unless that puts it after the end.
            start_min = _minutes(start.group(1), start.group(2), end.group(3))
            if start_min > end_min:
                start_min = _minutes(start.group(1), start.group(2), "AM" if end.group(3).upper() == "PM" else "PM")
        if end_min <= start_min:
            end_min += 1440
        ranges.append((start_min, end_min))
    return ranges


def _fmt(minutes):
    minutes %= 1440
    return f"{minutes // 60}:{minutes % 60:02d}"


def _day_ranges(hours, weekday):
    for day, text in (hours or {}).items():
        if DAY_INDEX.get(day.strip().lower()) == weekday:
            return parse_ranges(text)
    return None


def open_status(hours, arrival, stay_minutes=0):
    """Whether a business is open when you arrive (a naive local datetime).

    Returns {"state": open | closes_soon | closed | unknown, "text": ...}.
    """
    today = _day_ranges(hours, arrival.weekday())
    yesterday = _day_ranges(hours, (arrival.weekday() - 1) % 7)
    if today is None and yesterday is None:
        return {"state": "unknown", "text": "Opening hours unknown"}
    now = arrival.hour * 60 + arrival.minute
    windows = list(today or []) + [(s - 1440, e - 1440) for s, e in (yesterday or []) if e > 1440]
    for start, end in windows:
        if start <= now < end:
            if end >= 1440 and start <= 0 and end - start >= 1440:
                return {"state": "open", "text": "Open 24 hours"}
            if end - now < stay_minutes + CLOSES_SOON_MINUTES:
                return {"state": "closes_soon", "text": f"Closes at {_fmt(end)}, soon after you arrive"}
            return {"state": "open", "text": f"Open until {_fmt(end)}"}
    if today is None:
        return {"state": "unknown", "text": "Opening hours unknown for that day"}
    later = sorted(s for s, _ in today if s > now)
    if later:
        return {"state": "closed", "text": f"Closed when you arrive, opens at {_fmt(later[0])}"}
    return {"state": "closed", "text": "Closed when you arrive" if today else "Closed that day"}
