import logging
import queue
import threading
import time

from config import EVENT_QUEUE_SIZE


class EventQueue:
    """
    Queue and route recognised vehicle plates to LED displays.

    IN  -> IN LED controller (e.g. COM60)
    OUT -> OUT LED controller (e.g. COM61)

    IN display:
        Row 1 = plate in RED
        Row 2 = WELCOME in GREEN

    OUT display:
        Row 1 = plate in RED
        Row 2 = blank

    IMPORTANT:
    The inactivity timeout clears the display after a period
    without a new accepted event. It does not confirm that a
    vehicle has passed the barrier.
    """

    def __init__(
        self,
        led_in_controller=None,
        led_out_controller=None,
        max_size=EVENT_QUEUE_SIZE,
        inactivity_timeout=10.0,
    ):
        self.logger = logging.getLogger(__name__)

        self.led_in_controller = led_in_controller
        self.led_out_controller = led_out_controller

        self.events = queue.Queue(maxsize=max_size)
        self.inactivity_timeout = max(
            0.1,
            float(inactivity_timeout),
        )

        self._running = False
        self._worker_thread = None
        self._monitor_thread = None
        self._lock = threading.Lock()

        # Track the active display separately for IN and OUT.
        self._active_displays = {
            "IN": {
                "plate": None,
                "last_seen": None,
                "generation": 0,
            },
            "OUT": {
                "plate": None,
                "last_seen": None,
                "generation": 0,
            },
        }

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    def start(self):
        if self._running:
            self.logger.warning(
                "Event queue is already running."
            )
            return

        self._running = True

        self._worker_thread = threading.Thread(
            target=self._process_events,
            name="EventQueueWorker",
            daemon=True,
        )

        self._monitor_thread = threading.Thread(
            target=self._monitor_timeout,
            name="LEDTimeoutMonitor",
            daemon=True,
        )

        self._worker_thread.start()
        self._monitor_thread.start()

        self.logger.info(
            "Event queue started | max_size=%s | "
            "inactivity_timeout=%.1fs",
            self.events.maxsize,
            self.inactivity_timeout,
        )

    # --------------------------------------------------------
    # ADD EVENT
    # --------------------------------------------------------

    def add(self, display_text, direction="IN"):
        direction = str(direction or "").strip().upper()

        if display_text is None:
            self.logger.warning(
                "Event rejected | plate is None."
            )
            return False

        display_text = str(display_text).strip().upper()

        if direction not in ("IN", "OUT"):
            self.logger.warning(
                "Event rejected | invalid direction=%s",
                direction,
            )
            return False

        if not display_text:
            self.logger.warning(
                "Event rejected | empty plate."
            )
            return False

        event = {
            "plate": display_text,
            "direction": direction,
            "received_at": time.monotonic(),
        }

        try:
            self.events.put_nowait(event)

            self.logger.info(
                "Event queued | direction=%s | plate=%s",
                direction,
                display_text,
            )

            return True

        except queue.Full:
            self.logger.error(
                "Event queue full | event dropped | "
                "direction=%s | plate=%s",
                direction,
                display_text,
            )
            return False

    # --------------------------------------------------------
    # SELECT CONTROLLER
    # --------------------------------------------------------

    def _get_led_controller(self, direction):
        if direction == "IN":
            return self.led_in_controller

        if direction == "OUT":
            return self.led_out_controller

        return None

    # --------------------------------------------------------
    # PROCESS QUEUE
    # --------------------------------------------------------

    def _process_events(self):
        while self._running or not self.events.empty():
            try:
                event = self.events.get(timeout=0.5)

            except queue.Empty:
                continue

            try:
                self._handle_event(event)

            except Exception:
                self.logger.exception(
                    "Failed to process LED event."
                )

            finally:
                self.events.task_done()

    # --------------------------------------------------------
    # HANDLE EVENT
    # --------------------------------------------------------

    def _handle_event(self, event):
        plate = event["plate"]
        direction = event["direction"]

        controller = self._get_led_controller(direction)

        if controller is None:
            self.logger.error(
                "No LED controller configured | "
                "direction=%s | plate=%s",
                direction,
                plate,
            )
            return

        show_welcome = direction == "IN"

        # Update the timer for this direction only.
        with self._lock:
            display_state = self._active_displays[direction]

            display_state["plate"] = plate
            display_state["last_seen"] = time.monotonic()
            display_state["generation"] += 1

            generation = display_state["generation"]

        self.logger.info(
            "LED routing | direction=%s | plate=%s | "
            "port=%s | welcome=%s",
            direction,
            plate,
            getattr(controller, "port", "unknown"),
            show_welcome,
        )

        # Row 1: plate in RED.
        # IN shows WELCOME; OUT clears Row 2.

        if direction == "IN":
            displayed = controller.display(
                plate,
                row=1,
                colour="RED",
                show_welcome=True,
                row2_message="WELCOME",
            )
        else:
            displayed = controller.display(
                plate,
                row=1,
                colour="RED",
                show_welcome=False,
                row2_message="THANK YOU",
            )

        if displayed is False:
            self.logger.error(
                "LED display request failed | direction=%s | "
                "plate=%s | port=%s",
                direction,
                plate,
                getattr(controller, "port", "unknown"),
            )
            return

        self.logger.debug(
            "LED display request accepted | direction=%s | "
            "plate=%s | generation=%s",
            direction,
            plate,
            generation,
        )

    # --------------------------------------------------------
    # TIMEOUT MONITOR
    # --------------------------------------------------------

    def _monitor_timeout(self):
        while self._running:
            time.sleep(0.5)
            self._check_timeout()

    def _check_timeout(self):
        now = time.monotonic()
        expired_displays = []

        with self._lock:
            for direction, state in self._active_displays.items():
                plate = state["plate"]
                last_seen = state["last_seen"]

                if plate is None or last_seen is None:
                    continue

                elapsed = now - last_seen

                if elapsed < self.inactivity_timeout:
                    continue

                # Invalidate this display's current timeout state.
                expired_displays.append(
                    {
                        "direction": direction,
                        "plate": plate,
                        "generation": state["generation"],
                    }
                )

                state["plate"] = None
                state["last_seen"] = None

        for expired in expired_displays:
            direction = expired["direction"]
            plate = expired["plate"]

            self.logger.info(
                "LED inactivity timeout | clearing display | "
                "direction=%s | last_plate=%s",
                direction,
                plate,
            )

            self._clear_display(
                direction=direction,
                expected_generation=expired["generation"],
            )

    # --------------------------------------------------------
    # CLEAR DISPLAY
    # --------------------------------------------------------

    def _clear_display(
        self,
        direction,
        expected_generation=None,
    ):
        controller = self._get_led_controller(direction)

        if controller is None:
            self.logger.warning(
                "Cannot clear display | no controller | "
                "direction=%s",
                direction,
            )
            return False

        # Do not clear a display if a newer event arrived
        # after the timeout was detected.
        with self._lock:
            current_state = self._active_displays[direction]

            if (
                expected_generation is not None
                and current_state["generation"]
                != expected_generation
            ):
                self.logger.debug(
                    "Skipped stale timeout clear | "
                    "direction=%s",
                    direction,
                )
                return False

        try:
            cleared = controller.clear(row=1)

            if cleared is False:
                self.logger.warning(
                    "LED clear request failed | direction=%s | "
                    "port=%s",
                    direction,
                    getattr(controller, "port", "unknown"),
                )
                return False

            return True

        except Exception:
            self.logger.exception(
                "Failed to clear LED display | direction=%s",
                direction,
            )
            return False

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    def stop(self, timeout=5.0):
        self.logger.info("Stopping event queue...")
        self._running = False

        current_thread = threading.current_thread()

        if (
            self._worker_thread
            and self._worker_thread.is_alive()
            and self._worker_thread is not current_thread
        ):
            self._worker_thread.join(timeout=timeout)

        if (
            self._monitor_thread
            and self._monitor_thread.is_alive()
            and self._monitor_thread is not current_thread
        ):
            self._monitor_thread.join(timeout=timeout)

        if self._worker_thread and self._worker_thread.is_alive():
            self.logger.warning(
                "Event queue worker has not stopped yet."
            )

        if self._monitor_thread and self._monitor_thread.is_alive():
            self.logger.warning(
                "LED timeout monitor has not stopped yet."
            )

        self.logger.info("Event queue stopped.")
