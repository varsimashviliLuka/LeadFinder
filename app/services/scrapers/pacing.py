import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class ScraperBlockedError(Exception):
    """Google showed a CAPTCHA / unusual-traffic page, or we're still backing off from one."""


class ScraperLimitError(Exception):
    """The daily place limit was reached."""


class ScraperState:
    """Pacing state that must survive restarts, stored as a small JSON file."""

    _lock = threading.Lock()

    def __init__(self, path):
        self.path = path

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.path)

    def _update(self, mutate):
        with self._lock:
            data = self._load()
            mutate(data)
            self._save(data)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def blocked_until(self):
        value = self._load().get("blocked_until")
        if not value:
            return None
        until = datetime.fromisoformat(value)
        return until if until > self._now() else None

    def mark_blocked(self, hours):
        until = self._now() + timedelta(hours=hours)
        self._update(lambda d: d.update(blocked_until=until.isoformat()))
        logger.warning("Google Maps scraping paused until %s", until.isoformat())
        return until

    def clear_block(self):
        self._update(lambda d: d.pop("blocked_until", None))

    def seconds_until_next_search(self, cooldown):
        value = self._load().get("last_search_at")
        if not value:
            return 0
        elapsed = (self._now() - datetime.fromisoformat(value)).total_seconds()
        return max(0, cooldown - elapsed)

    def record_search_started(self):
        self._update(lambda d: d.update(last_search_at=self._now().isoformat()))

    def places_today(self):
        daily = self._load().get("daily", {})
        return daily.get("places", 0) if daily.get("date") == date.today().isoformat() else 0

    def add_place(self):
        today = date.today().isoformat()

        def mutate(d):
            daily = d.get("daily", {})
            count = daily.get("places", 0) if daily.get("date") == today else 0
            d["daily"] = {"date": today, "places": count + 1}

        self._update(mutate)
