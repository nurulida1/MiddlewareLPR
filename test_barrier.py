
import logging

from barrier.relay_controller import BarrierRelayController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

barrier = BarrierRelayController()

try:
    barrier.trigger_open()
finally:
    barrier.stop()