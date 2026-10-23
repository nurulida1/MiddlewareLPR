
import json
import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import paho.mqtt.client as mqtt
import serial

# ============================================================
# CONFIGURATION
# ============================================================

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
MQTT_QOS = 1

TOPIC_IN = "parking/bosch/in"
TOPIC_OUT = "parking/bosch/out"

LED_IN_PORT = "COM60"
LED_OUT_PORT = "COM61"

BAUDRATE = 9600
SERIAL_TIMEOUT = 1
WRITE_TIMEOUT = 2

SIMULATION = False

DISPLAY_WIDTH = 16

WELCOME = "WELCOME"
THANKS = "THANKS"

# Keep the existing LED command suffix.
# Confirm its colour meaning with the LED vendor.
DISPLAY_COLOR = "0000"

MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Restore WELCOME / THANKS after no new plate for this many seconds.
DISPLAY_RESET_SECONDS = 3

# Logging retention.
LOG_BACKUP_DAYS = 1

# ============================================================
# LOGGING: CONSOLE + DAILY ROTATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "middleware.log"

file_handler = TimedRotatingFileHandler(
    filename=str(LOG_FILE),
    when="midnight",
    interval=1,
    backupCount=LOG_BACKUP_DAYS,
    encoding="utf-8",
    delay=True,
)

file_handler.suffix = "%Y-%m-%d"

console_handler = logging.StreamHandler()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        console_handler,
        file_handler,
    ],
    force=True,
)

logger = logging.getLogger("simple_led")

logger.info("=" * 70)
logger.info("Starting Bosch LPR to CUSTronics LED middleware")
logger.info("Log file: %s", LOG_FILE)
logger.info("Log retention: %s rotated daily files", LOG_BACKUP_DAYS)
logger.info("MQTT broker: %s:%s", MQTT_HOST, MQTT_PORT)
logger.info("MQTT QoS: %s", MQTT_QOS)
logger.info("IN topic branch: %s/#", TOPIC_IN)
logger.info("OUT topic branch: %s/#", TOPIC_OUT)
logger.info("IN LED port: %s", LED_IN_PORT)
logger.info("OUT LED port: %s", LED_OUT_PORT)
logger.info("Simulation mode: %s", SIMULATION)
logger.info("Display reset timeout: %s seconds", DISPLAY_RESET_SECONDS)
logger.info("=" * 70)

# Prevent LED commands from different threads interleaving.
display_lock = threading.Lock()
timer_lock = threading.Lock()

led_in = None
led_out = None

display_timers = {
    "IN": None,
    "OUT": None,
}

display_generations = {
    "IN": 0,
    "OUT": 0,
}


# ============================================================
# SERIAL CONNECTION
# ============================================================

def open_led(port):
    if SIMULATION:
        logger.info("SIMULATION: not opening serial port %s", port)
        return None

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
        logger.exception(
            "Cannot open LED port %s. Other ports and MQTT can continue.",
            port,
        )
        return None


# ============================================================
# FORMAT DISPLAY: EXACTLY 16 CHARACTERS
# ============================================================

def build_display_text(message, plate=""):
    message = message.upper().strip()

    # Allow only ASCII letters, digits and spaces in the plate.
    plate = "".join(
        char
        for char in str(plate).upper()
        if char.isascii() and (char.isalnum() or char == " ")
    )
    plate = " ".join(plate.split())

    # Shorten PUTRAJAYA 1234 to PUT 1234 when it fits.
    if plate.startswith("PUTRAJAYA"):
        suffix = plate[len("PUTRAJAYA"):].strip()
        shortened = "PUT" + (f" {suffix}" if suffix else "")

        if len(shortened) <= 8:
            plate = shortened

    if plate:
        if message == THANKS:
            # OUT: 8-character message slot + up to 8 plate characters.
            # Example: "THANKS  ABC1234 "
            message_slot = message.ljust(8)
            plate = plate[:DISPLAY_WIDTH - len(message_slot)]
            display_text = message_slot + plate

        else:
            # IN: WELCOME + one separator + plate.
            available_plate_chars = DISPLAY_WIDTH - len(message) - 1
            plate = plate[:available_plate_chars].rstrip()
            display_text = f"{message} {plate}"

    else:
        display_text = message

    # Every LED command contains exactly 16 display characters.
    display_text = display_text[:DISPLAY_WIDTH].ljust(DISPLAY_WIDTH)

    logger.info("DISPLAY TEXT: %r", display_text)
    logger.info("DISPLAY LENGTH: %d", len(display_text))

    return display_text


# ============================================================
# SEND LED COMMAND
# ============================================================

def send_led(connection, port, message, plate=""):
    display_text = build_display_text(message, plate)

    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("LED PORT: %s", port)
    logger.info("LED MESSAGE: %s", message)
    logger.info("LED PLATE: %s", plate if plate else "(none)")
    logger.info("LED COLOUR SUFFIX: %s", DISPLAY_COLOR)
    logger.info("ASCII COMMAND: %r", command)
    logger.info("HEX BYTES: %s", data.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(data))

    if SIMULATION:
        logger.info("SIMULATION: command not sent to physical LED")
        return

    if connection is None or not connection.is_open:
        logger.error(
            "LED port %s is unavailable. Skipping this command.",
            port,
        )
        return

    with display_lock:
        _write_led_command(connection, port, data, "LED")


def _write_led_command(connection, port, data, label):
    """Write a prepared command. Caller must hold display_lock."""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            written = connection.write(data)
            connection.flush()

            logger.info(
                "%s TRANSMISSION %d/%d: wrote %d/%d bytes on %s",
                label,
                attempt,
                MAX_RETRIES,
                written,
                len(data),
                port,
            )

            if written != len(data):
                logger.warning(
                    "Incomplete write on %s: %d/%d bytes",
                    port,
                    written,
                    len(data),
                )

        except (
            serial.SerialException,
            serial.SerialTimeoutException,
            OSError,
        ):
            logger.exception(
                "%s transmission %d/%d failed on %s",
                label,
                attempt,
                MAX_RETRIES,
                port,
            )

        if attempt < MAX_RETRIES:
            threading.Event().wait(RETRY_DELAY)

    logger.info("Finished sending %s command to %s", label, port)


# ============================================================
# STARTUP MESSAGES
# ============================================================

def show_startup_messages():
    logger.info("=" * 70)
    logger.info("SHOWING STARTUP MESSAGES")

    send_led(led_in, LED_IN_PORT, WELCOME)
    send_led(led_out, LED_OUT_PORT, THANKS)

    logger.info("Startup message commands completed.")
    logger.info("Waiting for Bosch plate recognition...")
    logger.info("=" * 70)


def show_startup_message_for_direction(direction):
    if direction == "IN":
        send_led(led_in, LED_IN_PORT, WELCOME)
    elif direction == "OUT":
        send_led(led_out, LED_OUT_PORT, THANKS)


# ============================================================
# RESTORE STARTUP MESSAGE AFTER TIMEOUT
# ============================================================

def reset_display_after_timeout(direction, generation):
    with display_lock:
        with timer_lock:
            # Do not let an outdated timer overwrite a newer plate.
            if generation != display_generations[direction]:
                logger.info(
                    "Ignoring outdated reset timer for %s",
                    direction,
                )
                return

            display_timers[direction] = None

        logger.info("=" * 70)
        logger.info(
            "NO NEW %s PLATE EVENT FOR %s SECONDS",
            direction,
            DISPLAY_RESET_SECONDS,
        )
        logger.info("RESTORING STARTUP MESSAGE FOR %s", direction)

        _send_startup_message_unlocked(direction)

        logger.info("Startup message restored for %s", direction)
        logger.info("=" * 70)


def _send_startup_message_unlocked(direction):
    """Send a reset command while display_lock is already held."""

    if direction == "IN":
        connection = led_in
        port = LED_IN_PORT
        message = WELCOME
    else:
        connection = led_out
        port = LED_OUT_PORT
        message = THANKS

    display_text = build_display_text(message)
    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("RESET LED PORT: %s", port)
    logger.info("RESET ASCII COMMAND: %r", command)
    logger.info("RESET HEX BYTES: %s", data.hex(" ").upper())
    logger.info("RESET BYTE COUNT: %d", len(data))

    if SIMULATION:
        logger.info("SIMULATION: reset command not sent")
        return

    if connection is None or not connection.is_open:
        logger.error(
            "Cannot reset display; LED port %s is unavailable.",
            port,
        )
        return

    _write_led_command(connection, port, data, "RESET")


def schedule_display_reset(direction):
    with timer_lock:
        old_timer = display_timers[direction]

        if old_timer is not None:
            old_timer.cancel()

        display_generations[direction] += 1
        generation = display_generations[direction]

        timer = threading.Timer(
            DISPLAY_RESET_SECONDS,
            reset_display_after_timeout,
            args=(direction, generation),
        )
        timer.daemon = True

        display_timers[direction] = timer
        timer.start()

    logger.info(
        "DISPLAY RESET TIMER STARTED: %s seconds for %s",
        DISPLAY_RESET_SECONDS,
        direction,
    )


# ============================================================
# EXTRACT PLATE FROM JSON
# ============================================================

def find_plate(data):
    if isinstance(data, dict):
        for key in (
            "plate",
            "plate_number",
            "LicensePlate",
            "LicensePlateNumber",
            "PlateNumber",
        ):
            value = data.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

            if isinstance(value, dict):
                text_value = value.get("#text")

                if isinstance(text_value, str) and text_value.strip():
                    return text_value.strip()

        for value in data.values():
            result = find_plate(value)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_plate(item)
            if result:
                return result

    return None


# ============================================================
# DETERMINE DIRECTION FROM MQTT TOPIC
# ============================================================

def get_direction(topic):
    topic_lower = topic.lower()

    if (
        topic_lower == TOPIC_IN.lower()
        or topic_lower.startswith(TOPIC_IN.lower() + "/")
    ):
        return "IN"

    if (
        topic_lower == TOPIC_OUT.lower()
        or topic_lower.startswith(TOPIC_OUT.lower() + "/")
    ):
        return "OUT"

    return None


# ============================================================
# MQTT CALLBACKS
# ============================================================

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logger.info("MQTT CONNECTED: %s:%s", MQTT_HOST, MQTT_PORT)

        subscriptions = [
            (TOPIC_IN + "/#", MQTT_QOS),
            (TOPIC_OUT + "/#", MQTT_QOS),
            (TOPIC_IN, MQTT_QOS),
            (TOPIC_OUT, MQTT_QOS),
        ]

        result, message_id = client.subscribe(subscriptions)

        logger.info(
            "MQTT SUBSCRIBE REQUEST: result=%s, message_id=%s",
            result,
            message_id,
        )
        logger.info("Subscribed to: %s/#", TOPIC_IN)
        logger.info("Subscribed to: %s/#", TOPIC_OUT)
        logger.info("Waiting for Bosch MQTT events...")

    else:
        logger.error("MQTT CONNECTION FAILED: %s", reason_code)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logger.warning("MQTT DISCONNECTED: reason=%s", reason_code)


def on_subscribe(client, userdata, mid, reason_code_list, properties):
    logger.info(
        "MQTT SUBSCRIPTION ACKNOWLEDGED: mid=%s, reasons=%s",
        mid,
        reason_code_list,
    )


def on_message(client, userdata, msg):
    logger.info("MQTT RAW PAYLOAD: %s", msg.payload.decode("utf-8", errors="replace"))
    logger.info("=" * 70)
    logger.info("MQTT MESSAGE RECEIVED")
    logger.info("MQTT TOPIC: %s", msg.topic)
    logger.info("MQTT MESSAGE QOS: %s", msg.qos)

    # Do not log the complete raw payload.
    # Bosch events may contain large base64 images.
    raw = msg.payload.decode("utf-8", errors="replace")

    direction = get_direction(msg.topic)

    if direction is None:
        logger.warning(
            "Cannot determine IN/OUT direction from topic: %s",
            msg.topic,
        )
        return

    logger.info("DETECTED TOPIC DIRECTION: %s", direction)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Payload is not JSON; ignoring this message.")
        return

    plate = find_plate(data)

    if not plate:
        logger.info("No plate number in this event. Ignoring non-plate event.")
        return

    plate = plate.upper().strip()
    logger.info("PLATE FOUND: %s", plate)

    if direction == "IN":
        send_led(led_in, LED_IN_PORT, WELCOME, plate)
    else:
        send_led(led_out, LED_OUT_PORT, THANKS, plate)

    schedule_display_reset(direction)


# ============================================================
# START APPLICATION
# ============================================================

def main():
    global led_in, led_out

    led_in = open_led(LED_IN_PORT)
    led_out = open_led(LED_OUT_PORT)

    show_startup_messages()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="simple_bosch_led",
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        logger.info("Connecting MQTT to %s:%s", MQTT_HOST, MQTT_PORT)

        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=MQTT_KEEPALIVE,
        )

        client.loop_forever()

    except KeyboardInterrupt:
        logger.info("Stopping application...")

    except Exception:
        logger.exception("Application error")

    finally:
        with timer_lock:
            for direction, timer in display_timers.items():
                if timer is not None:
                    timer.cancel()
                    logger.info("Cancelled pending timer for %s", direction)

        try:
            client.disconnect()
        except Exception:
            logger.exception("Error disconnecting MQTT client")

        for connection in (led_in, led_out):
            if connection and connection.is_open:
                try:
                    connection.close()
                    logger.info("Serial port closed")
                except (serial.SerialException, OSError):
                    logger.exception("Error closing serial port")

        logger.info("Application stopped.")


if __name__ == "__main__":
    main()
