
import os

# ============================================================
# APPLICATION
# ============================================================

APP_NAME = "Bosch LPR to CUSTronics LED Middleware"

SITE_ID = "PARKING_01"
LANE_ID = "ENTRY_01"


# ============================================================
# CAMERA
# ============================================================

CAMERA_TYPE = os.getenv("CAMERA_TYPE", "bosch_mqtt")
CAMERA_ID = os.getenv("CAMERA_ID", "CAM_ENTRY_01")


# ============================================================
# MQTT
# ============================================================

MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

MQTT_CLIENT_ID = os.getenv(
    "MQTT_CLIENT_ID",
    "bosch-lpr-led-middleware",
)

MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "parking/bosch")

MQTT_TOPIC_PREFIX_IN = os.getenv(
    "MQTT_TOPIC_PREFIX_IN", "parking/bosch/in"
)

MQTT_TOPIC_PREFIX_OUT = os.getenv(
    "MQTT_TOPIC_PREFIX_OUT", "parking/bosch/out"
)

MQTT_TOPIC_IN = f"{MQTT_TOPIC_PREFIX_IN}/#"
MQTT_TOPIC_OUT = f"{MQTT_TOPIC_PREFIX_OUT}/#"

MQTT_TOPIC = os.getenv(
    "MQTT_TOPIC",
    f"{MQTT_TOPIC_PREFIX}/#",
)

MQTT_QOS = 1
MQTT_KEEPALIVE = 60
MQTT_RECONNECT_MIN_DELAY = 1
MQTT_RECONNECT_MAX_DELAY = 30
MQTT_USE_TLS = False


# ============================================================
# EVENT HANDLING
# ============================================================

DUPLICATE_TIMEOUT = 5
DUPLICATE_CACHE_TTL = 60
EVENT_QUEUE_SIZE = 100
QUEUE_GET_TIMEOUT = 1
SHUTDOWN_TIMEOUT = 10


# ============================================================
# LED / RS485
# ============================================================

LED_SIMULATION_MODE = (
    os.getenv("LED_SIMULATION_MODE", "false") # change to false when use real LED
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

# Fixed logical roles.
# COM61 is IN; COM60 is OUT.
# Change these environment variables if required.
LED_IN_SERIAL_PORT = os.getenv(
    "LED_IN_SERIAL_PORT",
    "COM61",
).strip().upper()

LED_OUT_SERIAL_PORT = os.getenv(
    "LED_OUT_SERIAL_PORT",
    "COM60",
).strip().upper()

# Automatically check whether the configured COM ports
# exist in Windows when the application starts.
LED_AUTO_DETECT_PORTS = (
    os.getenv("LED_AUTO_DETECT_PORTS", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

LED_BAUD_RATE = int(os.getenv("LED_BAUD_RATE", "9600"))
LED_DATA_BITS = 8
LED_PARITY = "N"
LED_STOP_BITS = 1
LED_SERIAL_TIMEOUT = 1

RS485_MAX_RETRIES = 3
RS485_RETRY_DELAY = 1

# Backward compatibility with existing LED code.
SERIAL_PORT = os.getenv(
    "LED_SERIAL_PORT",
    LED_IN_SERIAL_PORT,
)

BAUD_RATE = LED_BAUD_RATE
DATA_BITS = LED_DATA_BITS
PARITY = LED_PARITY
STOP_BITS = LED_STOP_BITS
SERIAL_TIMEOUT = LED_SERIAL_TIMEOUT


# # ============================================================
# # BARRIER
# # ============================================================

# BARRIER_CONTROL_ENABLED = (
#     os.getenv("BARRIER_CONTROL_ENABLED", "false")
#     .strip()
#     .lower()
#     in {"1", "true", "yes", "on"}
# )

# BARRIER_RELAY_COM_PORT = os.getenv(
#     "BARRIER_RELAY_COM_PORT",
#     "COM4",
# )

# BARRIER_RELAY_PROTOCOL = "UNCONFIRMED"
# BARRIER_RELAY_BAUD_RATE = 9600
# BARRIER_RELAY_SLAVE_ADDRESS = 1
# BARRIER_RELAY_COIL_ADDRESS = 0
# BARRIER_RELAY_PULSE_SECONDS = 0.5

# SIMULATE_AUTHORISED_ACCESS = (
#     os.getenv("SIMULATE_AUTHORISED_ACCESS", "false")
#     .strip()
#     .lower()
#     in {"1", "true", "yes", "on"}
# )


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

LOG_FILE = "logs/middleware.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5