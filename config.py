import os

# Application
APP_NAME = "Bosch LPR to CUSTronics LED Middleware"
SITE_ID = "PARKING_01"
LANE_ID = "ENTRY_01"

# Camera
CAMERA_TYPE = os.getenv("CAMERA_TYPE", "bosch_mqtt")
CAMERA_ID = os.getenv("CAMERA_ID", "CAM_ENTRY_01")

# MQTT broker: use the PC IP reachable by the Bosch camera
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "192.168.0.100")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv(
    "MQTT_CLIENT_ID",
    "bosch-lpr-led-middleware"
)

# Must match the topic Bosch actually publishes to.
# Use "#" temporarily for testing, then narrow it once you see the topic.
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "parking/bosch")
MQTT_TOPIC = os.getenv(
    "MQTT_TOPIC",
    f"{MQTT_TOPIC_PREFIX}/#"
)

MQTT_QOS = 1
MQTT_KEEPALIVE = 60
MQTT_RECONNECT_MIN_DELAY = 1
MQTT_RECONNECT_MAX_DELAY = 30
MQTT_USE_TLS = False

# Event handling
DUPLICATE_TIMEOUT = 5
DUPLICATE_CACHE_TTL = 60
EVENT_QUEUE_SIZE = 100
QUEUE_GET_TIMEOUT = 1
SHUTDOWN_TIMEOUT = 10

# LED / RS485
LED_SIMULATION_MODE = (
    os.getenv("LED_SIMULATION_MODE", "true").lower() == "true"
)
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")
BAUD_RATE = 9600
DATA_BITS = 8
PARITY = "N"
STOP_BITS = 1
SERIAL_TIMEOUT = 1

RS485_MAX_RETRIES = 3
RS485_RETRY_DELAY = 1

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
LOG_FILE = "logs/middleware.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5