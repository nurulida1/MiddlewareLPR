import logging
import os
from logging.handlers import RotatingFileHandler

from config import (
    APP_NAME,
    LOG_LEVEL,
    LOG_FILE,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
)


def setup_logger():
    """
    Configure application-wide logging.

    Logs are written to:
    1. Console
    2. Rotating log file

    All module loggers propagate to the root logger.
    """

    # ========================================================
    # LOG LEVEL
    # ========================================================

    level = getattr(
        logging,
        LOG_LEVEL.upper(),
        logging.INFO,
    )

    # ========================================================
    # LOG DIRECTORY
    # ========================================================

    log_directory = os.path.dirname(LOG_FILE)

    if log_directory:
        os.makedirs(
            log_directory,
            exist_ok=True,
        )

    # ========================================================
    # FORMAT
    # ========================================================

    formatter = logging.Formatter(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(threadName)s | "
        "%(message)s"
    )

    # ========================================================
    # ROOT LOGGER
    # ========================================================

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        # Console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)

        root_logger.addHandler(console_handler)

        # Rotating log file
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )

        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)

    else:
        # Reuse existing handlers to prevent duplicates.
        for handler in root_logger.handlers:
            handler.setLevel(level)
            handler.setFormatter(formatter)

    # ========================================================
    # APPLICATION LOGGER
    # ========================================================

    app_logger = logging.getLogger("middleware")
    app_logger.setLevel(level)
    app_logger.propagate = True

    app_logger.info("%s logger initialized", APP_NAME)
    app_logger.info("Log level: %s", LOG_LEVEL.upper())
    app_logger.info("Log file: %s", LOG_FILE)

    return app_logger


if __name__ == "__main__":
    app_logger = setup_logger()

    app_logger.info("Logging test started.")

    camera_logger = logging.getLogger("cameras.bosch_mqtt")
    camera_logger.info(
        "Plate detected | direction=IN | plate=ABC1234"
    )

    led_logger = logging.getLogger("led")
    led_logger.info(
        "LED output | direction=IN | ASCII_TEXT=%r",
        "ABC1234",
    )

    barrier_logger = logging.getLogger("barrier.relay_controller")
    barrier_logger.warning(
        "Barrier is in simulation mode; physical relay not activated."
    )

    app_logger.info("Logging test completed.")