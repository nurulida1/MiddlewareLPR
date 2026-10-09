import logging
import time

from config import (
    LED_SIMULATION_MODE,
    SERIAL_PORT,
    BAUD_RATE,
    DATA_BITS,
    PARITY,
    STOP_BITS,
    SERIAL_TIMEOUT,
    RS485_MAX_RETRIES,
    RS485_RETRY_DELAY,
)


class LEDController:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.serial_connection = None

    def connect(self):
        if LED_SIMULATION_MODE:
            self.logger.warning(
                "LED simulation mode enabled. "
                "No data will be sent to the physical LED."
            )
            return True

        try:
            import serial

            byte_size_map = {
                5: serial.FIVEBITS,
                6: serial.SIXBITS,
                7: serial.SEVENBITS,
                8: serial.EIGHTBITS,
            }

            parity_map = {
                "N": serial.PARITY_NONE,
                "E": serial.PARITY_EVEN,
                "O": serial.PARITY_ODD,
            }

            stop_bits_map = {
                1: serial.STOPBITS_ONE,
                2: serial.STOPBITS_TWO,
            }

            self.serial_connection = serial.Serial(
                port=SERIAL_PORT,
                baudrate=BAUD_RATE,
                bytesize=byte_size_map[DATA_BITS],
                parity=parity_map[PARITY],
                stopbits=stop_bits_map[STOP_BITS],
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT,
            )

            self.logger.info(
                "Serial port opened: %s at %s baud",
                SERIAL_PORT,
                BAUD_RATE,
            )
            return True

        except Exception:
            self.logger.exception(
                "Unable to open serial port %s",
                SERIAL_PORT,
            )
            return False

    def display(self, text):
        message = str(text).strip()

        if not message:
            return False

        if LED_SIMULATION_MODE:
            self.logger.info("[LED SIMULATION] Display: %s", message)
            return True

        if (
            self.serial_connection is None
            or not self.serial_connection.is_open
        ):
            self.logger.error("Serial connection is not open.")
            return False

        # EXAMPLE ONLY. Replace with the actual CUSTronics frame.
        # Do not assume plain text + CRLF is the controller's protocol.
        payload = (message + "\r\n").encode("ascii", errors="strict")

        # Show exactly what will be transmitted
        self.logger.info("ASCII text to send: %r", message)
        self.logger.info("ASCII bytes: %s", payload.hex(" ").upper())
        self.logger.info("Byte count: %d", len(payload))

        for attempt in range(1, RS485_MAX_RETRIES + 1):
            try:
                bytes_written = self.serial_connection.write(payload)
                self.serial_connection.flush()

                self.logger.info(
                    "Serial write completed: %d/%d bytes to %s",
                    bytes_written,
                    len(payload),
                    SERIAL_PORT,
                )
                return bytes_written == len(payload)

            except Exception:
                self.logger.exception(
                    "Serial write failed (attempt %d)",
                    attempt,
                )

                if attempt < RS485_MAX_RETRIES:
                    time.sleep(RS485_RETRY_DELAY)

        return False

    def disconnect(self):
        if self.serial_connection is not None:
            try:
                if self.serial_connection.is_open:
                    self.serial_connection.close()
                    self.logger.info("Serial port closed.")
            except Exception:
                self.logger.exception("Error closing serial port.")

    def stop(self):
        self.disconnect()