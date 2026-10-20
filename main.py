
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
)

from processor import PlateProcessor
from led import LEDController
from event_queue import EventQueue
from cameras.factory import create_camera_listener

# BARRIER SUPPORT - TEMPORARILY DISABLED
# Keep this code commented out until we confirm whether
# barrier control is required.
#
# from config import (
#     SIMULATE_AUTHORISED_ACCESS,
#     BARRIER_CONTROL_ENABLED,
# )
# from barrier.relay_controller import BarrierRelayController
#
# BARRIER_SIMULATION_MODE = True


# Clear the LED after this many seconds without another
# accepted detection of the active plate.
LED_INACTIVITY_TIMEOUT = 10.0


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
    Report the configured COM ports.

    Missing ports generate warnings instead of stopping
    the application. Returns the detected port names.
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


def initialize_led(logger, direction, port, available_ports):
    """
    Initialize one LED controller safely.

    If a port is known to be missing, skip it rather than
    stopping the entire middleware.
    """

    if (
        not LED_SIMULATION_MODE
        and available_ports is not None
        and port.strip().upper() not in available_ports
    ):
        logger.warning(
            "%s LED skipped | port=%s | reason=COM port "
            "not detected by Windows",
            direction,
            port,
        )
        return None

    controller = LEDController(port=port)

    logger.info(
        "Initializing %s LED | port=%s",
        direction,
        port,
    )

    try:
        if controller.connect():
            logger.info(
                "%s LED initialized successfully | port=%s",
                direction,
                port,
            )
            return controller

        logger.error(
            "%s LED initialization failed | port=%s. "
            "Middleware will continue without this LED.",
            direction,
            port,
        )

    except Exception:
        logger.exception(
            "%s LED initialization raised an error | port=%s",
            direction,
            port,
        )

    try:
        controller.stop()
    except Exception:
        logger.exception(
            "Error cleaning up failed %s LED controller.",
            direction,
        )

    return None


def main():
    logger = setup_logger()

    logger.info("=" * 60)
    logger.info("%s starting", APP_NAME)
    logger.info("Site: %s | Default lane: %s", SITE_ID, LANE_ID)
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

    # BARRIER SUPPORT - TEMPORARILY DISABLED
    # logger.info(
    #     "Barrier simulation mode: %s",
    #     BARRIER_SIMULATION_MODE,
    # )

    logger.info("=" * 60)

    available_ports = validate_led_ports(logger)

    processor = PlateProcessor()

    # Start only the LED controllers whose ports are available.
    # A missing COM port must not stop MQTT or the event queue.
    led_in = None
    led_out = None

    camera = None
    event_queue = None

    # BARRIER SUPPORT - TEMPORARILY DISABLED
    # barrier = None

    try:
        led_in = initialize_led(
            logger,
            "IN",
            LED_IN_SERIAL_PORT,
            available_ports,
        )

        led_out = led_in
        logger.info(
            "Single LED mode | IN and OUT share port=%s",
            LED_IN_SERIAL_PORT,
        )

        # led_out = initialize_led(
        #     logger,
        #     "OUT",
        #     LED_OUT_SERIAL_PORT,
        #     available_ports,
        # )

        if led_in is None:
            logger.warning(
                "IN LED is unavailable. IN events will be "
                "logged, but cannot be displayed on that LED."
            )

        if led_out is None:
            logger.warning(
                "OUT LED is unavailable. OUT events will be "
                "logged, but cannot be displayed on that LED."
            )

        if not LED_SIMULATION_MODE:
            logger.warning(
                "Physical serial mode is enabled. Opening a "
                "COM port does not confirm that the LED panel "
                "works. Verify the CUSTronics RS485 protocol "
                "before relying on physical display output."
            )

        event_queue = EventQueue(
            led_in_controller=led_in,
            led_out_controller=led_out,
            max_size=EVENT_QUEUE_SIZE,
            inactivity_timeout=LED_INACTIVITY_TIMEOUT,
        )

        # BARRIER SUPPORT - TEMPORARILY DISABLED
        #
        # if BARRIER_SIMULATION_MODE:
        #     barrier = BarrierRelayController()
        #
        #     logger.warning(
        #         "Barrier is in SOFTWARE SIMULATION mode. "
        #         "No physical gate will be activated."
        #     )
        #
        # elif BARRIER_CONTROL_ENABLED:
        #     logger.critical(
        #         "Physical barrier control is not implemented. "
        #         "Keep BARRIER_CONTROL_ENABLED=False until relay "
        #         "hardware, wiring and authorisation are verified."
        #     )

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

            # BARRIER SUPPORT - TEMPORARILY DISABLED
            #
            # A detected plate alone does not prove that the
            # vehicle is authorised to enter or exit.
            #
            # if SIMULATE_AUTHORISED_ACCESS and barrier is not None:
            #     logger.warning(
            #         "[TEST ONLY] Simulating authorised access | "
            #         "direction=%s | plate=%s",
            #         direction,
            #         display_text,
            #     )
            #
            #     try:
            #         barrier.trigger_open()
            #     except Exception:
            #         logger.exception(
            #             "Simulated barrier action failed."
            #         )
            # else:
            #     logger.info(
            #         "Barrier not triggered for plate %s: "
            #         "authorisation has not been verified.",
            #         display_text,
            #     )

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

        # for direction, controller in (
        #     ("IN", led_in),
        #     ("OUT", led_out),
        # ):
        for controller in {id(led_in): led_in, id(led_out): led_out}.values():
            if controller is None:
                continue

            try:
                controller.stop()
            except Exception:
                logger.exception("Error stopping LED controller.")

            if controller is None:
                continue

            try:
                controller.stop()
            except Exception:
                logger.exception(
                    "Error stopping %s LED controller.",
                    direction,
                )

        # BARRIER SUPPORT - TEMPORARILY DISABLED
        #
        # if barrier is not None:
        #     try:
        #         barrier.stop()
        #     except Exception:
        #         logger.exception(
        #             "Error stopping barrier controller."
        #         )

        logger.info("Middleware stopped.")


if __name__ == "__main__":
    main()
