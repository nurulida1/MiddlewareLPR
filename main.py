import logging
import os
from logging.handlers import RotatingFileHandler

from config import (
    APP_NAME,
    SITE_ID,
    LANE_ID,
    CAMERA_TYPE,
    EVENT_QUEUE_SIZE,
    LOG_LEVEL,
    LOG_FILE,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    SHUTDOWN_TIMEOUT,
)
from processor import PlateProcessor
from led import LEDController
from event_queue import EventQueue
from cameras.factory import create_camera_listener


def setup_logger():
    os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def main():
    logger = setup_logger()

    logger.info("=" * 60)
    logger.info("%s starting", APP_NAME)
    logger.info("Site: %s | Lane: %s", SITE_ID, LANE_ID)
    logger.info("Camera mode: %s", CAMERA_TYPE)
    logger.info("=" * 60)

    processor = PlateProcessor()
    led = LEDController()
    event_queue = EventQueue(
        led_controller=led,
        max_size=EVENT_QUEUE_SIZE,
    )
    camera = None

    def on_plate_detected(event):
        logger.info(
            "Camera event | source=%s | camera=%s | plate=%s | id=%s",
            event.source,
            event.camera_id,
            event.plate,
            event.event_id,
        )

        display_text = processor.process(event)

        if display_text is not None:
            event_queue.add(display_text)

    try:
        if not led.connect():
            logger.error("LED initialization failed. Exiting.")
            return

        event_queue.start()

        camera = create_camera_listener(
            callback=on_plate_detected
        )

        logger.info("Middleware ready. Waiting for plate events.")
        camera.start()

    except KeyboardInterrupt:
        logger.info("Shutdown requested.")

    except Exception:
        logger.exception("Application failed.")

    finally:
        if camera is not None:
            try:
                camera.stop()
            except Exception:
                logger.exception("Error stopping camera listener.")

        event_queue.stop(timeout=SHUTDOWN_TIMEOUT)
        led.stop()

        logger.info("Middleware stopped.")


if __name__ == "__main__":
    main()