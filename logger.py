import logging
import os

from logging.handlers import (
    RotatingFileHandler,
)

from config import (
    APP_NAME,
    LOG_LEVEL,
    LOG_FILE,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
)


def setup_logger():

    logger = logging.getLogger(
        "middleware"
    )

    if logger.handlers:
        return logger

    level = getattr(
        logging,
        LOG_LEVEL.upper(),
        logging.INFO,
    )

    logger.setLevel(
        level
    )

    logger.propagate = False

    # ========================================================
    # LOG DIRECTORY
    # ========================================================

    log_directory = (
        os.path.dirname(
            LOG_FILE
        )
    )

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
        "%(threadName)s | "
        "%(message)s"
    )

    # ========================================================
    # CONSOLE
    # ========================================================

    console_handler = (
        logging.StreamHandler()
    )

    console_handler.setLevel(
        level
    )

    console_handler.setFormatter(
        formatter
    )

    # ========================================================
    # FILE
    # ========================================================

    file_handler = (
        RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    )

    file_handler.setLevel(
        level
    )

    file_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        console_handler
    )

    logger.addHandler(
        file_handler
    )

    logger.info(
        "%s logger initialized",
        APP_NAME,
    )

    return logger