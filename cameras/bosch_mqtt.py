import json
import logging
import uuid

from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from cameras.base import BaseCameraListener

from config import (
    CAMERA_ID,
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_CLIENT_ID,
    MQTT_TOPIC,
    MQTT_TOPIC_IN,
    MQTT_TOPIC_OUT,
    MQTT_QOS,
    MQTT_KEEPALIVE,
    MQTT_RECONNECT_MIN_DELAY,
    MQTT_RECONNECT_MAX_DELAY,
    MQTT_USE_TLS,
)

from models import PlateEvent


class BoschMQTTListener(BaseCameraListener):
    """
    Receive Bosch LPR events from separate IN and OUT MQTT topics.

    Example:
        parking/bosch/IN  -> direction IN
        parking/bosch/OUT -> direction OUT
    """

    def __init__(self, callback):
        super().__init__(callback)

        self.logger = logging.getLogger(__name__)
        self.client = None

        self.topic_directions = {
            MQTT_TOPIC_IN: "IN",
            MQTT_TOPIC_OUT: "OUT",
        }

    # ========================================================
    # START MQTT LISTENER
    # ========================================================

    def start(self):
        """Start MQTT listener and retry if broker is unavailable."""
        self.running = True

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID,
            protocol=mqtt.MQTTv311,
        )

        if MQTT_USERNAME:
            self.client.username_pw_set(
                MQTT_USERNAME,
                MQTT_PASSWORD or None,
            )

        if MQTT_USE_TLS:
            self.client.tls_set()

        self.client.reconnect_delay_set(
            min_delay=MQTT_RECONNECT_MIN_DELAY,
            max_delay=MQTT_RECONNECT_MAX_DELAY,
        )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self.logger.info(
            "Connecting to MQTT broker %s:%s",
            MQTT_BROKER_HOST,
            MQTT_BROKER_PORT,
        )

        self.logger.info(
            "IN topic: %s",
            MQTT_TOPIC_IN,
        )

        self.logger.info(
            "OUT topic: %s",
            MQTT_TOPIC_OUT,
        )

        try:
            self.client.connect_async(
                MQTT_BROKER_HOST,
                MQTT_BROKER_PORT,
                MQTT_KEEPALIVE,
            )

            self.logger.info(
                "MQTT listener started."
                "Automatic reconnection is enabled."
            )

            self.client.loop_forever(
                retry_first_connection=True,
            )

        except KeyboardInterrupt:
            self.logger.info(
                "MQTT listener interrupted."
            )

        except Exception:
            self.logger.exception(
                "MQTT listener failed."
            )
            raise

        finally:
            self.stop()

    # ========================================================
    # STOP MQTT LISTENER
    # ========================================================

    def stop(self):
        self.running = False

        if self.client is not None:
            try:
                self.client.disconnect()
                self.client.loop_stop()

            except Exception:
                self.logger.exception(
                    "Error stopping MQTT client."
                )

        super().stop()

    # ========================================================
    # MQTT CONNECTION CALLBACK
    # ========================================================

    
    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties,
    ):
        if reason_code.is_failure:
            self.logger.error(
                "MQTT connection failed: %s",
                reason_code,
            )
            return

        self.logger.info(
            "MQTT connected successfully: %s:%s",
            MQTT_BROKER_HOST,
            MQTT_BROKER_PORT,
        )

        result, message_id = client.subscribe(
            MQTT_TOPIC,
            qos=MQTT_QOS,
        )

        if result == mqtt.MQTT_ERR_SUCCESS:
            self.logger.info(
                "MQTT subscription requested | topic=%s | message_id=%s",
                MQTT_TOPIC,
                message_id,
            )
        else:
            self.logger.error(
                "MQTT subscription failed | topic=%s | result=%s",
                MQTT_TOPIC,
                result,
            )

    # ========================================================
    # MQTT DISCONNECTION CALLBACK
    # ========================================================

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):
        self.logger.warning(
            "MQTT disconnected: %s",
            reason_code,
        )

    # ========================================================
    # MQTT MESSAGE CALLBACK
    # ========================================================

    def _on_message(self, client, userdata, message):
        try:
            # Decode the MQTT message.
            raw_payload = message.payload.decode("utf-8", errors="replace")

            # Parse JSON once.
            try:
                payload = json.loads(raw_payload)
                
            except json.JSONDecodeError:
                self.logger.warning("MQTT RAW NON-JSON INPUT | topic=%s | payload=%s", message.topic, raw_payload)
                return

            # Log full JSON at DEBUG level to avoid cluttering normal logs.
            formatted_json = json.dumps(payload, indent=4, ensure_ascii=False)

            self.logger.debug("MQTT RAW JSON INPUT | topic=%s\n%s", message.topic, formatted_json)

            # Validate the JSON structure
            if not isinstance(payload, dict):
                self.logger.warning("Ignoring non-object JSON payload | topic=%s", message.topic)
                return

            self.logger.info(
                "MQTT message received | topic=%s",
                message.topic,
            )

            # Determine whether this is and IN or OUT event.
            direction = self._get_direction(
                message.topic
            )

            self.logger.info(
                "MQTT direction result | topic=%s | direction=%s",
                message.topic,
                direction,
            )

            if direction is None:
                self.logger.warning(
                    "Ignoring message from unconfigured topic: %s",
                    message.topic,
                )
                return

            # Extract the license plate.
            event = self._parse_payload(
                payload,
                direction=direction,
            )

            if event is None:
                self.logger.warning(
                    "No valid plate found | topic=%s",
                    message.topic,
                )
                return

            # ASCII representation for diagnostic logging.
            ascii_plate = event.plate.encode(
                "ascii",
                errors="replace",
            ).decode("ascii")

            self.logger.info(
                "Plate detected | "
                "plate=%s | ASCII=%s | direction=%s | "
                "camera=%s | topic=%s",
                event.plate,
                ascii_plate,
                event.direction,
                event.camera_id,
                message.topic,
            )

            # Pass the complete event to the application.
            self.callback(event)

        except Exception:
            self.logger.exception(
                "Failed to process MQTT message | topic=%s",
                message.topic,
            )

    # ========================================================
    # TOPIC TO DIRECTION
    # ========================================================

    
    
    def _get_direction(self, topic: str):
        # Explicitly configured topics
        if topic == MQTT_TOPIC_IN:
            return "IN"

        if topic == MQTT_TOPIC_OUT:
            return "OUT"

        # Match the Bosch LPR recognition topic
        if (
            "/RuleEngine/Recognition/LicensePlate/" in topic
            and "LPR-Detector" in topic
        ):
            self.logger.info(
                "Bosch LPR topic matched | topic=%s",
                topic,
            )
            return "IN"  # Use OUT instead if this is the exit camera

        return None

    # ========================================================
    # PARSE BOSCH LPR PAYLOAD
    # ========================================================

    def _parse_payload(self, payload, direction):
        plate = None

        # Known nested Bosch IVA Pro LPR JSON structure.
        try:
            plate = (
                payload["Data"]
                ["LicensePlateInfo"]
                ["LicensePlateInfo"]
                ["PlateNumber"]
                ["#text"]
            )

        except (KeyError, TypeError):
            pass

        # Fallback for alternative JSON structures.
        if plate is None:
            plate = self._find_value(
                payload,
                {
                    "platenumber",
                    "plate_number",
                    "licenseplatenumber",
                    "licensenumber",
                    "license_number",
                    "registrationnumber",
                },
            )

        if not isinstance(plate, (str, int)):
            return None

        plate = str(plate).strip().upper()

        if not plate:
            return None

        # A vehicle registration plate should be ASCII.
        if not plate.isascii():
            self.logger.warning(
                "Ignoring non-ASCII plate value: %r",
                plate,
            )
            return None

        timestamp_value = self._find_value(
            payload,
            {
                "utctime",
                "timestamp",
                "eventtime",
                "event_time",
                "datetime",
                "date_time",
            },
        )

        camera_value = self._find_value(
            payload,
            {
                "cameraid",
                "camera_id",
                "cameraname",
                "camera_name",
                "deviceid",
                "device_id",
            },
        )

        event_id_value = self._find_value(
            payload,
            {
                "eventid",
                "event_id",
            },
        )

        return PlateEvent(
            plate=plate,
            camera_id=str(
                camera_value or CAMERA_ID
            ),
            event_id=str(
                event_id_value or uuid.uuid4()
            ),
            timestamp=self._parse_timestamp(
                timestamp_value
            ),
            source="bosch_mqtt",
            direction=direction,
        )

    # ========================================================
    # FIND VALUE RECURSIVELY
    # ========================================================

    @classmethod
    def _find_value(cls, obj, target_keys):
        if isinstance(obj, dict):
            for key, value in obj.items():
                normalized_key = cls._normalize_key(key)

                if normalized_key in target_keys:
                    unwrapped = cls._unwrap_value(value)

                    if unwrapped is not None:
                        return unwrapped

            for value in obj.values():
                result = cls._find_value(
                    value,
                    target_keys,
                )

                if result is not None:
                    return result

        elif isinstance(obj, list):
            for value in obj:
                result = cls._find_value(
                    value,
                    target_keys,
                )

                if result is not None:
                    return result

        return None

    # ========================================================
    # NORMALIZE JSON KEYS
    # ========================================================

    @staticmethod
    def _normalize_key(key):
        return "".join(
            character.lower()
            for character in str(key)
            if character.isalnum()
        )

    # ========================================================
    # UNWRAP BOSCH JSON VALUES
    # ========================================================

    @staticmethod
    def _unwrap_value(value):
        if isinstance(value, dict):
            for key in ("#text", "value", "text"):
                if key in value:
                    return value[key]

            return None

        return value

    # ========================================================
    # PARSE TIMESTAMP
    # ========================================================

    @staticmethod
    def _parse_timestamp(value):
        if value is None:
            return datetime.now(timezone.utc)

        try:
            if isinstance(value, (int, float)):
                # Accept Unix seconds or milliseconds.
                timestamp = float(value)

                if timestamp > 100_000_000_000:
                    timestamp /= 1000

                return datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )

            text_value = str(value).strip()

            if text_value.endswith("Z"):
                text_value = (
                    text_value[:-1] + "+00:00"
                )

            parsed = datetime.fromisoformat(
                text_value
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed.astimezone(timezone.utc)

        except (
            ValueError,
            TypeError,
            OverflowError,
            OSError,
        ):
            return datetime.now(timezone.utc)