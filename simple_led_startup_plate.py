
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

LOG_BACKUP_DAYS = 1

# True = simulation without physical COM ports.
# False = use physical LED panels.
SIMULATION = False

DISPLAY_WIDTH = 16
WELCOME = "WELCOME"
THANKS = "THANKS"

PLATE_DISPLAY_SECONDS = 5

# Existing tested command suffix.
DISPLAY_COLOR = "0000"

# Retry incomplete/failed serial writes.
MAX_RETRIES = 3
RETRY_DELAY = 0.2

# Repeat each complete command even after a successful write.
SEND_REPEAT_COUNT = 4
SEND_REPEAT_DELAY = 0.2

# Delay after clearing and before displaying new text.
CLEAR_SETTLE_DELAY = 0.1

# ============================================================
# LOGGING
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "simple_led_startup_plate.log"

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

logger = logging.getLogger("simple_led_startup_plate")

# ============================================================
# GLOBAL STATE
# ============================================================

current_display = {
    "IN": WELCOME,
    "OUT": THANKS,
}

display_timers = {
    "IN": None,
    "OUT": None,
}

display_versions = {
    "IN": 0,
    "OUT": 0,
}

led_in = None
led_out = None

command_queues = {
    "IN": queue.Queue(maxsize=1),
    "OUT": queue.Queue(maxsize=1),
}

worker_threads = {}
state_lock = threading.RLock()

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
# LATEST-MESSAGE-WINS QUEUE
# ============================================================

def enqueue_latest(direction, message, command_type):
    command_queue = command_queues[direction]
    item = (message, command_type)

    while True:
        try:
            command_queue.put_nowait(item)
            break

        except queue.Full:
            try:
                old_item = command_queue.get_nowait()
                command_queue.task_done()

                logger.warning(
                    "REPLACED WAITING %s COMMAND: %s (%s)",
                    direction,
                    old_item[0],
                    old_item[1],
                )

            except queue.Empty:
                continue

    logger.info(
        "COMMAND QUEUED: lane=%s | type=%s | message=%s",
        direction,
        command_type,
        message,
    )


# ============================================================
# SERIAL COMMAND TRANSMISSION
# ============================================================

def write_led_command(connection, port, data, command_type):
    attempts = (
        MAX_RETRIES
        if command_type in ("RESET_TO_STARTUP", "CLEAR")
        else 1
    )

    for attempt in range(1, attempts + 1):
        try:
            written = connection.write(data)
            connection.flush()

            logger.info(
                "%s WRITE ATTEMPT %d/%d: %d/%d bytes on %s",
                command_type,
                attempt,
                attempts,
                written,
                len(data),
                port,
            )

            if written == len(data):
                logger.info(
                    "SERIAL WRITE SUCCESS: %s on %s",
                    command_type,
                    port,
                )
                return True

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
                "%s write attempt %d/%d failed on %s",
                command_type,
                attempt,
                attempts,
                port,
            )

        if attempt < attempts:
            time.sleep(RETRY_DELAY)

    logger.error(
        "SERIAL WRITE FAILED: %s after %d attempt(s) on %s",
        command_type,
        attempts,
        port,
    )

    return False


def send_repeated_command(
    connection,
    port,
    data,
    command_type,
):
    all_successful = True

    for attempt in range(1, SEND_REPEAT_COUNT + 1):
        logger.info(
            "%s SEND %d/%d",
            command_type,
            attempt,
            SEND_REPEAT_COUNT,
        )

        success = write_led_command(
            connection,
            port,
            data,
            command_type,
        )

        if not success:
            all_successful = False

        if attempt < SEND_REPEAT_COUNT:
            time.sleep(SEND_REPEAT_DELAY)

    return all_successful


# ============================================================
# CLEAR LED PANEL
# ============================================================


def clear_led(connection, port, direction):
    clear_text = " " * DISPLAY_WIDTH
    clear_command = f"001DIS={clear_text}{DISPLAY_COLOR}\r\n"
    clear_data = clear_command.encode("ascii")

    logger.info("=" * 70)
    logger.info("SENDING REPEATED CLEAR COMMANDS")
    logger.info("LANE: %s", direction)
    logger.info("LED PORT: %s", port)
    logger.info("CLEAR ASCII: %r", clear_command)
    logger.info("CLEAR HEX: %s", clear_data.hex(" ").upper())
    logger.info("CLEAR BYTE COUNT: %d", len(clear_data))

    all_writes_successful = True

    for attempt in range(1, SEND_REPEAT_COUNT + 1):
        logger.info(
            "CLEAR SEND %d/%d on %s",
            attempt,
            SEND_REPEAT_COUNT,
            port,
        )

        success = write_led_command(
            connection,
            port,
            clear_data,
            "CLEAR",
        )

        if not success:
            all_writes_successful = False

        if attempt < SEND_REPEAT_COUNT:
            time.sleep(SEND_REPEAT_DELAY)

    time.sleep(CLEAR_SETTLE_DELAY)

    if all_writes_successful:
        logger.info(
            "%s: all clear-command writes succeeded; "
            "physical clearing is unconfirmed",
            direction,
        )
    else:
        logger.warning(
            "%s: one or more clear-command writes failed",
            direction,
        )

    return all_writes_successful


# ============================================================
# PLATE DISPLAY TIMER
# ============================================================

def restore_startup_display(direction, version):
    with state_lock:
        if display_versions[direction] != version:
            logger.info(
                "%s: ignoring outdated display timer",
                direction,
            )
            return

        startup_message = WELCOME if direction == "IN" else THANKS

        current_display[direction] = startup_message
        display_versions[direction] += 1
        display_timers[direction] = None

        logger.info(
            "%s TIMEOUT: restoring startup message: %s",
            direction,
            startup_message,
        )

        enqueue_latest(
            direction,
            startup_message,
            "RESET_TO_STARTUP",
        )


# def schedule_startup_restore(direction, message):
#     logger.info(
#         "%s: temporary stay mode enabled; "
#         "keeping display '%s' until the next event",
#         direction,
#         message,
#     )


def schedule_startup_restore(direction, message):
    with state_lock:
        if current_display[direction] != message:
            return

        old_timer = display_timers[direction]

        if old_timer is not None:
            old_timer.cancel()

        version = display_versions[direction]

        timer = threading.Timer(
            PLATE_DISPLAY_SECONDS,
            restore_startup_display,
            args=(direction, version),
        )

        timer.daemon = True
        display_timers[direction] = timer
        timer.start()

        logger.info(
            "%s: restore startup message in %s seconds",
            direction,
            PLATE_DISPLAY_SECONDS,
        )


# ============================================================
# TRANSMIT DISPLAY MESSAGE
# ============================================================

def transmit_led_command(direction, message, command_type):
    connection, port = get_lane_connection(direction)

    logger.info("=" * 70)
    logger.info("PREPARING LED COMMAND")
    logger.info("LANE: %s", direction)
    logger.info("COMMAND TYPE: %s", command_type)
    logger.info("LED PORT: %s", port)
    logger.info("DISPLAY MESSAGE: %s", message)

    if not str(message or "").strip():
        logger.warning("Empty message; keeping current display.")
        return

    if SIMULATION:
        logger.info(
            "SIMULATION: would display %s on %s",
            message,
            direction,
        )

        if command_type == "PLATE":
            schedule_startup_restore(direction, message)

        return

    if connection is None or not connection.is_open:
        logger.error(
            "LED port %s unavailable; command skipped.",
            port,
        )
        return

    # Startup messages are sent directly.
    # Plate and reset messages clear the old display first.
    if command_type != "STARTUP":
        if not clear_led(connection, port, direction):
            logger.error(
                "Clear failed; skipping message %s on %s",
                message,
                direction,
            )
            return

        time.sleep(CLEAR_SETTLE_DELAY)

    # if command_type != "STARTUP":
    #     logger.info(
    #         "TEMPORARY STAY MODE: skipping clear before displaying '%s'",
    #         message,
    #     )

    if command_type == "PLATE":
        display_text = message[:DISPLAY_WIDTH].ljust(DISPLAY_WIDTH)

        logger.info("DISPLAY TEXT: %r", display_text)
        logger.info("DISPLAY LENGTH: %d", len(display_text))
    else:
        display_text = build_display_text(message)

    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("ASCII COMMAND: %r", command)
    logger.info("HEX BYTES: %s", data.hex(" ").upper())
    logger.info("BYTE COUNT: %d", len(data))

    success = send_repeated_command(
        connection,
        port,
        data,
        command_type,
    )

    if success:
        logger.info(
            "ALL DISPLAY SENDS COMPLETED: lane=%s | message=%s",
            direction,
            message,
        )

        if command_type == "PLATE":
            schedule_startup_restore(direction, message)

    else:
        logger.error(
            "ONE OR MORE DISPLAY SENDS FAILED: lane=%s | message=%s",
            direction,
            message,
        )


# ============================================================
# ONE SERIAL WORKER PER LANE
# ============================================================

def led_worker(direction):
    command_queue = command_queues[direction]

    logger.info("LED WORKER STARTED FOR %s", direction)

    while True:
        item = command_queue.get()

        try:
            if item is None:
                logger.info("LED WORKER STOPPING FOR %s", direction)
                return

            message, command_type = item

            transmit_led_command(
                direction,
                message,
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
    # Cancel outstanding timers during shutdown.
    with state_lock:
        for direction, timer in display_timers.items():
            if timer is not None:
                timer.cancel()
                display_timers[direction] = None

    for command_queue in command_queues.values():
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

def clear_startup_panels():
    logger.info("CLEARING BOTH LED PANELS BEFORE STARTUP")

    for direction in ("IN", "OUT"):
        connection, port = get_lane_connection(direction)

        if connection is None or not connection.is_open:
            logger.error(
                "Cannot clear %s panel: port %s unavailable",
                direction,
                port,
            )
            continue

        success = clear_led(connection, port, direction)

        if success:
            logger.info("%s PANEL CLEARED: %s", direction, port)
        else:
            logger.error("%s PANEL CLEAR FAILED: %s", direction, port)

    time.sleep(CLEAR_SETTLE_DELAY)


def show_startup_messages():
    logger.info("DISPLAYING STARTUP MESSAGES ON BOTH LED PANELS")

    for direction in ("IN", "OUT"):
        startup_message = WELCOME if direction == "IN" else THANKS

        with state_lock:
            timer = display_timers[direction]

            if timer is not None:
                timer.cancel()
                display_timers[direction] = None

            display_versions[direction] += 1
            current_display[direction] = startup_message

        transmit_led_command(
            direction,
            startup_message,
            "STARTUP",
        )

# ============================================================
# REGISTER PLATE EVENT
# ============================================================


def register_plate_event(direction, message, plate):
    plate = normalize_plate(plate)

    if not plate:
        logger.info(
            "EMPTY PLATE IGNORED: keeping %s display unchanged",
            direction,
        )
        return

    # Format the message into two 8-character rows:
    # Row 1: WELCOME / THANKS / DENIED
    # Row 2: Plate number
    if message in ("WELCOME", "THANKS", "DENIED"):
        message = f"{message:<8}{plate[:8]:<8}"
    else:
        message = f"{message} {plate}"

    with state_lock:
        display_versions[direction] += 1

        old_timer = display_timers[direction]
        if old_timer is not None:
            old_timer.cancel()
            display_timers[direction] = None

        current_display[direction] = message
        enqueue_latest(direction, message, "PLATE")

    logger.info(
        "PLATE EVENT: lane=%s | plate=%s | message=%r",
        direction,
        plate,
        message,
    )

def send_display_frame(connection, port, row1, row2):
    display_text = (
        row1[:8].ljust(8)
        + row2[:8].ljust(8)
    )

    command = f"001DIS={display_text}{DISPLAY_COLOR}\r\n"
    data = command.encode("ascii")

    logger.info("SCROLL FRAME ASCII: %r", command)
    logger.info("SCROLL FRAME TEXT: %r", display_text)
    logger.info("SCROLL FRAME HEX: %s", data.hex(" ").upper())
    logger.info("SCROLL FRAME BYTE COUNT: %d", len(data))

    return send_repeated_command(
        connection,
        port,
        data,
        "PLATE",
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
# DETERMINE LANE FROM MQTT TOPIC
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

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):
    if reason_code == 0:
        logger.info(
            "MQTT CONNECTED: %s:%s",
            MQTT_HOST,
            MQTT_PORT,
        )

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

    else:
        logger.error("MQTT CONNECTION FAILED: %s", reason_code)


def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties,
):
    logger.warning("MQTT DISCONNECTED: reason=%s", reason_code)


def on_subscribe(
    client,
    userdata,
    mid,
    reason_code_list,
    properties,
):
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

    raw = msg.payload.decode("utf-8", errors="replace")
    logger.info("MQTT RAW JSON: %s", raw)
    logger.info("MQTT RAW HEX: %s", msg.payload.hex(" ").upper())
    logger.info("MQTT PAYLOAD BYTES: %d", len(msg.payload))

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
        logger.info("=" * 70)
        logger.info("Starting LED startup + plate display test")
        logger.info(
            "IN LED: %s | startup message: %s",
            LED_IN_PORT,
            WELCOME,
        )
        logger.info(
            "OUT LED: %s | startup message: %s",
            LED_OUT_PORT,
            THANKS,
        )
        logger.info("Simulation mode: %s", SIMULATION)
        logger.info("Display width: %s", DISPLAY_WIDTH)
        logger.info("Command send repeats: %s", SEND_REPEAT_COUNT)
        logger.info("Plate display timeout: %s seconds", PLATE_DISPLAY_SECONDS)
        logger.info("=" * 70)

        led_in = open_led(LED_IN_PORT)
        led_out = open_led(LED_OUT_PORT)

        start_led_workers()

        clear_startup_panels()

        show_startup_messages()

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="simple_bosch_led_startup_plate",
        )

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_message = on_message

        logger.info(
            "Connecting MQTT to %s:%s",
            MQTT_HOST,
            MQTT_PORT,
        )

        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=MQTT_KEEPALIVE,
        )

        logger.info("Waiting for Bosch MQTT plate events...")
        client.loop_forever()

    except KeyboardInterrupt:
        logger.info("Stopping application...")

    except Exception:
        logger.exception("Application error")

    finally:
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
