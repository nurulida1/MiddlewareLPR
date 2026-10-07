import logging
import re
import time

from threading import Lock

from config import (
    DUPLICATE_TIMEOUT,
    DUPLICATE_CACHE_TTL,
)


logger = logging.getLogger(
    "middleware"
)


class PlateProcessor:

    def __init__(self):

        # Example:
        #
        # {
        #     ("CAM_ENTRY_01", "VAB1234"): 123456.78
        # }

        self.recent_plates = {}

        self._lock = Lock()

    # ========================================================
    # CLEAN PLATE
    # ========================================================

    def clean_plate(
        self,
        plate,
    ) -> str:

        if plate is None:
            return ""

        plate = (
            str(plate)
            .strip()
            .upper()
        )

        # Remove whitespace.
        #
        # Example:
        #
        # "VAB 1234"
        #
        # becomes:
        #
        # "VAB1234"

        plate = re.sub(
            r"\s+",
            "",
            plate,
        )

        return plate

    # ========================================================
    # DUPLICATE PROTECTION
    # ========================================================

    def is_duplicate(
        self,
        camera_id,
        plate,
    ) -> bool:

        now = time.monotonic()

        key = (
            camera_id,
            plate,
        )

        with self._lock:

            self._cleanup_locked(
                now
            )

            last_seen = (
                self.recent_plates.get(
                    key
                )
            )

            # Always refresh last seen time.
            #
            # This means the plate must disappear
            # for DUPLICATE_TIMEOUT seconds before
            # it is accepted again.

            self.recent_plates[key] = now

            # First time seeing plate.

            if last_seen is None:

                return False

            elapsed = (
                now
                - last_seen
            )

            if (
                elapsed
                < DUPLICATE_TIMEOUT
            ):

                logger.info(
                    "Duplicate skipped | "
                    "camera=%s | "
                    "plate=%s | "
                    "elapsed=%.2fs",
                    camera_id,
                    plate,
                    elapsed,
                )

                return True

            return False

    # ========================================================
    # CLEAN DUPLICATE CACHE
    # ========================================================

    def _cleanup_locked(
        self,
        now,
    ):

        expired = [
            key
            for key, last_seen
            in self.recent_plates.items()
            if (
                now - last_seen
                >= DUPLICATE_CACHE_TTL
            )
        ]

        for key in expired:

            del self.recent_plates[key]

    # ========================================================
    # PROCESS
    # ========================================================

    def process(
        self,
        event,
    ):

        plate = self.clean_plate(
            event.plate
        )

        logger.info(
            "Processing plate | "
            "source=%s | "
            "camera=%s | "
            "raw=%s | "
            "clean=%s | "
            "event_id=%s",
            event.source,
            event.camera_id,
            event.plate,
            plate,
            event.event_id,
        )

        # Basic safety only.
        #
        # Bosch has already selected which LPR events
        # should be published.

        if not plate:

            logger.warning(
                "Empty plate received | "
                "camera=%s",
                event.camera_id,
            )

            return None

        # Duplicate protection

        if self.is_duplicate(
            event.camera_id,
            plate,
        ):

            return None

        logger.info(
            "Plate accepted | "
            "camera=%s | "
            "plate=%s",
            event.camera_id,
            plate,
        )

        return plate