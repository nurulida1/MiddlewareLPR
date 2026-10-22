
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
    LED_IN_SERIAL_PORT,
    LED_OUT_SERIAL_PORT,
    LED_SIMULATION_MODE,
    LED_AUTO_DETECT_PORTS,
    MQTT_TOPIC_PREFIX_IN,
    MQTT_TOPIC_PREFIX_OUT,
)

from processor import PlateProcessor
from led import LEDController
from event_queue import EventQueue
from cameras.factory import create_camera_listener


# ============================================================
# LED CONFIGURATION
# ============================================================

LED_INACTIVITY_TIMEOUT = 10.0


# ============================================================
# LOGGING
# ============================================================

def setup_logger():
    os.makedirs(
        os.path.dirname(LOG_FILE) or ".",
        exist_ok=True,
    )

    logger = logging.getLogger()
    logger.setLevel(
        getattr(logging, LOG_LEVEL.upper(), logging.DEBUG)
    )

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
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


# ============================================================
# COM PORT DETECTION
# ============================================================

def get_available_com_ports():
    """Return COM port names currently detected by Windows."""
    try:
        from serial.tools import list_ports

        return {
            port.device.upper()
            for port in list_ports.comports()
        }

    except ImportError as exc:
        raise RuntimeError(
            "pyserial is not installed. Run: "
            "python -m pip install pyserial"
        ) from exc


def validate_led_ports(logger):
    """
    Report configured COM ports.

    Missing ports generate warnings rather than stopping
    the entire middleware.
    """

    if LED_SIMULATION_MODE:
        logger.info(
            "LED simulation enabled. Physical COM ports "
            "will not be opened."
        )
        return set()

    if not LED_AUTO_DETECT_PORTS:
        logger.warning(
            "LED automatic COM-port detection is disabled. "
            "Configured ports will be attempted."
        )
        return None

    try:
        available_ports = get_available_com_ports()

    except RuntimeError:
        logger.exception(
            "Unable to enumerate Windows COM ports. "
            "LED initialization will be attempted individually."
        )
        return None

    logger.info(
        "COM ports detected by Windows: %s",
        ", ".join(sorted(available_ports)) or "None",
    )

    configured_ports = {
        "IN": LED_IN_SERIAL_PORT.strip().upper(),
        "OUT": LED_OUT_SERIAL_PORT.strip().upper(),
    }

    for direction, port in configured_ports.items():
        if port in available_ports:
            logger.info(
                "%s LED COM port detected: %s",
                direction,
                port,
            )
        else:
            logger.warning(
                "%s LED COM port not detected: %s. "
                "That LED will be unavailable for now.",
                direction,
                port,
            )

    return available_ports


# ============================================================
# LED INITIALIZATION
# ============================================================

def initialize_led(logger, direction, port, available_ports):
    """
    Initialize one LED controller safely.

    Returns the controller on success, otherwise None.
    """

    normalized_port = port.strip().upper()

    if (
        not LED_SIMULATION_MODE
        and available_ports is not None
        and normalized_port not in available_ports
    ):
        logger.warning(
            "%s LED skipped | port=%s | "
            "reason=COM port not detected by Windows",
            direction,
            normalized_port,
        )
        return None

    controller = LEDController(port=normalized_port)

    logger.info(
        "Initializing %s LED | port=%s",
        direction,
        normalized_port,
    )

    try:
        if controller.connect():
            logger.info(
                "%s LED initialized successfully | port=%s",
                direction,
                normalized_port,
            )
            return controller

        logger.error(
            "%s LED initialization failed | port=%s. "
            "Middleware will continue without this LED.",
            direction,
            normalized_port,
        )

    except Exception:
        logger.exception(
            "%s LED initialization raised an error | port=%s",
            direction,
            normalized_port,
        )

    try:
        controller.stop()
    except Exception:
        logger.exception(
            "Error cleaning up failed %s LED controller.",
            direction,
        )

    return None


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    logger = setup_logger()

    logger.info("=" * 60)
    logger.info("%s starting", APP_NAME)
    logger.info(
        "Site: %s | Default lane: %s",
        SITE_ID,
        LANE_ID,
    )
    logger.info("Camera mode: %s", CAMERA_TYPE)

    logger.info(
        "LED configuration | IN=%s | OUT=%s | simulation=%s",
        LED_IN_SERIAL_PORT,
        LED_OUT_SERIAL_PORT,
        LED_SIMULATION_MODE,
    )

    logger.info(
        "LED inactivity timeout: %.1fs",
        LED_INACTIVITY_TIMEOUT,
    )
    logger.info("=" * 60)

    available_ports = validate_led_ports(logger)

    processor = PlateProcessor()

    led_in = None
    led_out = None

    camera = None
    event_queue = None

    try:
        # ----------------------------------------------------
        # INITIALIZE IN AND OUT LED CONTROLLERS
        #
        # IN  = COM61
        # OUT = COM60
        #
        # This assumes two independent LED controllers/panels.
        # ----------------------------------------------------

        led_in = initialize_led(
            logger,
            "IN",
            LED_IN_SERIAL_PORT,
            available_ports,
        )

        led_out = initialize_led(
            logger,
            "OUT",
            LED_OUT_SERIAL_PORT,
            available_ports,
        )

        logger.info(
            "Dual LED mode | IN=%s | OUT=%s | simulation=%s",
            LED_IN_SERIAL_PORT,
            LED_OUT_SERIAL_PORT,
            LED_SIMULATION_MODE,
        )

        if led_in is None:
            logger.error(
                "IN LED unavailable | port=%s",
                LED_IN_SERIAL_PORT,
            )

        if led_out is None:
            logger.error(
                "OUT LED unavailable | port=%s",
                LED_OUT_SERIAL_PORT,
            )

        if not LED_SIMULATION_MODE:
            logger.warning(
                "Physical serial mode is enabled. Opening a COM port "
                "does not confirm that the LED accepts the command protocol."
            )

        # ----------------------------------------------------
        # EVENT QUEUE
        # ----------------------------------------------------

        event_queue = EventQueue(
            led_in_controller=led_in,
            led_out_controller=led_out,
            max_size=EVENT_QUEUE_SIZE,
            inactivity_timeout=LED_INACTIVITY_TIMEOUT,
        )

        # ----------------------------------------------------
        # CAMERA / MQTT EVENT CALLBACK
        # ----------------------------------------------------

        def on_plate_detected(event):
            direction = str(
                getattr(event, "direction", "") or ""
            ).strip().upper()

            if direction not in ("IN", "OUT"):
                logger.warning(
                    "Plate event rejected: invalid direction=%r | "
                    "source=%s | camera=%s | plate=%s. "
                    "Check MQTT topic-to-direction mapping.",
                    direction,
                    getattr(event, "source", "unknown"),
                    getattr(event, "camera_id", "unknown"),
                    getattr(event, "plate", ""),
                )
                return

            selected_port = (
                LED_IN_SERIAL_PORT
                if direction == "IN"
                else LED_OUT_SERIAL_PORT
            )

            selected_controller = (
                led_in
                if direction == "IN"
                else led_out
            )

            logger.info(
                "Camera event | direction=%s | selected_port=%s | "
                "source=%s | camera=%s | plate=%s | id=%s",
                direction,
                selected_port,
                getattr(event, "source", "unknown"),
                getattr(event, "camera_id", "unknown"),
                getattr(event, "plate", ""),
                getattr(event, "event_id", "unknown"),
            )

            display_text = processor.process(event)

            if display_text is None:
                logger.info(
                    "Plate ignored by processor | direction=%s",
                    direction,
                )
                return

            if selected_controller is None:
                logger.warning(
                    "Plate detected but LED unavailable | "
                    "direction=%s | port=%s | plate=%s",
                    direction,
                    selected_port,
                    display_text,
                )
                return

            queued = event_queue.add(
                display_text,
                direction=direction,
            )

            if not queued:
                logger.warning(
                    "Plate event was not queued | "
                    "direction=%s | plate=%s",
                    direction,
                    display_text,
                )

        # ----------------------------------------------------
        # START EVENT QUEUE AND CAMERA LISTENER
        # ----------------------------------------------------

        event_queue.start()

        camera = create_camera_listener(
            callback=on_plate_detected,
        )

        logger.info(
            "Middleware ready. Waiting for IN/OUT plate events."
        )

        camera.start()

    except KeyboardInterrupt:
        logger.info("Shutdown requested.")

    except Exception:
        logger.exception("Application failed.")

    finally:
        # ----------------------------------------------------
        # CLEAN SHUTDOWN
        # ----------------------------------------------------

        if camera is not None:
            try:
                camera.stop()
            except Exception:
                logger.exception(
                    "Error stopping camera listener."
                )

        if event_queue is not None:
            try:
                event_queue.stop(timeout=SHUTDOWN_TIMEOUT)
            except Exception:
                logger.exception(
                    "Error stopping event queue."
                )

        # Stop each controller only once.
        controllers = {
            id(controller): controller
            for controller in (led_in, led_out)
            if controller is not None
        }

        for controller in controllers.values():
            try:
                controller.stop()
            except Exception:
                logger.exception(
                    "Error stopping LED controller."
                )

        logger.info("Middleware stopped.")


if __name__ == "__main__":
    main()
