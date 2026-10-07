import logging
import queue
import threading

from config import (
    QUEUE_GET_TIMEOUT,
    SHUTDOWN_TIMEOUT,
)


logger = logging.getLogger(
    "middleware"
)


class EventQueue:

    def __init__(
        self,
        led_controller,
        max_size=100,
    ):

        self.led_controller = (
            led_controller
        )

        self.queue = queue.Queue(
            maxsize=max_size
        )

        self.running = False

        self.worker = None

    # ========================================================
    # START
    # ========================================================

    def start(
        self,
    ):

        if self.running:
            return

        self.running = True

        self.worker = threading.Thread(
            target=self._worker,
            name="LEDQueueWorker",
            daemon=True,
        )

        self.worker.start()

        logger.info(
            "Event queue started | "
            "max_size=%s",
            self.queue.maxsize,
        )

    # ========================================================
    # ADD
    # ========================================================

    def add(
        self,
        text: str,
    ) -> bool:

        if not self.running:

            logger.error(
                "Cannot queue LED message | "
                "queue is not running"
            )

            return False

        try:

            self.queue.put_nowait(
                text
            )

            logger.info(
                "LED message queued | "
                "text=%s | "
                "queue_size=%s",
                text,
                self.queue.qsize(),
            )

            return True

        except queue.Full:

            logger.error(
                "Event queue full | "
                "text=%s",
                text,
            )

            return False

    # ========================================================
    # WORKER
    # ========================================================

    def _worker(
        self,
    ):

        logger.info(
            "Event queue worker started"
        )

        while (
            self.running
            or not self.queue.empty()
        ):

            try:

                text = self.queue.get(
                    timeout=QUEUE_GET_TIMEOUT
                )

            except queue.Empty:

                continue

            try:

                success = (
                    self.led_controller.send(
                        text
                    )
                )

                if not success:

                    logger.error(
                        "LED delivery failed | "
                        "text=%s",
                        text,
                    )

            except Exception:

                logger.exception(
                    "Unexpected queue worker "
                    "error | text=%s",
                    text,
                )

            finally:

                self.queue.task_done()

        logger.info(
            "Event queue worker exited"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self,
    ):

        if (
            not self.running
            and self.worker is None
        ):

            return

        logger.info(
            "Stopping event queue..."
        )

        self.running = False

        if (
            self.worker is not None
            and self.worker.is_alive()
        ):

            self.worker.join(
                timeout=SHUTDOWN_TIMEOUT
            )

            if self.worker.is_alive():

                logger.warning(
                    "Event queue worker did not "
                    "stop within %s seconds",
                    SHUTDOWN_TIMEOUT,
                )

        self.worker = None

        logger.info(
            "Event queue stopped"
        )