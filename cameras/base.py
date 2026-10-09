from abc import ABC, abstractmethod


class BaseCameraListener(ABC):
    def __init__(self, callback):
        self.callback = callback
        self.running = False

    @abstractmethod
    def start(self):
        """Start listening for camera events."""
        raise NotImplementedError

    def stop(self):
        self.running = False