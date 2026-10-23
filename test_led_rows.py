import logging
import time
import serial

# ============================================================
# CONFIGURATION
# ============================================================

PORT = "COM60"
BAUDRATE = 9600

ROW_WIDTH = 8

WELCOME_MESSAGE = "WELCOME"
PLATE_NUMBER = "PUTRAJAYA 1234"

GREEN_SUFFIX = "1100"
RED_SUFFIX = "2200"

COMMAND_INTERVAL = 4.0

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
# SHORTEN PLATE NUMBER
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

    if len(plate) <= ROW_WIDTH:
        return plate

    shortened = plate[:ROW_WIDTH]

    logger.info(
        "Plate shortened: %s -> %s",
        plate,
        shortened,
    )
    return shortened


# ============================================================
# BUILD ROW COMMAND
# Format: 001DIS=MESSAGE1100<CR><LF>
#          002DIS=MESSAGE2200<CR><LF>
# ============================================================

def build_row_command(row_number, message, colour_suffix):
    if row_number not in (1, 2):
        raise ValueError("Row number must be 1 or 2.")

    if colour_suffix not in (GREEN_SUFFIX, RED_SUFFIX):
        raise ValueError("Invalid colour suffix.")

    message = str(message).strip().upper()

    if not message.isascii():
        raise ValueError("Message must contain ASCII characters.")

    command = (
        f"00{row_number}DIS="
        f"{message}"
        f"{colour_suffix}\r\n"
    )

    return command.encode("ascii")


# ============================================================
# SEND COMMAND
# ============================================================

def send_row_command(ser, row_number, message, colour_suffix):
    command_bytes = build_row_command(
        row_number=row_number,
        message=message,
        colour_suffix=colour_suffix,
    )

    logger.info("=" * 60)
    logger.info("ROW: %d", row_number)
    logger.info("MESSAGE: %s", message)
    logger.info("ASCII: %r", command_bytes.decode("ascii"))
    logger.info("HEX: %s", command_bytes.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(command_bytes))

    sent = ser.write(command_bytes)
    ser.flush()

    logger.info(
        "SERIAL WRITE: %d/%d bytes",
        sent,
        len(command_bytes),
    )

    if sent != len(command_bytes):
        raise IOError("Incomplete serial write.")


# ============================================================
# MAIN TEST
# 1. ROW 2: PLATE NUMBER IN RED
# 2. ROW 1: WELCOME IN GREEN
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
            logger.info("Baud rate: %d", BAUDRATE)

            # ------------------------------------------------
            # STEP 1: ROW 2 - PLATE NUMBER IN RED
            # Expected format:
            # 002DIS=PUT12342200<CR><LF>
            # ------------------------------------------------

            row2_message = shorten_plate(PLATE_NUMBER)

            send_row_command(
                ser=ser,
                row_number=2,
                message=row2_message,
                colour_suffix=RED_SUFFIX,
            )

            logger.info(
                "Waiting %.1f seconds before next command...",
                COMMAND_INTERVAL,
            )
            time.sleep(COMMAND_INTERVAL)

            # ------------------------------------------------
            # STEP 2: ROW 1 - WELCOME IN GREEN
            # Expected format:
            # 001DIS=WELCOME1100<CR><LF>
            # ------------------------------------------------

            send_row_command(
                ser=ser,
                row_number=1,
                message=WELCOME_MESSAGE,
                colour_suffix=GREEN_SUFFIX,
            )

            logger.info("Both commands sent.")
            logger.info("No clear command was sent.")

            input(
                "Check the physical LED display, "
                "then press Enter to exit..."
            )

    except KeyboardInterrupt:
        logger.info("Test stopped by user.")

    except serial.SerialException:
        logger.exception(
            "Cannot access %s. Close HTerm or PowerLED first.",
            PORT,
        )

    except Exception:
        logger.exception("LED test failed.")

    finally:
        logger.info("Log file: led_rs485_test.log")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    setup_logging()
    test_led()