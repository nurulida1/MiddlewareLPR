from config import (
    APP_NAME,
    SITE_ID,
    LANE_ID,
    CAMERA_TYPE,
    EVENT_QUEUE_SIZE,
)

from logger import (
    setup_logger,
)

from led import (
    LEDController,
)

from processor import (
    PlateProcessor,
)

from event_queue import (
    EventQueue,
)

from cameras.factory import (
    create_camera_listener,
)


# ============================================================
# LOGGER
# ============================================================

logger = setup_logger()


# ============================================================
# COMPONENTS
# ============================================================

processor = PlateProcessor()

led = LEDController()

event_queue = EventQueue(
    led_controller=led,
    max_size=EVENT_QUEUE_SIZE,
)

camera = None


# ============================================================
# LPR CALLBACK
# ============================================================

def on_plate_detected(
    event,
):

    logger.info(
        "LPR event received | "
        "source=%s | "
        "camera=%s | "
        "plate=%s | "
        "event_id=%s",
        event.source,
        event.camera_id,
        event.plate,
        event.event_id,
    )

    # --------------------------------------------------------
    # CLEAN + DUPLICATE PROTECTION
    # --------------------------------------------------------

    display_text = (
        processor.process(
            event
        )
    )

    if display_text is None:

        return

    # --------------------------------------------------------
    # QUEUE FOR LED
    # --------------------------------------------------------

    success = (
        event_queue.add(
            display_text
        )
    )

    if not success:

        logger.error(
            "Failed to queue plate | "
            "camera=%s | "
            "plate=%s",
            event.camera_id,
            display_text,
        )


# ============================================================
# MAIN
# ============================================================

def main():

    global camera

    logger.info(
        "=================================================="
    )

    logger.info(
        "%s",
        APP_NAME,
    )

    logger.info(
        "=================================================="
    )

    logger.info(
        "Site=%s | "
        "Lane=%s | "
        "CameraType=%s",
        SITE_ID,
        LANE_ID,
        CAMERA_TYPE,
    )

    # --------------------------------------------------------
    # LED
    # --------------------------------------------------------

    if not led.connect():

        logger.error(
            "Unable to initialize "
            "LED controller"
        )

        return

    # --------------------------------------------------------
    # QUEUE
    # --------------------------------------------------------

    event_queue.start()

    # --------------------------------------------------------
    # CAMERA
    # --------------------------------------------------------

    camera = (
        create_camera_listener(
            callback=on_plate_detected
        )
    )

    logger.info(
        "Middleware ready | "
        "waiting for LPR events"
    )

    camera.start()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        logger.info(
            "Shutdown requested by user"
        )

    except Exception:

        logger.exception(
            "Unexpected application error"
        )

    finally:

        logger.info(
            "Shutting down middleware..."
        )

        # ----------------------------------------------------
        # CAMERA
        # ----------------------------------------------------

        if camera is not None:

            try:

                camera.stop()

            except Exception:

                logger.exception(
                    "Error stopping "
                    "camera listener"
                )

        # ----------------------------------------------------
        # EVENT QUEUE
        # ----------------------------------------------------

        try:

            event_queue.stop()

        except Exception:

            logger.exception(
                "Error stopping "
                "event queue"
            )

        # ----------------------------------------------------
        # LED
        # ----------------------------------------------------

        try:

            led.close()

        except Exception:

            logger.exception(
                "Error closing "
                "LED controller"
            )

        logger.info(
            "Middleware shutdown complete"
        )