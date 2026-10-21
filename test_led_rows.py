
import logging
import time
import serial


# ============================================================
# CONFIGURATION
# ============================================================

PORT = "COM61"
BAUDRATE = 9600

ROW_WIDTH = 8
FRAME_WIDTH = 16

WELCOME_MESSAGE = "THANKS"
PLATE_NUMBER = "PUTRAJAYA 1234"

GREEN_SUFFIX = "1100"

DISPLAY_SECONDS = 5
CLEAR_DISPLAY_SECONDS = 1

logger = logging.getLogger(__name__)


# ============================================================
# LOGGING
# ============================================================

def setup_logging():
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        "led_rs485_test.log",
        mode="w",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


# ============================================================
# SHORTEN LONG PLATE NUMBERS
# ============================================================

def shorten_plate(plate):
    plate = str(plate).strip().upper()

    # Special case: Putrajaya plate
    if plate.startswith("PUTRAJAYA"):
        # Extract the number after PUTRAJAYA.
        number = plate[len("PUTRAJAYA"):].strip()

        # Example: PUTRAJAYA 1234 -> PUT1234
        shortened = "PUT" + number

        if len(shortened) <= ROW_WIDTH:
            logger.info(
                "Shortened plate: %s -> %s",
                plate,
                shortened,
            )
            return shortened

    # Normal plates: keep unchanged if they fit.
    if len(plate) <= ROW_WIDTH:
        return plate

    # For other long plates, keep the first 8 characters.
    shortened = plate[:ROW_WIDTH]

    logger.info(
        "Plate exceeds %d characters: %s -> %s",
        ROW_WIDTH,
        plate,
        shortened,
    )

    return shortened


# ============================================================
# BUILD COMBINED DISPLAY MESSAGE
# ============================================================

def build_display_message(welcome, plate):
    welcome = str(welcome).strip().upper()
    plate = shorten_plate(plate)

    if not welcome.isascii() or not plate.isascii():
        raise ValueError("Messages must contain ASCII characters.")

    row1 = welcome[:ROW_WIDTH].ljust(ROW_WIDTH)
    row2 = plate[:ROW_WIDTH].ljust(ROW_WIDTH)

    combined = row1 + row2

    logger.info("ROW 1: %r", row1)
    logger.info("ROW 2: %r", row2)
    logger.info("COMBINED: %r", combined)

    return combined


# ============================================================
# BUILD COMMAND
# ============================================================

def build_command(message, colour_suffix):
    if not message.isascii():
        raise ValueError("Message must contain ASCII characters.")

    message = message[:FRAME_WIDTH].ljust(FRAME_WIDTH)

    command = f"001DIS={message}{colour_suffix}\r\n"
    return command.encode("ascii")


# ============================================================
# SEND COMMAND WITH ASCII AND HEX LOGGING
# ============================================================

def send_command(ser, step, message, colour_suffix):
    command_bytes = build_command(message, colour_suffix)

    logger.info("=" * 60)
    logger.info("STEP: %s", step)
    logger.info("DISPLAY TEXT: %r", message)
    logger.info("ASCII: %r", command_bytes.decode("ascii"))
    logger.info("HEX: %s", command_bytes.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(command_bytes))

    sent = ser.write(command_bytes)
    ser.flush()

    logger.info("SENT: %d/%d bytes", sent, len(command_bytes))


# ============================================================
# MAIN TEST
# ============================================================

def test_led():
    try:
        with serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            write_timeout=2,
        ) as ser:

            logger.info("Connected to %s", PORT)

            while True:
                combined_message = build_display_message(
                    WELCOME_MESSAGE,
                    PLATE_NUMBER,
                )

                send_command(
                    ser,
                    "DISPLAY THANKS + SHORTENED PLATE",
                    combined_message,
                    GREEN_SUFFIX,
                )

                time.sleep(DISPLAY_SECONDS)

                send_command(
                    ser,
                    "CLEAR DISPLAY",
                    "",
                    "0000",
                )

                time.sleep(CLEAR_DISPLAY_SECONDS)

    except KeyboardInterrupt:
        logger.info("Test stopped by user.")

    except serial.SerialException:
        logger.exception(
            "Cannot access %s. Close HTerm or other serial programs.",
            PORT,
        )

    except Exception:
        logger.exception("LED test failed.")

    finally:
        logger.info("Log file: led_rs485_test.log")


if __name__ == "__main__":
    setup_logging()
    test_led()
