import time
import uuid

from cameras.base import BaseCameraListener
from models import PlateEvent


class SimulationCameraListener(BaseCameraListener):
    def start(self):
        self.running = True
        print("Simulation camera started.")

        try:
            while self.running:
                event = PlateEvent(
                    plate="VAB 1234",
                    camera_id="SIM_CAMERA_01",
                    event_id=str(uuid.uuid4()),
                    source="simulation",
                )

                self.callback(event)
                time.sleep(10)

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        super().stop()
        print("Simulation camera stopped.")