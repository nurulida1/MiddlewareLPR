from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlateEvent:
    """
    Represents a vehicle plate detection event from a camera.

    direction:
        IN  = Vehicle entering the parking area.
        OUT = Vehicle leaving the parking area.
    """

    plate: str
    camera_id: str
    event_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    source: Optional[str] = None
    direction: str = "IN"

    def __post_init__(self):
        # Ensure the timestamp always has a value.
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

        # Normalize and validate the direction.
        self.direction = str(self.direction).strip().upper()

        if self.direction not in {"IN", "OUT"}:
            raise ValueError(
                f"Invalid plate event direction: {self.direction!r}. "
                "Expected 'IN' or 'OUT'."
            )

        # Normalize the plate number.
        self.plate = str(self.plate).strip().upper()

        if not self.plate:
            raise ValueError(
                "Plate number cannot be empty."
            )
