import logging
import time
import uuid

from cameras.base import (
    BaseCameraListener,
)

from models import (
    PlateEvent,
)

from config import (
    CAMERA_ID,
)


logger = logging.getLogger(
    "middleware"
)


class SimulationCameraListener(
    BaseCameraListener
):

    def start(
        self,
    ):

        self.running = True

        logger.info(
            "Simulation camera started | "
            "camera=%s",
            CAMERA_ID,
        )

        self._run_simulation()

    # ========================================================
    # SIMULATION
    # ========================================================

    def _run_simulation(
        self,
    ):

        test_events = [
            # plate, delay

            (
                "VAB 1234",
                1,
            ),

            # Duplicate

            (
                "VAB 1234",
                1,
            ),

            (
                "VAB 1234",
                1,
            ),

            # Different plate

            (
                "BPK 8888",
                1,
            ),

            (
                "PUTRA",
                1,
            ),

            (
                "12345",
                1,
            ),

            (
                "WXY 9876",
                1,
            ),
        ]

        for (
            plate,
            delay,
        ) in test_events:

            if not self.running:
                return

            time.sleep(
                delay
            )

            event = PlateEvent(
                plate=plate,
                camera_id=CAMERA_ID,
                event_id=str(
                    uuid.uuid4()
                ),
                source="simulation",
            )

            logger.info(
                "Simulated LPR event | "
                "camera=%s | "
                "plate=%s",
                CAMERA_ID,
                plate,
            )

            self.callback(
                event
            )

        logger.info(
            "Simulation completed | "
            "middleware remains active"
        )

        while self.running:

            time.sleep(
                1
            )