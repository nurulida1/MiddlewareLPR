from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlateEvent:
    plate: str
    camera_id: str
    event_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    source: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)