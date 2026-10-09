import logging
import re
import time
from threading import Lock

from config import DUPLICATE_TIMEOUT, DUPLICATE_CACHE_TTL


class PlateProcessor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._last_seen = {}
        self._lock = Lock()

    @staticmethod
    def clean_plate(plate):
        if not isinstance(plate, str):
            return ""

        # Uppercase and remove spaces and other separators.
        return re.sub(r"[^A-Z0-9]", "", plate.upper())

    def process(self, event):
        plate = self.clean_plate(event.plate)

        if not plate:
            self.logger.warning("Ignoring empty or invalid plate.")
            return None

        now = time.monotonic()
        cache_key = (event.camera_id, plate)

        with self._lock:
            # Remove expired entries.
            expired_keys = [
                key
                for key, last_time in self._last_seen.items()
                if now - last_time > DUPLICATE_CACHE_TTL
            ]

            for key in expired_keys:
                del self._last_seen[key]

            last_time = self._last_seen.get(cache_key)

            # Refresh last-seen time even for a duplicate.
            self._last_seen[cache_key] = now

            if (
                last_time is not None
                and now - last_time < DUPLICATE_TIMEOUT
            ):
                self.logger.info(
                    "Duplicate plate ignored: %s",
                    plate,
                )
                return None

        self.logger.info(
            "Plate accepted | raw=%s | cleaned=%s | camera=%s",
            event.plate,
            plate,
            event.camera_id,
        )

        return plate