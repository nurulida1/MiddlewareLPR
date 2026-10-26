
import json
import logging
import queue
import threading
import time
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

# Keep the existing suffix; confirm its meaning with the LED vendor.
DISPLAY_COLOR = "0000"

MAX_RETRIES = 3
RETRY_DELAY = 0.2

DISPLAY_RESET_SECONDS = 5
LOG_BACKUP_DAYS = 1

# ============================================================
# LOGGING
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(), file_handler],
    force=True,
)

logger = logging.getLogger("simple_led")

logger.info("=" * 70)
logger.info("Starting Bosch LPR to CUSTronics LED middleware")
logger.info("MQTT broker: %s:%s", MQTT_HOST, MQTT_PORT)
logger.info("IN topic: %s/#", TOPIC_IN)
logger.info("OUT topic: %s/#", TOPIC_OUT)
logger.info("IN LED port: %s", LED_IN_PORT)
logger.info("OUT LED port: %s", LED_OUT_PORT)
logger.info("Simulation mode: %s", SIMULATION)
logger.info("Retries: %s | Retry delay: %s seconds",
            MAX_RETRIES, RETRY_DELAY)
logger.info("Display reset: %s seconds", DISPLAY_RESET_SECONDS)
logger.info("=" * 70)

# ============================================================
# GLOBAL STATE
# ============================================================

led_in = None
led_out = None

# One queue and one worker per lane.
# A queue holds at most one waiting command.
command_queues = {
    "IN": queue.Queue(maxsize=1),
    "OUT": queue.Queue(maxsize=1),
}

worker_threads = {}

# Protect timer/generation updates.
state_lock = threading.Lock()

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
            "Cannot open LED port %s. MQTT can continue.",
            port,
        )
        return None


def get_lane_connection(direction):
    if direction == "IN":
        return led_in, LED_IN_PORT
    return led_out, LED_OUT_PORT


# ============================================================
# FORMAT DISPLAY: EXACTLY 16 CHARACTERS
# ============================================================

def build_display_text(message, plate=""):
    plate = str(plate or "").upper()
    plate = "".join(
        char for char in plate
        if char.isascii() and (char.isalnum() or char == " ")
    )
    plate = " ".join(plate.split())

    # Shorten PUTRAJAYA plates if the shortened plate fits the slot.
    if plate.startswith("PUTRAJAYA "):
        shortened = "PUT " + plate[len("PUTRAJAYA "):]
        if len(shortened) <= 8:
            plate = shortened

    if message in ("DENIED", THANKS):
        display_text = f"{message:<8}{plate[:8]:<8}"
    else:
        display_text = f"{message} {plate}"

    display_text = display_text[:DISPLAY_WIDTH].ljust(DISPLAY_WIDTH)

    logger.info("DISPLAY TEXT: %r", display_text)
    logger.info("DISPLAY LENGTH: %d", len(display_text))

    return display_text


# ============================================================
# LATEST-MESSAGE-WINS QUEUE
# ============================================================

def enqueue_latest(direction, message, plate="", command_type="LED"):
    """
    Keep at most one waiting command per lane.
    Replace a waiting command with the newest one.
    A command already being transmitted cannot be cancelled.
    """
    command_queue = command_queues[direction]
    item = (message, plate, command_type)

    while True:
        try:
            command_queue.put_nowait(item)
            break

        except queue.Full:
            try:
                old_item = command_queue.get_nowait()
                command_queue.task_done()

                logger.warning(
                    "REPLACED WAITING %s COMMAND: %s %s",
                    direction,
                    old_item[0],
                    old_item[1] or "(no plate)",
                )

            except queue.Empty:
                # The worker took the item just before we could remove it.
                continue

    logger.info(
        "COMMAND QUEUED: lane=%s | type=%s | message=%s | plate=%s",
        direction,
        command_type,
        message,
        plate or "(none)",
    )


# ============================================================
# SERIAL COMMAND TRANSMISSION
# ============================================================

def write_led_command(connection, port, data, command_type):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            written = connection.write(data)
            connection.flush()

            logger.info(
                "%s TRANSMISSION %d/%d: wrote %d/%d bytes on %s",
                command_type,
                attempt,
                MAX_RETRIES,
                written,
                len(data),
                port,
            )

            if written != len(data):
                logger.warning(
                    "INCOMPLETE WRITE on %s: %d/%d bytes",
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
                command_type,
                attempt,
                MAX_RETRIES,
                port,
            )

        if attempt < MAX_RETRIES:
            threading.Event().wait(RETRY_DELAY)

    logger.info("FINISHED SENDING %s COMMAND TO %s", command_type, port)


def transmit_led_command(direction, message, plate, command_type):
    connection, port = get_lane_connection(direction)

    display_text = build_display_text(message, plate)
    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("=" * 70)
    logger.info("TRANSMITTING COMMAND")
    logger.info("LANE: %s", direction)
    logger.info("COMMAND TYPE: %s", command_type)
    logger.info("LED PORT: %s", port)
    logger.info("LED MESSAGE: %s", message)
    logger.info("LED PLATE: %s", plate or "(none)")
    logger.info("ASCII COMMAND: %r", command)
    logger.info("HEX BYTES: %s", data.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(data))

    if SIMULATION:
        logger.info("SIMULATION: not sent to physical LED")
        return

    if connection is None or not connection.is_open:
        logger.error("LED port %s unavailable; command skipped.", port)
        return

    logger.warning(
        ">>> FINAL LED WRITE: lane=%s | type=%s | text=%r",
        direction,
        command_type,
        display_text,
    )

    write_led_command(connection, port, data, command_type)

# ============================================================
# ONE SERIAL WORKER PER LANE
# ============================================================

# def led_worker(direction):
#     command_queue = command_queues[direction]

#     logger.info("LED WORKER STARTED FOR %s", direction)

#     while True:
#         item = command_queue.get()

#         try:
#             if item is None:
#                 logger.info("LED WORKER STOPPING FOR %s", direction)
#                 return

#             message, plate, command_type = item

#             transmit_led_command(
#                 direction,
#                 message,
#                 plate,
#                 command_type,
#             )

#         except Exception:
#             logger.exception("Unexpected LED worker error for %s", direction)

#         finally:
#             command_queue.task_done()

def led_worker(direction):
    command_queue = command_queues[direction]

    logger.info("LED WORKER STARTED FOR %s", direction)

    while True:
        item = command_queue.get()

        try:
            if item is None:
                logger.info("LED WORKER STOPPING FOR %s", direction)
                return

            message, plate, command_type = item

            # Send the default message directly after timeout.
            transmit_led_command(
                direction,
                message,
                plate,
                command_type,
            )

        except Exception:
            logger.exception(
                "Unexpected LED worker error for %s",
                direction,
            )

        finally:
            command_queue.task_done()

def start_led_workers():
    for direction in ("IN", "OUT"):
        worker = threading.Thread(
            target=led_worker,
            args=(direction,),
            name=f"LEDWorker-{direction}",
            daemon=True,
        )
        worker_threads[direction] = worker
        worker.start()


def stop_led_workers():
    for direction, command_queue in command_queues.items():
        # Discard any waiting command during shutdown.
        while True:
            try:
                command_queue.get_nowait()
                command_queue.task_done()
            except queue.Empty:
                break

        command_queue.put(None)

    for worker in worker_threads.values():
        worker.join(timeout=5)


# ============================================================
# STARTUP MESSAGES
# ============================================================

def show_startup_messages():
    logger.info("QUEUEING STARTUP MESSAGES")

    enqueue_latest("IN", WELCOME, command_type="STARTUP")
    enqueue_latest("OUT", THANKS, command_type="STARTUP")


# ============================================================
# DISPLAY RESET TIMER
# ============================================================

def reset_display_after_timeout(direction, generation):
    with state_lock:
        if generation != display_generations[direction]:
            logger.info(
                "IGNORING OUTDATED RESET TIMER FOR %s",
                direction,
            )
            return

        display_timers[direction] = None

        if direction == "IN":
            startup_message = WELCOME
        else:
            startup_message = THANKS

        logger.info(
            "NO NEW %s PLATE EVENT FOR %s SECONDS",
            direction,
            DISPLAY_RESET_SECONDS,
        )

        # Queue the reset while holding state_lock so a new plate event
        # cannot interleave between the generation check and enqueue.
        enqueue_latest(
            direction,
            startup_message,
            command_type="RESET",
        )


def register_plate_event(direction, message, plate):
    """
    Invalidate the old timer, queue the newest plate command,
    and start a fresh inactivity timer.
    """
    with state_lock:
        old_timer = display_timers[direction]

        display_generations[direction] += 1
        generation = display_generations[direction]

        display_timers[direction] = None

        if old_timer is not None:
            old_timer.cancel()

        # The new plate command replaces any waiting older command.
        enqueue_latest(
            direction,
            message,
            plate,
            command_type="PLATE",
        )

        timer = threading.Timer(
            DISPLAY_RESET_SECONDS,
            reset_display_after_timeout,
            args=(direction, generation),
        )
        timer.daemon = True

        display_timers[direction] = timer
        timer.start()

    logger.info(
        "NEW %s PLATE REGISTERED: %s | MESSAGE: %s",
        direction,
        plate,
        message,
    )
    logger.info(
        "RESET TIMER STARTED: %s seconds for %s",
        DISPLAY_RESET_SECONDS,
        direction,
    )


# ============================================================
# EXTRACT PLATE FROM JSON
# ============================================================

def normalize_plate(plate):
    return "".join(str(plate).upper().split())

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
        logger.info("Subscribed to %s/#", TOPIC_IN)
        logger.info("Subscribed to %s/#", TOPIC_OUT)

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
    logger.info("=" * 70)
    logger.info("MQTT MESSAGE RECEIVED")
    logger.info("MQTT TOPIC: %s", msg.topic)
    logger.info("MQTT QOS: %s", msg.qos)
    logger.info("MQTT RETAIN: %s", msg.retain)

    # Log the complete raw JSON payload exactly as decoded.
    raw = msg.payload.decode("utf-8", errors="replace")
    logger.info("MQTT RAW JSON: %s", raw)

    # Also log the raw payload as hexadecimal for troubleshooting.
    logger.info("MQTT RAW HEX: %s", msg.payload.hex(" ").upper())
    logger.info("MQTT PAYLOAD BYTES: %d", len(msg.payload))

    # Determine direction after logging the raw payload.
    direction = get_direction(msg.topic)

    if direction is None:
        logger.warning("Cannot determine lane for topic: %s", msg.topic)
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Payload is not JSON; ignoring.")
        return

    plate = find_plate(data)

    if not plate:
        logger.info("No plate number in event; ignoring.")
        return

    plate = normalize_plate(plate)
    logger.info("PLATE FOUND (SPACES REMOVED): %s", plate)
    
    event_data = data.get("Data", {})
    if not isinstance(event_data, dict):
        event_data = {}

    label = str(event_data.get("Label", "")).strip().upper()

    if label == "WHITELIST":
        message = WELCOME if direction == "IN" else THANKS
    else:
        message = "DENIED"

    logger.info(
        "%s DISPLAY RESULT: %s | LABEL: %s | PLATE: %s",
        direction,
        message,
        label or "(missing)",
        plate,
    )

    register_plate_event(direction, message, plate)

# ============================================================
# START APPLICATION
# ============================================================

def main():
    global led_in, led_out

    client = None

    try:
        led_in = open_led(LED_IN_PORT)
        led_out = open_led(LED_OUT_PORT)

        # Start workers before queueing startup messages.
        start_led_workers()
        show_startup_messages()

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="simple_bosch_led",
        )

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_message = on_message

        logger.info("Connecting MQTT to %s:%s", MQTT_HOST, MQTT_PORT)

        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=MQTT_KEEPALIVE,
        )

        logger.info("Waiting for Bosch MQTT events...")
        client.loop_forever()

    except KeyboardInterrupt:
        logger.info("Stopping application...")

    except Exception:
        logger.exception("Application error")

    finally:
        with state_lock:
            for direction, timer in display_timers.items():
                if timer is not None:
                    timer.cancel()
                    display_timers[direction] = None

        if client is not None:
            try:
                client.disconnect()
            except Exception:
                logger.exception("Error disconnecting MQTT client")

        stop_led_workers()

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
