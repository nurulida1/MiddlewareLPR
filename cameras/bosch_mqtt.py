import json
import logging
import threading
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
    MQTT_QOS,
    MQTT_KEEPALIVE,
    MQTT_RECONNECT_MIN_DELAY,
    MQTT_RECONNECT_MAX_DELAY,
    MQTT_USE_TLS,
)
from models import PlateEvent


class BoschMQTTListener(BaseCameraListener):
    def __init__(self, callback):
        super().__init__(callback)

        self.logger = logging.getLogger(__name__)
        self.client = None
        self.connected = threading.Event()

    def start(self):
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
        self.logger.info("MQTT subscription topic: %s", MQTT_TOPIC)

        try:
            self.client.connect(
                MQTT_BROKER_HOST,
                MQTT_BROKER_PORT,
                MQTT_KEEPALIVE,
            )
            self.client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            self.logger.info("MQTT listener interrupted.")
        except Exception:
            self.logger.exception("MQTT listener failed.")
            raise
        finally:
            self.stop()

    def stop(self):
        self.running = False

        if self.client is not None:
            try:
                self.client.disconnect()
                self.client.loop_stop()
            except Exception:
                self.logger.exception("Error stopping MQTT client.")

        super().stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.logger.error(
                "MQTT connection failed: %s",
                reason_code,
            )
            return

        self.connected.set()
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
                "Subscribed to %s (message id %s)",
                MQTT_TOPIC,
                message_id,
            )
        else:
            self.logger.error(
                "MQTT subscription request failed: %s",
                result,
            )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):
        self.connected.clear()
        self.logger.warning(
            "MQTT disconnected: %s",
            reason_code,
        )

    def _on_message(self, client, userdata, message):
        try:
            raw_payload = message.payload.decode("utf-8")
            self.logger.debug(
                "MQTT message received | topic=%s | payload=%s",
                message.topic,
                raw_payload,
            )

            payload = json.loads(raw_payload)

            if not isinstance(payload, dict):
                self.logger.warning("Ignoring non-object JSON payload.")
                return

            event = self._parse_payload(payload)

            if event is None:
                self.logger.warning(
                    "Message received but no valid plate was found. "
                    "Check the raw payload above."
                )
                return

            self.logger.info(
                "Plate detected | plate=%s | camera=%s | topic=%s",
                event.plate,
                event.camera_id,
                message.topic,
            )

            self.callback(event)

        except UnicodeDecodeError:
            self.logger.exception("MQTT payload is not valid UTF-8.")
        except json.JSONDecodeError:
            self.logger.exception("MQTT payload is not valid JSON.")
        except Exception:
            self.logger.exception("Failed to process MQTT message.")

    def _parse_payload(self, payload):
        # First try the known nested Bosch IVA Pro LPR structure.
        plate = None

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

        plate = str(plate).strip()

        if not plate:
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
            {"eventid", "event_id"},
        )

        return PlateEvent(
            plate=plate,
            camera_id=str(camera_value or CAMERA_ID),
            event_id=str(event_id_value or uuid.uuid4()),
            timestamp=self._parse_timestamp(timestamp_value),
            source="bosch_mqtt",
        )

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
                result = cls._find_value(value, target_keys)

                if result is not None:
                    return result

        elif isinstance(obj, list):
            for value in obj:
                result = cls._find_value(value, target_keys)

                if result is not None:
                    return result

        return None

    @staticmethod
    def _normalize_key(key):
        return "".join(
            character.lower()
            for character in str(key)
            if character.isalnum()
        )

    @staticmethod
    def _unwrap_value(value):
        if isinstance(value, dict):
            for key in ("#text", "value", "text"):
                if key in value:
                    return value[key]

            return None

        return value

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
                text_value = text_value[:-1] + "+00:00"

            parsed = datetime.fromisoformat(text_value)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)

        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)