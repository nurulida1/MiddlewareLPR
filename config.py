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

# Available:
#
# "simulation"
# "bosch_mqtt"
#
# Use simulation during development.
CAMERA_TYPE = "bosch_mqtt" #later change to "bosch_mqtt" for production

# Fallback ID if the MQTT payload does not contain
# camera information.
CAMERA_ID = "CAM_ENTRY_01"


# ============================================================
# MQTT BROKER
# ============================================================

MQTT_BROKER_HOST = os.getenv(
    "MQTT_BROKER_HOST",
    "192.168.0.100",
)

MQTT_BROKER_PORT = int(
    os.getenv(
        "MQTT_BROKER_PORT",
        "1883",
    )
)

MQTT_USERNAME = os.getenv(
    "MQTT_USERNAME",
    "",
)

MQTT_PASSWORD = os.getenv(
    "MQTT_PASSWORD",
    "",
)

MQTT_CLIENT_ID = os.getenv(
    "MQTT_CLIENT_ID",
    "bosch-lpr-led-middleware",
)


# ============================================================
# MQTT TOPIC
# ============================================================

# This must match the Topic Prefix configured
# in Bosch Configuration Manager.

MQTT_TOPIC_PREFIX = os.getenv(
    "MQTT_TOPIC_PREFIX",
    "parking/bosch",
)

# Bosch Publish Filter already controls which events
# are published.
#
# During integration, subscribe to everything below
# the configured Bosch prefix.

MQTT_TOPIC = f"{MQTT_TOPIC_PREFIX}/#"


# ============================================================
# MQTT CONNECTION
# ============================================================

# Bosch documentation recommends "At least once".
MQTT_QOS = 1

MQTT_KEEPALIVE = 60

MQTT_RECONNECT_MIN_DELAY = 1

MQTT_RECONNECT_MAX_DELAY = 30


# ============================================================
# MQTT TLS
# ============================================================

# False = normal MQTT
# True  = secure MQTT / TLS

MQTT_USE_TLS = False

MQTT_CA_CERT = None
MQTT_CLIENT_CERT = None
MQTT_CLIENT_KEY = None


# ============================================================
# DUPLICATE PROTECTION
# ============================================================

# Same plate from same camera must disappear for this
# amount of time before being accepted again.
#
# Useful especially because MQTT QoS 1 may redeliver
# messages.

DUPLICATE_TIMEOUT = 5

# Remove old duplicate-cache entries after this time.
DUPLICATE_CACHE_TTL = 60


# ============================================================
# EVENT QUEUE
# ============================================================

EVENT_QUEUE_SIZE = 100

QUEUE_GET_TIMEOUT = 1

SHUTDOWN_TIMEOUT = 10


# ============================================================
# LED
# ============================================================

# True:
# Do not communicate with physical LED.
#
# False:
# Use actual RS485 connection.

LED_SIMULATION_MODE = True


# CUSTronics:
# 2.2RGW-485-2x8-110
#
# 2 lines x 8 characters.

LED_ROWS = 2
LED_COLUMNS = 8


# ============================================================
# RS485
# ============================================================

# Windows:
# COM3
#
# Linux:
# /dev/ttyUSB0

SERIAL_PORT = os.getenv(
    "SERIAL_PORT",
    "COM3",
)


# ============================================================
# CUSTronics SERIAL CONFIGURATION
# ============================================================
#
# TEMPORARY until actual CUSTronics RS485 protocol/manual
# confirms these values.

BAUD_RATE = 9600

DATA_BITS = 8

PARITY = "N"

STOP_BITS = 1

SERIAL_TIMEOUT = 1


# ============================================================
# RS485 RETRY
# ============================================================

RS485_MAX_RETRIES = 3

RS485_RETRY_DELAY = 1


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = "INFO"

LOG_FILE = "logs/middleware.log"

LOG_MAX_BYTES = 5 * 1024 * 1024

LOG_BACKUP_COUNT = 5