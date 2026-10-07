from abc import (
    ABC,
    abstractmethod,
)


class BaseCameraListener(
    ABC
):

    def __init__(
        self,
        callback,
    ):

        self.callback = callback

        self.running = False

    @abstractmethod
    def start(
        self,
    ):
        pass

    def stop(
        self,
    ):

        self.running = False