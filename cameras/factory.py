import logging

from config import CAMERA_TYPE
from cameras.simulation import SimulationCameraListener
from cameras.bosch_mqtt import BoschMQTTListener


logger = logging.getLogger(__name__)


def create_camera_listener(callback):
    """
    Create the appropriate camera listener.

    Supported camera types:
    - simulation
    - bosch_mqtt
    """

    camera_type = CAMERA_TYPE.strip().lower()

    if camera_type == "simulation":
        logger.info("Creating simulation camera listener")

        return SimulationCameraListener(
            callback=callback
        )

    if camera_type == "bosch_mqtt":
        logger.info("Creating Bosch MQTT camera listener")

        return BoschMQTTListener(
            callback=callback
        )

    raise ValueError(
        f"Unsupported CAMERA_TYPE: {CAMERA_TYPE!r}. "
        "Supported values: 'simulation', 'bosch_mqtt'."
    )