import logging
import time

import serial

from config import (
    LED_SIMULATION_MODE,
    LED_COLUMNS,
    SERIAL_PORT,
    BAUD_RATE,
    DATA_BITS,
    PARITY,
    STOP_BITS,
    SERIAL_TIMEOUT,
    RS485_MAX_RETRIES,
    RS485_RETRY_DELAY,
)


logger = logging.getLogger(
    "middleware"
)


class LEDController:

    def __init__(
        self,
    ):

        self.serial_connection = None

    # ========================================================
    # CONNECT
    # ========================================================

    def connect(
        self,
    ) -> bool:

        if LED_SIMULATION_MODE:

            logger.info(
                "LED simulation mode enabled"
            )

            return True

        bytesize_map = {
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }

        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }

        stopbits_map = {
            1: serial.STOPBITS_ONE,
            2: serial.STOPBITS_TWO,
        }

        parity = (
            str(PARITY)
            .strip()
            .upper()
        )

        # ----------------------------------------------------
        # VALIDATE SERIAL SETTINGS
        # ----------------------------------------------------

        if DATA_BITS not in bytesize_map:

            logger.error(
                "Invalid DATA_BITS | "
                "value=%s",
                DATA_BITS,
            )

            return False

        if parity not in parity_map:

            logger.error(
                "Invalid PARITY | "
                "value=%s",
                PARITY,
            )

            return False

        if STOP_BITS not in stopbits_map:

            logger.error(
                "Invalid STOP_BITS | "
                "value=%s",
                STOP_BITS,
            )

            return False

        self.disconnect()

        try:

            self.serial_connection = (
                serial.Serial(
                    port=SERIAL_PORT,
                    baudrate=BAUD_RATE,
                    bytesize=(
                        bytesize_map[
                            DATA_BITS
                        ]
                    ),
                    parity=(
                        parity_map[
                            parity
                        ]
                    ),
                    stopbits=(
                        stopbits_map[
                            STOP_BITS
                        ]
                    ),
                    timeout=SERIAL_TIMEOUT,
                    write_timeout=(
                        SERIAL_TIMEOUT
                    ),
                )
            )

            logger.info(
                "RS485 serial port opened | "
                "port=%s | "
                "baud=%s | "
                "data=%s | "
                "parity=%s | "
                "stop=%s",
                SERIAL_PORT,
                BAUD_RATE,
                DATA_BITS,
                parity,
                STOP_BITS,
            )

            return True

        except serial.SerialException as error:

            logger.error(
                "Unable to open RS485 port | "
                "port=%s | "
                "error=%s",
                SERIAL_PORT,
                error,
            )

            self.serial_connection = None

            return False

        except Exception:

            logger.exception(
                "Unexpected RS485 "
                "connection error"
            )

            self.serial_connection = None

            return False

    # ========================================================
    # STATUS
    # ========================================================

    def is_connected(
        self,
    ) -> bool:

        if LED_SIMULATION_MODE:
            return True

        return (
            self.serial_connection
            is not None
            and
            self.serial_connection.is_open
        )

    # ========================================================
    # BUILD CUSTronics MESSAGE
    # ========================================================

    def build_message(
        self,
        text: str,
    ) -> bytes:

        if not isinstance(
            text,
            str,
        ):

            raise TypeError(
                "LED text must be a string"
            )

        text = (
            text
            .strip()
            .upper()
        )

        if not text:

            raise ValueError(
                "LED text cannot be empty"
            )

        # Physical display protection.
        #
        # CUSTronics model:
        #
        # 2.2RGW-485-2x8-110
        #
        # 8 characters per line.

        if len(text) > LED_COLUMNS:

            raise ValueError(
                f"LED text exceeds "
                f"{LED_COLUMNS}-character "
                f"line limit: {text}"
            )

        # ----------------------------------------------------
        # ASCII
        # ----------------------------------------------------

        try:

            ascii_data = text.encode(
                "ascii"
            )

        except UnicodeEncodeError:

            raise ValueError(
                f"LED text contains "
                f"non-ASCII characters: {text}"
            )

        # ----------------------------------------------------
        # CUSTronics PROTOCOL
        # ----------------------------------------------------
        #
        # TEMPORARY:
        #
        # Raw ASCII only.
        #
        # Example:
        #
        # VAB1234
        #
        # ->
        #
        # b"VAB1234"
        #
        # decimal bytes:
        #
        # 86, 65, 66, 49, 50, 51, 52
        #
        #
        # Once CUSTronics provides the actual protocol,
        # this is the ONLY section that needs to be
        # changed for:
        #
        # - device address
        # - row
        # - red / green
        # - STX / ETX
        # - checksum
        # - clear display
        # - CR / LF
        #
        # Do not invent those values.

        return ascii_data

    # ========================================================
    # SEND
    # ========================================================

    def send(
        self,
        text: str,
    ) -> bool:

        try:

            message = (
                self.build_message(
                    text
                )
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            logger.error(
                "Invalid LED message | "
                "text=%s | "
                "error=%s",
                text,
                error,
            )

            return False

        # ----------------------------------------------------
        # SIMULATION
        # ----------------------------------------------------

        if LED_SIMULATION_MODE:

            logger.info(
                "LED SIMULATION | "
                "text=%s | "
                "ascii_bytes=%s",
                text,
                list(message),
            )

            return True

        # ----------------------------------------------------
        # REAL RS485
        # ----------------------------------------------------

        for attempt in range(
            1,
            RS485_MAX_RETRIES + 1,
        ):

            try:

                if not self.is_connected():

                    logger.warning(
                        "RS485 disconnected | "
                        "attempting reconnect"
                    )

                    if not self.connect():

                        raise ConnectionError(
                            "RS485 reconnect failed"
                        )

                bytes_written = (
                    self.serial_connection.write(
                        message
                    )
                )

                self.serial_connection.flush()

                if (
                    bytes_written
                    != len(message)
                ):

                    raise IOError(
                        "Incomplete RS485 write | "
                        f"expected={len(message)} | "
                        f"written={bytes_written}"
                    )

                logger.info(
                    "LED message sent | "
                    "text=%s | "
                    "bytes=%s | "
                    "written=%s | "
                    "attempt=%s",
                    text,
                    list(message),
                    bytes_written,
                    attempt,
                )

                return True

            except (
                serial.SerialException,
                serial.SerialTimeoutException,
                ConnectionError,
                IOError,
            ) as error:

                logger.error(
                    "RS485 send failed | "
                    "text=%s | "
                    "attempt=%s/%s | "
                    "error=%s",
                    text,
                    attempt,
                    RS485_MAX_RETRIES,
                    error,
                )

                self.disconnect()

                if (
                    attempt
                    < RS485_MAX_RETRIES
                ):

                    time.sleep(
                        RS485_RETRY_DELAY
                    )

            except Exception:

                logger.exception(
                    "Unexpected LED error | "
                    "text=%s",
                    text,
                )

                self.disconnect()

                return False

        logger.error(
            "LED delivery permanently failed | "
            "text=%s",
            text,
        )

        return False

    # ========================================================
    # DISCONNECT
    # ========================================================

    def disconnect(
        self,
    ):

        try:

            if (
                self.serial_connection
                is not None
                and
                self.serial_connection.is_open
            ):

                self.serial_connection.close()

                logger.info(
                    "RS485 serial port closed"
                )

        except Exception as error:

            logger.warning(
                "Error closing RS485 port | "
                "error=%s",
                error,
            )

        finally:

            self.serial_connection = None

    # ========================================================
    # CLOSE
    # ========================================================

    def close(
        self,
    ):

        self.disconnect()

        logger.info(
            "LED controller closed"
        )