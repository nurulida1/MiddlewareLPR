import logging
from queue import Queue, Full, Empty
from threading import Thread, Event

from config import QUEUE_GET_TIMEOUT


class EventQueue:
    def __init__(self, led_controller, max_size=100):
        self.logger = logging.getLogger(__name__)
        self.led_controller = led_controller

        self.queue = Queue(maxsize=max_size)
        self.stop_event = Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return

        self.stop_event.clear()
        self.worker = Thread(
            target=self._worker,
            name="LED-Event-Queue",
            daemon=True,
        )
        self.worker.start()

        self.logger.info("LED event queue started.")

    def add(self, display_text):
        if not display_text:
            return False

        try:
            self.queue.put_nowait(str(display_text))
            self.logger.info(
                "Queued LED message: %s",
                display_text,
            )
            return True

        except Full:
            self.logger.error(
                "LED queue is full. Message dropped: %s",
                display_text,
            )
            return False

    def _worker(self):
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                display_text = self.queue.get(
                    timeout=QUEUE_GET_TIMEOUT
                )
            except Empty:
                continue

            try:
                success = self.led_controller.display(display_text)

                if not success:
                    self.logger.error(
                        "LED display failed for: %s",
                        display_text,
                    )

            except Exception:
                self.logger.exception("LED worker error.")

            finally:
                self.queue.task_done()

        self.logger.info("LED event queue worker stopped.")

    def stop(self, timeout=10):
        self.stop_event.set()

        if self.worker:
            self.worker.join(timeout=timeout)

            if self.worker.is_alive():
                self.logger.warning(
                    "LED queue worker is still running."
                )