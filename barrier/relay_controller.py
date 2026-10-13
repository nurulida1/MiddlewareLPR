
import logging
import time

logger = logging.getLogger(__name__)


class BarrierRelayController:
    """Simulate a barrier relay without physical hardware."""

    def __init__(self, pulse_seconds=0.5):
        self.pulse_seconds = pulse_seconds
        logger.info(
            "[SIMULATION] Barrier relay initialized. "
            "No hardware connected."
        )

    def trigger_open(self):
        """Display the intended relay pulse; do not operate hardware."""

        logger.info("[SIMULATION] Barrier OPEN request")
        logger.info("[SIMULATION] Relay output: ON")
        logger.info(
            "[SIMULATION] Pulse duration: %.1f seconds",
            self.pulse_seconds,
        )

        time.sleep(self.pulse_seconds)

        logger.info("[SIMULATION] Relay output: OFF")
        logger.info("[SIMULATION] OPEN pulse completed")

        return True

    def stop(self):
        logger.info("[SIMULATION] Barrier relay stopped")