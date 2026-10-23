
import logging
import time
import serial
import threading

from config import (
    LED_IN_SERIAL_PORT,
    LED_OUT_SERIAL_PORT,
    LED_SIMULATION_MODE,
    LED_AUTO_DETECT_PORTS,
)

# ============================================================
# CONFIGURATION
# ============================================================

BAUDRATE = 9600
ROW_WIDTH = 8
FRAME_WIDTH = 16

DEFAULT_WELCOME_MESSAGE = "THANKS"

GREEN_SUFFIX = "1100"
YELLOW_SUFFIX = "2200"

# 0000 was supplied as a possible clear/off command.
# Confirm with CUSTronics before relying on it.
CLEAR_SUFFIX = "0000"

DISPLAY_SECONDS = 5
CLEAR_DISPLAY_SECONDS = 1

LED_SEND_ATTEMPTS = 3
LED_RETRY_DELAY = 0.3

# Allow the physical LED time to update before the next message.
LED_COMMAND_INTERVAL = 2.0

logger = logging.getLogger(__name__)


# ============================================================
# LOGGING
# ============================================================

def setup_logging():
    if logger.handlers:
        return

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


# ============================================================
# SHORTEN LONG PLATE NUMBERS
# ============================================================

def shorten_plate(plate):
    plate = str(plate).strip().upper()

    if plate.startswith("PUTRAJAYA"):
        number = plate[len("PUTRAJAYA"):].strip()
        shortened = "PUT" + number

        if len(shortened) <= ROW_WIDTH:
            logger.info(
                "Shortened plate: %s -> %s",
                plate,
                shortened,
            )
            return shortened

        logger.warning(
            "Putrajaya plate is too long for the 8-character limit: %s",
            shortened,
        )

    if len(plate) <= ROW_WIDTH:
        return plate

    shortened = plate[:ROW_WIDTH]

    logger.warning(
        "Plate exceeds %d characters: %s -> %s",
        ROW_WIDTH,
        plate,
        shortened,
    )

    return shortened


# ============================================================
# BUILD ONE COMBINED 16-CHARACTER MESSAGE
# ============================================================

def build_display_message(welcome, plate):
    welcome = str(welcome).strip().upper()[:ROW_WIDTH]
    plate = shorten_plate(plate)

    if not welcome.isascii() or not plate.isascii():
        raise ValueError("Display messages must contain ASCII characters.")

    first_part = welcome.ljust(ROW_WIDTH)
    second_part = plate.ljust(ROW_WIDTH)

    combined = first_part + second_part

    logger.info("FIRST 8 CHARACTERS: %r", first_part)
    logger.info("NEXT 8 CHARACTERS:  %r", second_part)
    logger.info("COMBINED MESSAGE:   %r", combined)

    return combined


# ============================================================
# BUILD THE SERIAL COMMAND
# ============================================================



def build_command(message, colour_suffix):
    message = str(message)

    if not message.isascii():
        raise ValueError("Message must contain ASCII characters.")

    if colour_suffix not in (
        GREEN_SUFFIX,
        YELLOW_SUFFIX,
        CLEAR_SUFFIX,
    ):
        raise ValueError(
            f"Unsupported colour suffix: {colour_suffix}"
        )

    # The LED requires exactly 16 display characters.
    # Short messages are padded with spaces.
    # Long messages are limited to 16 characters.
    display_text = message[:FRAME_WIDTH].ljust(FRAME_WIDTH)

    command = f"001DIS={display_text}{colour_suffix}\r\n"

    return command.encode("ascii")



# ============================================================
# SERIAL LED CONTROLLER
# ============================================================

class LEDController:
    def __init__(
        self,
        port=None,
        baudrate=BAUDRATE,
        simulation=None,
        **kwargs,
    ):
        setup_logging()

        self.port = port or LED_IN_SERIAL_PORT
        self.baudrate = baudrate

        self.simulation = (
            LED_SIMULATION_MODE
            if simulation is None
            else simulation
        )

        self.serial_connection = None
        self.connected = False
        self._serial_lock = threading.Lock()

        self._last_send_time = 0.0

        # Avoid opening the same serial port twice.
        self._last_message = None
        self._last_colour_suffix = None

        if LED_AUTO_DETECT_PORTS:
            logger.info("Serial auto-detection is enabled.")
            logger.info("Configured LED port: %s", self.port)

    # --------------------------------------------------------
    # CONNECT
    # --------------------------------------------------------

    def connect(self):
        if self.simulation:
            logger.warning(
                "LED simulation mode is enabled; no physical command will be sent."
            )
            self.connected = True
            return True

        if self.serial_connection and self.serial_connection.is_open:
            self.connected = True
            return True

        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,
                write_timeout=2,
            )

            self.connected = True
            logger.info(
                "Connected to physical LED on %s at %d baud.",
                self.port,
                self.baudrate,
            )
            return True

        except serial.SerialException:
            self.connected = False
            logger.exception(
                "Cannot open %s. Close HTerm or any other program using this port.",
                self.port,
            )
            return False

    # --------------------------------------------------------
    # SEND ONE COMMAND
    # --------------------------------------------------------

    # Comment (22/10 - 8.30 AM)
    # def _send_rs485_command(self, message, colour_suffix):
    #     if self.simulation:
    #         logger.info(
    #             "[SIMULATION] Would display %r using suffix %s",
    #             message,
    #             colour_suffix,
    #         )
    #         return True

    #     if not self.connected or not self.serial_connection:
    #         logger.error("LED is not connected; command was not sent.")
    #         return False

    #     try:
    #         command_bytes = build_command(message, colour_suffix)

    #         logger.info("=" * 60)
    #         logger.info("DISPLAY TEXT: %r", message)
    #         logger.info("ASCII: %r", command_bytes.decode("ascii"))
    #         logger.info("HEX: %s", command_bytes.hex(" ").upper())
    #         logger.info("BYTE COUNT: %d", len(command_bytes))
            
    #         sent = self.serial_connection.write(command_bytes)
    #         self.serial_connection.flush()

    #         # Give the LED controller a short time to process the command.
    #         time.sleep(0.1)


    #         logger.info(
    #             "SERIAL WRITE: %d/%d bytes",
    #             sent,
    #             len(command_bytes),
    #         )

    #         if sent != len(command_bytes):
    #             logger.error("Not all command bytes were written.")
    #             return False

    #         self._last_message = message
    #         self._last_colour_suffix = colour_suffix

    #         # A successful write only confirms that Windows accepted
    #         # the bytes. It does not confirm that the LED understood them.
    #         return True

    #     except (serial.SerialException, ValueError):
    #         logger.exception("Failed to send the LED command.")
    #         return False


    
    def _send_rs485_command(self, message, colour_suffix):
        try:
            command_bytes = build_command(message, colour_suffix)
            command_ascii = command_bytes.decode("ascii")

            logger.info("=" * 60)
            logger.info("LED PORT: %s", self.port)
            logger.info(
                "DISPLAY TEXT (16 CHARACTERS): %r",
                message[:FRAME_WIDTH].ljust(FRAME_WIDTH),
            )
            logger.info("COLOUR SUFFIX: %s", colour_suffix)
            logger.info("ASCII: %r", command_ascii)
            logger.info(
                "HEX: %s",
                " ".join(f"{byte:02X}" for byte in command_bytes),
            )
            logger.info("BYTE COUNT: %d", len(command_bytes))
            logger.info("CR = 0D | LF = 0A")

            if self.simulation:
                logger.info("[SIMULATION] No physical RS485 bytes sent.")
                return True

            if (
                not self.connected
                or self.serial_connection is None
                or not self.serial_connection.is_open
            ):
                logger.error("LED is not connected; command was not sent.")
                return False

            with self._serial_lock:
                # Wait before sending another command to this LED.
                elapsed = time.monotonic() - self._last_send_time
                remaining = LED_COMMAND_INTERVAL - elapsed

                if remaining > 0:
                    logger.info(
                        "Waiting %.1f seconds before next LED command.",
                        remaining,
                    )
                    time.sleep(remaining)

                for attempt in range(1, LED_SEND_ATTEMPTS + 1):
                    logger.info(
                        "LED transmission attempt %d/%d",
                        attempt,
                        LED_SEND_ATTEMPTS,
                    )

                    sent = self.serial_connection.write(command_bytes)
                    self.serial_connection.flush()
                    self._last_send_time = time.monotonic()

                    logger.info(
                        "SERIAL WRITE: %d/%d bytes",
                        sent,
                        len(command_bytes),
                    )

                    if sent != len(command_bytes):
                        logger.error("Incomplete serial write.")
                        return False

                    if attempt < LED_SEND_ATTEMPTS:
                        time.sleep(LED_RETRY_DELAY)

            self._last_message = message
            self._last_colour_suffix = colour_suffix
            logger.info(
                "All %d display command transmissions completed. "
                "Physical display acceptance is not confirmed.",
                LED_SEND_ATTEMPTS,
            )
            return True

        except (serial.SerialException, OSError, ValueError):
            logger.exception("Failed to build or send LED command.")
            return False

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    # def display(
    #     self,
    #     text,
    #     row=None,
    #     colour="GREEN",
    #     show_welcome=True,
    #     row2_message=None,
    #     **kwargs,
    # ):
    #     plate = shorten_plate(text)

    #     # The entire 16-character message uses one colour suffix.
    #     colour_name = str(colour).strip().upper()

    #     colour_suffixes = {
    #         "GREEN": GREEN_SUFFIX,
    #         "YELLOW": YELLOW_SUFFIX,
    #     }

    #     if colour_name not in colour_suffixes:
    #         logger.error(
    #             "Colour %r is not configured with a confirmed command. "
    #             "No physical command was sent.",
    #             colour_name,
    #         )
    #         return False

    #     welcome = (
    #         row2_message
    #         if row2_message is not None
    #         else DEFAULT_WELCOME_MESSAGE
    #     )

    #     if not show_welcome and row2_message is None:
    #         welcome = DEFAULT_WELCOME_MESSAGE

    #     message = build_display_message(welcome, plate)
    #     colour_suffix = colour_suffixes[colour_name]

    #     if self.simulation:
    #         return self._send_rs485_command(message, colour_suffix)

    #     if not self.connected and not self.connect():
    #         return False

    #     return self._send_rs485_command(message, colour_suffix)
  
    
    def display(
        self,
        text,
        row=None,
        colour="YELLOW",
        show_welcome=True,
        row2_message=None,
        **kwargs,
    ):
        plate = shorten_plate(text)

        if not plate or not plate.isascii():
            logger.error("Invalid or empty plate: %r", text)
            return False

        # Choose the greeting.
        welcome = (
            row2_message
            if row2_message is not None
            else DEFAULT_WELCOME_MESSAGE
        )

        # Combine greeting and plate into exactly 16 characters.
        message = build_display_message(welcome, plate)

        # Use one colour for the entire message.
        colour_name = str(kwargs.get("color", colour)).strip().upper()

        colour_suffixes = {
            "GREEN": GREEN_SUFFIX,
            "YELLOW": YELLOW_SUFFIX,
        }

        colour_suffix = colour_suffixes.get(colour_name)

        if colour_suffix is None:
            logger.error("Unsupported display colour: %s", colour_name)
            return False

        if self.simulation:
            return self._send_rs485_command(message, colour_suffix)

        if not self.connected and not self.connect():
            return False

        return self._send_rs485_command(message, colour_suffix)

    # --------------------------------------------------------
    # CLEAR DISPLAY
    # --------------------------------------------------------

    # def clear(self):
    #     logger.warning(
    #         "Clear uses suffix 0000, which must be confirmed by CUSTronics."
    #     )

    #     if self.simulation:
    #         logger.info("[SIMULATION] Clear requested.")
    #         self._last_message = None
    #         return True

    #     if not self.connected and not self.connect():
    #         return False

    #     # Sends 16 spaces using the supplied 0000 suffix.
    #     result = self._send_rs485_command("", CLEAR_SUFFIX)

    #     if result:
    #         self._last_message = None

    #     return result

    # Test retry 3-4 times to clear led
    # def clear(self):
    #     logger.warning(
    #         "Clear uses suffix 0000, which must be confirmed by CUSTronics."
    #     )

    #     if self.simulation:
    #         logger.info("[SIMULATION] Clear requested; no physical bytes sent.")
    #         self._last_message = None
    #         self._last_colour_suffix = None
    #         return True

    #     if not self.connected and not self.connect():
    #         return False

    #     max_attempts = 4
    #     retry_delay = 0.3

    #     for attempt in range(1, max_attempts + 1):
    #         logger.info(
    #             "Sending LED clear command | attempt=%s/%s",
    #             attempt,
    #             max_attempts,
    #         )

    #         result = self._send_rs485_command("", CLEAR_SUFFIX)

    #         if result:
    #             self.logger_clear_success(attempt)
    #             self._last_message = None
    #             self._last_colour_suffix = None
    #             return True

    #         if attempt < max_attempts:
    #             time.sleep(retry_delay)

    #     logger.error(
    #         "Clear command failed after %s attempts.",
    #         max_attempts,
    #     )
    #     return False
   
    
    def clear(self):
        """Test clearing the full display, then the plate section."""

        if self.simulation:
            logger.info("[SIMULATION] Clear requested; no physical bytes sent.")
            self._last_message = None
            self._last_colour_suffix = None
            return True

        if not self.connected and not self.connect():
            logger.error("Cannot clear LED: connection failed.")
            return False

        # Test 1: Clear the complete 16-character display.
        logger.info("CLEAR TEST 1: Sending full blank command.")
        full_blank = " " * 16

        result = self._send_rs485_command(full_blank, CLEAR_SUFFIX)

        if not result:
            return False

        time.sleep(0.5)

        # Test 2: Send a command with the first 8 characters blank
        # and the second 8 characters set to spaces.
        # This is a diagnostic test, not a confirmed vendor protocol.
        logger.info("CLEAR TEST 2: Sending blank command again.")
        result = self._send_rs485_command(" " * 16, CLEAR_SUFFIX)

        if result:
            self._last_message = None
            self._last_colour_suffix = None
            logger.info("Clear test commands transmitted.")

        return result

    # --------------------------------------------------------
    # DISCONNECT
    # --------------------------------------------------------

    def disconnect(self):
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                logger.info("Disconnected from %s.", self.port)

        except serial.SerialException:
            logger.exception("Error while closing the LED serial port.")

        finally:
            self.serial_connection = None
            self.connected = False

    # --------------------------------------------------------
    # COMPATIBILITY HELPERS
    # --------------------------------------------------------

    def stop(self):
        self.disconnect()

    def close(self):
        self.disconnect()


# ============================================================
# STANDALONE TEST
# ============================================================


if __name__ == "__main__":
    setup_logging()

    controller = LEDController(
        port="COM60",
        simulation=False,
    )

    try:
        if controller.connect():
            controller.display(
                "ABC123",
                colour="GREEN",
            )

            input("Check the LED message. Press Enter to send CLEAR: ")

            controller.clear()

            input("Check the physical LED, then press Enter to exit: ")

    except KeyboardInterrupt:
        logger.info("LED test stopped.")

    finally:
        controller.disconnect()
