
import logging
import time
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import serial

# ============================================================
# CONFIGURATION
# ============================================================

LED_IN_PORT = "COM60"

BAUDRATE = 9600
SERIAL_TIMEOUT = 1
WRITE_TIMEOUT = 2

DISPLAY_WIDTH = 16
WELCOME = "WELCOME"

PLATE_DISPLAY_SECONDS = 5
DISPLAY_COLOR = "0000"

MAX_RETRIES = 10
RETRY_DELAY = 0.2

SEND_REPEAT_COUNT = 4
SEND_REPEAT_DELAY = 0.2

PLATE_SEND_REPEAT_COUNT = 3
PLATE_SEND_REPEAT_DELAY = 0.5

CLEAR_SETTLE_DELAY = 0.1

# ============================================================
# LOGGING
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "manual_plate_led.log"

file_handler = TimedRotatingFileHandler(
    filename=str(LOG_FILE),
    when="midnight",
    interval=1,
    backupCount=1,
    encoding="utf-8",
    delay=True,
)
file_handler.suffix = "%Y-%m-%d"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), file_handler],
    force=True,
)

logger = logging.getLogger("manual_plate_led")

# ============================================================
# GLOBAL STATE
# ============================================================

led_in = None
state_lock = threading.RLock()
display_timer = None
display_version = 0


# ============================================================
# SERIAL CONNECTION
# ============================================================

def open_led(port):
    try:
        connection = serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=WRITE_TIMEOUT,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        logger.info("Serial connected successfully: %s", port)
        return connection

    except (serial.SerialException, OSError):
        logger.exception("Cannot open LED port %s", port)
        return None


# ============================================================
# NORMALIZE PLATE
# ============================================================

def normalize_plate(plate):
    return "".join(str(plate).upper().split())


# ============================================================
# DISPLAY TEXT: EXACTLY 16 CHARACTERS
# ============================================================

def build_display_text(message):
    text = str(message or "").upper()

    text = "".join(
        char for char in text
        if char.isascii() and (char.isalnum() or char == " ")
    )

    text = " ".join(text.split())
    result = text[:DISPLAY_WIDTH].ljust(DISPLAY_WIDTH)

    logger.info("DISPLAY TEXT: %r", result)
    logger.info("DISPLAY LENGTH: %d", len(result))

    return result


# ============================================================
# SERIAL COMMAND TRANSMISSION
# ============================================================

def write_led_command(connection, data, command_type):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            written = connection.write(data)
            connection.flush()

            logger.info(
                "%s WRITE ATTEMPT %d/%d: %d/%d bytes",
                command_type,
                attempt,
                MAX_RETRIES,
                written,
                len(data),
            )

            if written == len(data):
                logger.info("SERIAL WRITE SUCCESS: %s", command_type)
                return True

            logger.warning(
                "INCOMPLETE WRITE: %d/%d bytes",
                written,
                len(data),
            )

        except (
            serial.SerialException,
            serial.SerialTimeoutException,
            OSError,
        ):
            logger.exception(
                "%s write attempt %d/%d failed",
                command_type,
                attempt,
                MAX_RETRIES,
            )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    logger.error("SERIAL WRITE FAILED: %s", command_type)
    return False



def send_repeated_command(
    connection,
    data,
    command_type,
):
    repeat_count = (
        PLATE_SEND_REPEAT_COUNT
        if command_type == "PLATE"
        else SEND_REPEAT_COUNT
    )

    repeat_delay = (
        PLATE_SEND_REPEAT_DELAY
        if command_type == "PLATE"
        else SEND_REPEAT_DELAY
    )

    all_successful = True

    for attempt in range(1, repeat_count + 1):
        logger.info(
            "%s SEND %d/%d",
            command_type,
            attempt,
            repeat_count,
        )

        success = write_led_command(
            connection,
            data,
            command_type,
        )

        if not success:
            all_successful = False

        if attempt < repeat_count:
            time.sleep(repeat_delay)

    return all_successful


# ============================================================
# CLEAR LED PANEL
# ============================================================

def clear_led():
    clear_text = " " * DISPLAY_WIDTH
    command = f"001DIS={clear_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("CLEAR COMMAND: %r", command)

    success = send_repeated_command(
        led_in,
        data,
        "CLEAR",
    )

    time.sleep(CLEAR_SETTLE_DELAY)
    return success

# ============================================================
# DISPLAY MESSAGE
# ============================================================

def transmit_led_command(message, command_type):
    if led_in is None or not led_in.is_open:
        logger.error("COM60 is unavailable")
        return False

    logger.info("=" * 60)
    logger.info("COMMAND TYPE: %s", command_type)
    logger.info("DISPLAY MESSAGE: %s", message)

    if command_type != "STARTUP":
        if not clear_led():
            logger.error("Clear failed; skipping new display")
            return False

    display_text = build_display_text(message)

    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("ASCII COMMAND: %r", command)
    logger.info("HEX BYTES: %s", data.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(data))

    success = send_repeated_command(
        led_in,
        data,
        command_type,
    )

    if success:
        logger.info("DISPLAY COMMANDS SENT SUCCESSFULLY")
    else:
        logger.error("ONE OR MORE DISPLAY SENDS FAILED")

    return success


# ============================================================
# RESTORE STARTUP MESSAGE AFTER TIMEOUT
# ============================================================

def restore_startup_display(version):
    global display_timer, display_version

    with state_lock:
        if display_version != version:
            logger.info("Ignoring outdated display timer")
            return

        display_timer = None
        display_version += 1

        logger.info(
            "TIMEOUT: restoring startup message: %s",
            WELCOME,
        )

        transmit_led_command(WELCOME, "RESET_TO_STARTUP")


def schedule_startup_restore():
    global display_timer

    with state_lock:
        if display_timer is not None:
            display_timer.cancel()

        version = display_version

        timer = threading.Timer(
            PLATE_DISPLAY_SECONDS,
            restore_startup_display,
            args=(version,),
        )

        timer.daemon = True
        display_timer = timer
        timer.start()

        logger.info(
            "Restore WELCOME in %s seconds",
            PLATE_DISPLAY_SECONDS,
        )


# ============================================================
# REGISTER MANUAL PLATE
# ============================================================

def register_plate_event(plate):
    global display_version, display_timer

    plate = normalize_plate(plate)

    if not plate:
        logger.warning("Empty plate ignored")
        return

    # Two rows, 8 characters each:
    # Row 1: WELCOME
    # Row 2: Plate number
    message = f"{WELCOME:<8}{plate[:8]:<8}"

    with state_lock:
        display_version += 1

        if display_timer is not None:
            display_timer.cancel()
            display_timer = None

        logger.info(
            "MANUAL PLATE EVENT: plate=%s | message=%r",
            plate,
            message,
        )

        success = transmit_led_command(message, "PLATE")

        if success:
            schedule_startup_restore()


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    global led_in, display_version, display_timer

    try:
        logger.info("=" * 60)
        logger.info("Starting manual LED plate test")
        logger.info("LED PORT: %s", LED_IN_PORT)
        logger.info("STARTUP MESSAGE: %s", WELCOME)
        logger.info("DISPLAY WIDTH: %s", DISPLAY_WIDTH)
        logger.info("PLATE DISPLAY TIME: %s seconds",
                    PLATE_DISPLAY_SECONDS)
        logger.info("=" * 60)

        led_in = open_led(LED_IN_PORT)

        if led_in is None:
            logger.error("Cannot start: COM60 unavailable")
            return

        # Clear panel and show startup message
        clear_led()
        transmit_led_command(WELCOME, "STARTUP")

        print("\n====================================")
        print(" MANUAL LED PLATE TEST - COM60")
        print("====================================")
        print("Enter a plate number to display it.")
        print("Type CLEAR to clear the panel.")
        print("Type EXIT to quit.\n")

        while True:
            plate = input("Enter plate number: ").strip()

            if plate.upper() == "EXIT":
                break

            if plate.upper() == "CLEAR":
                with state_lock:
                    display_version += 1

                    if display_timer is not None:
                        display_timer.cancel()
                        display_timer = None

                    clear_led()

                continue

            if not plate:
                print("Please enter a plate number.")
                continue

            register_plate_event(plate)

    except KeyboardInterrupt:
        logger.info("Stopping application")

    except Exception:
        logger.exception("Application error")

    finally:
        with state_lock:
            if display_timer is not None:
                display_timer.cancel()
                display_timer = None

        if led_in is not None and led_in.is_open:
            led_in.close()
            logger.info("COM60 closed")

        logger.info("Application stopped")


if __name__ == "__main__":
    main()
