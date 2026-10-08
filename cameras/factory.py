from config import CAMERA_TYPE

from cameras.simulation import SimulationCameraListener
from cameras.bosch_mqtt import BoschMQTTListener


def create_camera_listener(callback):

    camera_type = CAMERA_TYPE.strip().lower()

    # Development / dummy simulation
    if camera_type == "simulation":

        return SimulationCameraListener(
            callback=callback
        )

    # Bosch camera via MQTT
    if camera_type == "bosch_mqtt":

        return BoschMQTTListener(
            callback=callback
        )

    raise ValueError(
        f"Unsupported CAMERA_TYPE: {CAMERA_TYPE}"
    )