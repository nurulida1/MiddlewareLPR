
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

LED_IN_PORT = "COM62"
LED_OUT_PORT = "COM61"

BAUDRATE = 9600
SERIAL_TIMEOUT = 1
WRITE_TIMEOUT = 2

# True = simulation without physical COM ports.
# False = use physical LED panels.
SIMULATION = False

DISPLAY_WIDTH = 16

DEFAULT_ROW1 = {
    "IN": "SELAMAT",
    "OUT": "TERIMA",
}

DEFAULT_ROW2 = {
    "IN": "DATANG",
    "OUT": "KASIH",
}

# WELCOME = "WELCOME"
# THANKS = "THANKS"

PLATE_DISPLAY_SECONDS = 3

# Existing tested command suffix.
DISPLAY_COLOR_DEFAULT = "0000"
DISPLAY_COLOR_GREEN = "1100"
DISPLAY_COLOR_RED = "0000"

# Retry incomplete/failed serial writes.
MAX_RETRIES = 3
RETRY_DELAY = 0.04

# Repeat each complete command even after a successful write.
# SEND_REPEAT_COUNT = 50
# SEND_REPEAT_DELAY = 0.01
SEND_REPEAT_COUNT = 3
SEND_REPEAT_DELAY = 0.05

# Delay after clearing and before displaying new text.
CLEAR_SETTLE_DELAY = 0.05

# ============================================================
# LOGGING
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"

LOG_BACKUP_COUNT = 7

def create_lane_logger(direction):
    lane_log_dir = LOG_DIR / direction
    lane_log_dir.mkdir(parents=True, exist_ok=True)

    log_file = lane_log_dir / f"simple_led_{direction.lower()}.log"

    lane_logger = logging.getLogger(
        f"simple_led_{direction.lower()}"
    )

    lane_logger.setLevel(logging.INFO)
    lane_logger.propagate = False

    # Avoid duplicate handlers if logger is initialized again.
    if not lane_logger.handlers:
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            interval=1,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )

        file_handler.suffix = "%Y-%m-%d"

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )

        file_handler.setFormatter(formatter)
        lane_logger.addHandler(file_handler)

    return lane_logger


# Separate loggers
logger_in = create_lane_logger("IN")
logger_out = create_lane_logger("OUT")

# General application logger (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
    force=True,
)

logger = logging.getLogger("simple_led_startup_plate")

def get_lane_logger(direction):
    if direction == "IN":
        return logger_in

    if direction == "OUT":
        return logger_out

    raise ValueError(f"Invalid LED direction: {direction}")

# ============================================================
# GLOBAL STATE
# ============================================================

# current_display = {
#     "IN": WELCOME,
#     "OUT": THANKS,
# }

current_display = {
    "IN": (
        DEFAULT_ROW1["IN"][:8].ljust(8)
        + DEFAULT_ROW2["IN"][:8].ljust(8)
    ),

    "OUT": (
        DEFAULT_ROW1["OUT"][:8].ljust(8)
        + DEFAULT_ROW2["OUT"][:8].ljust(8)
    ),
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

    if direction == "OUT":
        return led_out, LED_OUT_PORT

    raise ValueError(f"Invalid LED direction: {direction}")



# ============================================================
# DISPLAY TEXT: EXACTLY 16 CHARACTERS
# ============================================================

def build_display_text(message, direction):
    lane_logger = get_lane_logger(direction)

    text = str(message or "").upper()

    text = "".join(
        char for char in text
        if char.isascii() and (char.isalnum() or char == " ")
    )

    result = text[:DISPLAY_WIDTH].ljust(DISPLAY_WIDTH)

    lane_logger.info("DISPLAY TEXT: %r", result)
    lane_logger.info("DISPLAY LENGTH: %d", len(result))

    return result


# ============================================================
# LATEST-MESSAGE-WINS QUEUE
# ============================================================

def enqueue_latest(direction, message, command_type):
    lane_logger = get_lane_logger(direction)

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

                lane_logger.warning(
                    "REPLACED WAITING %s COMMAND: %s (%s)",
                    direction,
                    old_item[0],
                    old_item[1],
                )

            except queue.Empty:
                continue

    lane_logger.info(
        "COMMAND QUEUED: lane=%s | type=%s | message=%s",
        direction,
        command_type,
        message,
    )

# ============================================================
# SERIAL COMMAND TRANSMISSION
# ============================================================

def write_led_command(connection, port, data, command_type, direction):
    lane_logger = get_lane_logger(direction)

    attempts = MAX_RETRIES

    for attempt in range(1, attempts + 1):
        try:
            written = connection.write(data)
            connection.flush()

            if written == len(data):
                lane_logger.info(
                    "SERIAL WRITE SUCCESS: "
                    "lane=%s | command=%s | attempt=%d/%d | "
                    "bytes=%d/%d | port=%s",
                    direction,
                    command_type,
                    attempt,
                    attempts,
                    written,
                    len(data),
                    port,
                )

                return True

            lane_logger.warning(
                "SERIAL WRITE INCOMPLETE: "
                "lane=%s | command=%s | attempt=%d/%d | "
                "bytes=%d/%d | port=%s",
                direction,
                command_type,
                attempt,
                attempts,
                written,
                len(data),
                port,
            )

        except (
            serial.SerialException,
            serial.SerialTimeoutException,
            OSError,
        ):
            lane_logger.exception(
                "SERIAL WRITE ERROR: "
                "lane=%s | command=%s | attempt=%d/%d | port=%s",
                direction,
                command_type,
                attempt,
                attempts,
                port,
            )

        if attempt < attempts:
            time.sleep(RETRY_DELAY)

    lane_logger.error(
        "SERIAL WRITE FAILED AFTER ALL RETRIES: "
        "lane=%s | command=%s | port=%s",
        direction,
        command_type,
        port,
    )

    return False

# def send_repeated_command(
#     connection,
#     port,
#     data,
#     command_type,
# ):
#     all_successful = True

#     for attempt in range(1, SEND_REPEAT_COUNT + 1):
#         logger.info(
#             "%s SEND %d/%d",
#             command_type,
#             attempt,
#             SEND_REPEAT_COUNT,
#         )

#         success = write_led_command(
#             connection,
#             port,
#             data,
#             command_type,
#         )

#         if not success:
#             all_successful = False

#         if attempt < SEND_REPEAT_COUNT:
#             time.sleep(SEND_REPEAT_DELAY)

#     return all_successful


def send_repeated_command(
    connection,
    port,
    data,
    command_type,
    direction,
):
    lane_logger = get_lane_logger(direction)

    all_successful = True

    lane_logger.info(
        "START REPEATED TRANSMISSION: "
        "lane=%s | command=%s | repeat_count=%d",
        direction,
        command_type,
        SEND_REPEAT_COUNT,
    )

    for repeat in range(1, SEND_REPEAT_COUNT + 1):

        lane_logger.info(
            "TRANSMISSION %d/%d: %s on %s",
            repeat,
            SEND_REPEAT_COUNT,
            command_type,
            port,
        )

        success = write_led_command(
            connection,
            port,
            data,
            command_type,
            direction,
        )

        if not success:
            all_successful = False

        if repeat < SEND_REPEAT_COUNT:
            time.sleep(SEND_REPEAT_DELAY)

    if all_successful:
        lane_logger.info(
            "ALL SERIAL TRANSMISSIONS COMPLETED: "
            "lane=%s | command=%s | transmissions=%d",
            direction,
            command_type,
            SEND_REPEAT_COUNT,
        )
    else:
        lane_logger.error(
            "SERIAL TRANSMISSION WARNING: "
            "lane=%s | command=%s | at least one transmission failed",
            direction,
            command_type,
        )

    lane_logger.info(
        "PHYSICAL LED DISPLAY STATUS: UNCONFIRMED "
        "(no display acknowledgement available)"
    )

    return all_successful

# ============================================================
# CLEAR LED PANEL
# ============================================================


# def clear_led(connection, port, direction):
#     clear_text = " " * DISPLAY_WIDTH
#     # clear_command = f"001DIS={clear_text}{DISPLAY_COLOR}\r\n"
#     clear_command = (
#         f"001DIS={clear_text}{DISPLAY_COLOR_DEFAULT}\r\n"
#     )
#     clear_data = clear_command.encode("ascii")

#     logger.info("=" * 70)
#     logger.info("SENDING REPEATED CLEAR COMMANDS")
#     logger.info("LANE: %s", direction)
#     logger.info("LED PORT: %s", port)
#     logger.info("CLEAR ASCII: %r", clear_command)
#     logger.info("CLEAR HEX: %s", clear_data.hex(" ").upper())
#     logger.info("CLEAR BYTE COUNT: %d", len(clear_data))

#     all_writes_successful = True

#     for attempt in range(1, SEND_REPEAT_COUNT + 1):
#         logger.info(
#             "CLEAR SEND %d/%d on %s",
#             attempt,
#             SEND_REPEAT_COUNT,
#             port,
#         )

#         success = write_led_command(
#             connection,
#             port,
#             clear_data,
#             "CLEAR",
#         )

#         if not success:
#             all_writes_successful = False

#         if attempt < SEND_REPEAT_COUNT:
#             time.sleep(SEND_REPEAT_DELAY)

#     time.sleep(CLEAR_SETTLE_DELAY)

#     if all_writes_successful:
#         logger.info(
#             "%s: all clear-command writes succeeded; "
#             "physical clearing is unconfirmed",
#             direction,
#         )
#     else:
#         logger.warning(
#             "%s: one or more clear-command writes failed",
#             direction,
#         )

#     return all_writes_successful


def clear_led(connection, port, direction):
    lane_logger = get_lane_logger(direction)

    clear_text = " " * DISPLAY_WIDTH

    clear_command = (
        f"001DIS={clear_text}{DISPLAY_COLOR_DEFAULT}\r\n"
    )

    clear_data = clear_command.encode("ascii")

    lane_logger.info("=" * 70)
    lane_logger.info("CLEARING LED PANEL: %s", direction)
    lane_logger.info("CLEAR COMMAND: %r", clear_command)

    success = send_repeated_command(
        connection,
        port,
        clear_data,
        "CLEAR",
        direction,
    )

    time.sleep(CLEAR_SETTLE_DELAY)

    if success:
        lane_logger.info("%s: clear transmissions completed", direction)
    else:
        lane_logger.error("%s: clear transmission failed", direction)

    return success

# ============================================================
# PLATE DISPLAY TIMER
# ============================================================

# Commented 28
# def restore_startup_display(direction, version):
#     with state_lock:
#         if display_versions[direction] != version:
#             logger.info(
#                 "%s: ignoring outdated display timer",
#                 direction,
#             )
#             return

#         startup_message = WELCOME if direction == "IN" else THANKS

#         current_display[direction] = startup_message
#         display_versions[direction] += 1
#         display_timers[direction] = None

#         logger.info(
#             "%s TIMEOUT: restoring startup message: %s",
#             direction,
#             startup_message,
#         )

#         enqueue_latest(
#             direction,
#             startup_message,
#             "RESET_TO_STARTUP",
#         )

def restore_startup_display(direction, version):
    lane_logger = get_lane_logger(direction)

    with state_lock:
        if display_versions[direction] != version:
            lane_logger.info(
                "%s: ignoring outdated display timer",
                direction,
            )
            return

        row1 = center_row(DEFAULT_ROW1[direction])
        row2 = center_row(DEFAULT_ROW2[direction])

        default_message = row1 + row2

        display_versions[direction] += 1
        current_display[direction] = default_message
        display_timers[direction] = None

        enqueue_latest(
            direction,
            default_message,
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
    lane_logger = get_lane_logger(direction)

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

        lane_logger.info(
            "%s: restore startup message in %s seconds",
            direction,
            PLATE_DISPLAY_SECONDS,
        )


# ============================================================
# TRANSMIT DISPLAY MESSAGE
# ============================================================

def transmit_led_command(direction, message, command_type):
    lane_logger = get_lane_logger(direction)

    connection, port = get_lane_connection(direction)

    lane_logger.info("=" * 70)
    lane_logger.info("PREPARING LED COMMAND")
    lane_logger.info("LANE: %s", direction)
    lane_logger.info("COMMAND TYPE: %s", command_type)
    lane_logger.info("LED PORT: %s", port)
    lane_logger.info("DISPLAY MESSAGE: %s", message)

    if not str(message or "").strip():
        lane_logger.warning("Empty message; keeping current display.")
        return

    if SIMULATION:
        lane_logger.info(
            "SIMULATION: would display %s on %s",
            message,
            direction,
        )

        if command_type == "PLATE":
            schedule_startup_restore(direction, message)

        return

    if connection is None or not connection.is_open:
        lane_logger.error(
            "LED port %s unavailable; command skipped.",
            port,
        )
        return

    # Startup messages are sent directly.
    # Plate and reset messages clear the old display first.
    if command_type != "STARTUP":
        if not clear_led(connection, port, direction):
            lane_logger.error(
                "Clear failed; skipping message %s on %s",
                message,
                port,
            )
            return

    # if command_type != "STARTUP":
    #     logger.info(
    #         "TEMPORARY STAY MODE: skipping clear before displaying '%s'",
    #         message,
    #     )

    if command_type == "PLATE":
        row1 = center_row(message[:8])
        row2 = center_row(message[8:16])
        display_text = row1 + row2

        lane_logger.info("ROW 1: %r", row1)
        lane_logger.info("ROW 2: %r", row2)
        lane_logger.info("DISPLAY TEXT: %r", display_text)
        lane_logger.info("DISPLAY LENGTH: %d", len(display_text))
    else:
        display_text = build_display_text(message, direction)

    if command_type == "PLATE":
        row1_text = message[:8].strip().upper()

        if row1_text == "KKR":
            color_code = DISPLAY_COLOR_GREEN
        elif row1_text == "DENIED":
            color_code = DISPLAY_COLOR_RED
        else:
            color_code = DISPLAY_COLOR_DEFAULT
    else:
        color_code = DISPLAY_COLOR_DEFAULT

    command = f"001DIS={display_text}{color_code}\r\n"
    data = command.encode("ascii")

    lane_logger.info("ASCII COMMAND: %r", command)
    lane_logger.info("HEX BYTES: %s", data.hex(" ").upper())
    lane_logger.info("BYTE COUNT: %d", len(data))

    success = send_repeated_command(
        connection,
        port,
        data,
        command_type,    
        direction,
    )

    if success:
        lane_logger.info(
            "ALL DISPLAY SENDS COMPLETED: lane=%s | message=%s",
            direction,
            message,
        )

        if command_type == "PLATE":
            schedule_startup_restore(direction, message)

    else:
        lane_logger.error(
            "ONE OR MORE DISPLAY SENDS FAILED: lane=%s | message=%s",
            direction,
            message,
        )


# ============================================================
# ONE SERIAL WORKER PER LANE
# ============================================================

def led_worker(direction):
    lane_logger = get_lane_logger(direction)
    command_queue = command_queues[direction]

    lane_logger.info("LED WORKER STARTED FOR %s", direction)

    while True:
        item = command_queue.get()

        try:
            if item is None:
                lane_logger.info("LED WORKER STOPPING FOR %s", direction)
                return

            message, command_type = item

            transmit_led_command(
                direction,
                message,
                command_type,
            )

        except Exception:
            lane_logger.exception(
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

    # Remove pending commands and enqueue shutdown signals.
    for command_queue in command_queues.values():
        while True:
            try:
                command_queue.get_nowait()
                command_queue.task_done()
            except queue.Empty:
                break

        command_queue.put(None)

    # Wait until each worker finishes its current transmission.
    for direction, worker in worker_threads.items():
        worker.join()

        logger.info(
            "LED WORKER STOPPED: %s",
            direction,
        )

# ============================================================
# STARTUP MESSAGES
# ============================================================

def clear_startup_panels():
    logger.info("CLEARING BOTH LED PANELS BEFORE STARTUP")

    if SIMULATION:
        logger.info(
            "SIMULATION: skipping physical LED panel clearing"
        )
        return

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
            logger.info(
                "%s PANEL CLEAR TRANSMISSIONS COMPLETED: %s",
                direction,
                port,
            )
        else:
            logger.error(
                "%s PANEL CLEAR FAILED: %s",
                direction,
                port,
            )

    time.sleep(CLEAR_SETTLE_DELAY)

# Commented 28/10 5.30pm

def show_startup_messages():
    logger.info("DISPLAYING DEFAULT MESSAGES")

    for direction in ("IN", "OUT"):

        row1 = center_row(DEFAULT_ROW1[direction])
        row2 = center_row(DEFAULT_ROW2[direction])

        default_message = row1 + row2

        with state_lock:
            timer = display_timers[direction]

            if timer is not None:
                timer.cancel()
                display_timers[direction] = None

            display_versions[direction] += 1
            current_display[direction] = default_message

        # connection, port = get_lane_connection(direction)

        # if not SIMULATION and connection is not None and connection.is_open:
        #     clear_led(connection, port, direction)
        #     time.sleep(CLEAR_SETTLE_DELAY)

        transmit_led_command(
            direction,
            default_message,
            "STARTUP",
        )

# def show_startup_messages():
#     logger.info("DISPLAYING STARTUP MESSAGES ON BOTH LED PANELS")

#     for direction in ("IN", "OUT"):
#         startup_message = WELCOME if direction == "IN" else THANKS

#         with state_lock:
#             timer = display_timers[direction]

#             if timer is not None:
#                 timer.cancel()
#                 display_timers[direction] = None

#             display_versions[direction] += 1
#             current_display[direction] = startup_message

#         transmit_led_command(
#             direction,
#             startup_message,
#             "STARTUP",
#         )

# ============================================================
# REGISTER PLATE EVENT
# ============================================================

# Commented 28/10 : 5.24pm
# def register_plate_event(direction, message, plate):
#     plate = normalize_plate(plate)

#     if not plate:
#         logger.info(
#             "EMPTY PLATE IGNORED: keeping %s display unchanged",
#             direction,
#         )
#         return

#     # Format the message into two 8-character rows:
#     # Row 1: WELCOME / THANKS / DENIED
#     # Row 2: Plate number
#     if message in ("WELCOME", "THANKS", "DENIED"):
#         message = f"{message:<8}{plate[:8]:<8}"
#     else:
#         message = f"{message} {plate}"

#     with state_lock:
#         display_versions[direction] += 1

#         old_timer = display_timers[direction]
#         if old_timer is not None:
#             old_timer.cancel()
#             display_timers[direction] = None

#         current_display[direction] = message
#         enqueue_latest(direction, message, "PLATE")

#     logger.info(
#         "PLATE EVENT: lane=%s | plate=%s | message=%r",
#         direction,
#         plate,
#         message,
#     )


def register_plate_event(direction, message, plate):
    lane_logger = get_lane_logger(direction)

    plate = normalize_plate(plate)

    if not plate:
        lane_logger.info(
            "EMPTY PLATE IGNORED: keeping %s display unchanged",
            direction,
        )
        return

    row1 = center_row("KKR" if message == "KKR" else "DENIED")
    row2 = center_row(plate)

    display_message = row1 + row2

    with state_lock:
        display_versions[direction] += 1

        old_timer = display_timers[direction]

        if old_timer is not None:
            old_timer.cancel()
            display_timers[direction] = None

        current_display[direction] = display_message

        enqueue_latest(
            direction,
            display_message,
            "PLATE",
        )

    lane_logger.info(
        "PLATE EVENT: lane=%s | row1=%r | row2=%r",
        direction,
        row1,
        row2,
    )

def send_display_frame(connection, port, row1, row2, direction):
    lane_logger = get_lane_logger(direction)

    display_text = (
        center_row(row1)
        + center_row(row2)
    )

    command = f"001DIS={display_text}{DISPLAY_COLOR_DEFAULT}\r\n"
    data = command.encode("ascii")

    lane_logger.info("SCROLL FRAME ASCII: %r", command)
    lane_logger.info("SCROLL FRAME TEXT: %r", display_text)
    lane_logger.info("SCROLL FRAME HEX: %s", data.hex(" ").upper())
    lane_logger.info("SCROLL FRAME BYTE COUNT: %d", len(data))

    return send_repeated_command(
        connection,
        port,
        data,
        "PLATE",
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
        ]

        result, message_id = client.subscribe(subscriptions)

        logger.info(
            "MQTT SUBSCRIBE REQUEST: result=%s, message_id=%s",
            result,
            message_id,
        )

        logger.info(
            "MQTT LISTENING TO: %s and %s",
            TOPIC_IN + "/#",
            TOPIC_OUT + "/#",
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
    direction = get_direction(msg.topic)

    logger.info(
        "MQTT ROUTING: topic=%s | direction=%s",
        msg.topic,
        direction or "UNKNOWN",
    )

    if direction is None:
        logger.warning(
            "UNKNOWN MQTT TOPIC RECEIVED: %s",
            msg.topic,
        )
        logger.warning(
            "UNKNOWN MQTT PAYLOAD: %s",
            msg.payload.decode("utf-8", errors="replace"),
        )
        return

    lane_logger = get_lane_logger(direction)

    lane_logger.info("=" * 70)
    lane_logger.info("MQTT MESSAGE RECEIVED")
    lane_logger.info("LANE: %s", direction)
    lane_logger.info("MQTT TOPIC: %s", msg.topic)
    lane_logger.info("MQTT QOS: %s", msg.qos)
    lane_logger.info("MQTT RETAIN: %s", msg.retain)

    raw = msg.payload.decode("utf-8", errors="replace")

    lane_logger.info("MQTT RAW JSON: %s", raw)
    lane_logger.info("MQTT RAW HEX: %s", msg.payload.hex(" ").upper())
    lane_logger.info("MQTT PAYLOAD BYTES: %d", len(msg.payload))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        lane_logger.warning("Payload is not JSON; ignoring.")
        return

    plate = find_plate(data)

    if not plate:
        lane_logger.info("No plate number in event; ignoring.")
        return

    plate = normalize_plate(plate)

    lane_logger.info("PLATE FOUND (SPACES REMOVED): %s", plate)

    event_data = data.get("Data", {}) if isinstance(data, dict) else {}

    if not isinstance(event_data, dict):
        event_data = {}

    label = str(event_data.get("Label", "")).strip().upper()

    if label == "WHITELIST":
        message = "KKR"
    else:
        message = "DENIED"

    lane_logger.info(
        "%s DISPLAY RESULT: %s | LABEL: %s | PLATE: %s",
        direction,
        message,
        label or "(missing)",
        plate,
    )

    register_plate_event(direction, message, plate)

# def center_row(message, width=8):
#     text = str(message or "").strip().upper()
#     text = text[:width]
#     return text.ljust(width)

def center_row(message, width=8):
    text = str(message or "").strip().upper()
    text = text[:width]
    return text.center(width)

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
            "IN LED: %s | default: %s / %s",
            LED_IN_PORT,
            DEFAULT_ROW1["IN"],
            DEFAULT_ROW2["IN"],
        )

        logger.info(
            "OUT LED: %s | default: %s / %s",
            LED_OUT_PORT,
            DEFAULT_ROW1["OUT"],
            DEFAULT_ROW2["OUT"],
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
