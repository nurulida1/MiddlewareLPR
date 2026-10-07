import json
import logging
import uuid

from datetime import (
    datetime,
    timezone,
)

import paho.mqtt.client as mqtt

from cameras.base import (
    BaseCameraListener,
)

from models import (
    PlateEvent,
)

from config import (
    CAMERA_ID,
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_TOPIC,
    MQTT_QOS,
    MQTT_KEEPALIVE,
    MQTT_CLIENT_ID,
    MQTT_RECONNECT_MIN_DELAY,
    MQTT_RECONNECT_MAX_DELAY,
    MQTT_USE_TLS,
    MQTT_CA_CERT,
    MQTT_CLIENT_CERT,
    MQTT_CLIENT_KEY,
)


logger = logging.getLogger(
    "middleware"
)


class BoschMQTTListener(
    BaseCameraListener
):

    def __init__(
        self,
        callback,
    ):

        super().__init__(
            callback
        )

        # Paho MQTT 2.x callback API.

        self.client = mqtt.Client(
            callback_api_version=(
                mqtt.CallbackAPIVersion.VERSION2
            ),
            client_id=MQTT_CLIENT_ID,
            protocol=mqtt.MQTTv311,
        )

        # ====================================================
        # AUTHENTICATION
        # ====================================================

        if MQTT_USERNAME:

            self.client.username_pw_set(
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            )

        # ====================================================
        # TLS
        # ====================================================

        if MQTT_USE_TLS:

            self.client.tls_set(
                ca_certs=MQTT_CA_CERT,
                certfile=MQTT_CLIENT_CERT,
                keyfile=MQTT_CLIENT_KEY,
            )

        # ====================================================
        # RECONNECT
        # ====================================================

        self.client.reconnect_delay_set(
            min_delay=(
                MQTT_RECONNECT_MIN_DELAY
            ),
            max_delay=(
                MQTT_RECONNECT_MAX_DELAY
            ),
        )

        # ====================================================
        # CALLBACKS
        # ====================================================

        self.client.on_connect = (
            self._on_connect
        )

        self.client.on_disconnect = (
            self._on_disconnect
        )

        self.client.on_message = (
            self._on_message
        )

    # ========================================================
    # START
    # ========================================================

    def start(
        self,
    ):

        self.running = True

        logger.info(
            "Connecting to MQTT broker | "
            "host=%s | "
            "port=%s | "
            "topic=%s",
            MQTT_BROKER_HOST,
            MQTT_BROKER_PORT,
            MQTT_TOPIC,
        )

        try:

            self.client.connect(
                host=MQTT_BROKER_HOST,
                port=MQTT_BROKER_PORT,
                keepalive=MQTT_KEEPALIVE,
            )

            logger.info(
                "MQTT network loop starting"
            )

            self.client.loop_forever(
                retry_first_connection=True
            )

        except Exception:

            if self.running:

                logger.exception(
                    "MQTT listener failed"
                )

                raise

        finally:

            self.running = False

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self,
    ):

        self.running = False

        try:

            self.client.disconnect()

        except Exception:

            logger.exception(
                "Error disconnecting "
                "MQTT client"
            )

        logger.info(
            "Bosch MQTT listener stopped"
        )

    # ========================================================
    # CONNECTED
    # ========================================================

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties,
    ):

        if reason_code != 0:

            logger.error(
                "MQTT connection failed | "
                "reason=%s",
                reason_code,
            )

            return

        logger.info(
            "MQTT connected successfully | "
            "broker=%s:%s",
            MQTT_BROKER_HOST,
            MQTT_BROKER_PORT,
        )

        result, message_id = (
            client.subscribe(
                MQTT_TOPIC,
                qos=MQTT_QOS,
            )
        )

        if (
            result
            != mqtt.MQTT_ERR_SUCCESS
        ):

            logger.error(
                "MQTT subscribe failed | "
                "topic=%s | "
                "result=%s",
                MQTT_TOPIC,
                result,
            )

            return

        logger.info(
            "MQTT subscribed | "
            "topic=%s | "
            "qos=%s | "
            "mid=%s",
            MQTT_TOPIC,
            MQTT_QOS,
            message_id,
        )

    # ========================================================
    # DISCONNECTED
    # ========================================================

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):

        if self.running:

            logger.warning(
                "MQTT disconnected unexpectedly | "
                "reason=%s",
                reason_code,
            )

        else:

            logger.info(
                "MQTT disconnected"
            )

    # ========================================================
    # MQTT MESSAGE
    # ========================================================

    def _on_message(
        self,
        client,
        userdata,
        message,
    ):

        try:

            raw_payload = (
                message.payload.decode(
                    "utf-8"
                )
            )

        except UnicodeDecodeError:

            logger.warning(
                "MQTT payload is not UTF-8 | "
                "topic=%s",
                message.topic,
            )

            return

        logger.info(
            "Bosch MQTT message received | "
            "topic=%s | "
            "qos=%s | "
            "retain=%s",
            message.topic,
            message.qos,
            message.retain,
        )

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------

        try:

            payload = json.loads(
                raw_payload
            )

        except json.JSONDecodeError:

            logger.warning(
                "MQTT payload is not valid JSON | "
                "topic=%s | "
                "payload=%s",
                message.topic,
                raw_payload[:500],
            )

            return

        logger.debug(
            "Bosch MQTT payload | "
            "topic=%s | "
            "payload=%s",
            message.topic,
            payload,
        )

        # ----------------------------------------------------
        # EXTRACT LPR DATA
        # ----------------------------------------------------

        event = self._parse_payload(
            payload
        )

        if event is None:

            logger.warning(
                "Unable to extract plate from "
                "Bosch MQTT message | "
                "topic=%s",
                message.topic,
            )

            return

        # ----------------------------------------------------
        # PASS TO APPLICATION
        # ----------------------------------------------------

        try:

            self.callback(
                event
            )

        except Exception:

            logger.exception(
                "Error processing Bosch "
                "MQTT event"
            )

    # ========================================================
    # PARSE BOSCH PAYLOAD
    # ========================================================

    def _parse_payload(
        self,
        payload,
    ):

        # No event filtering here.
        #
        # Bosch Configuration Manager Publish Filter
        # already controls which LPR events reach MQTT.
        #
        # We only extract the required data.
        #
        # Exact Bosch JSON field names should be replaced
        # once one real MQTT payload is captured.

        plate = self._find_value(
            payload,
            {
                "platenumber",
                "plate_number",
                "plate",
                "licenseplate",
                "license_plate",
                "licensenumber",
                "license_number",
            },
        )

        if plate is None:

            return None

        camera_id = self._find_value(
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

        event_id = self._find_value(
            payload,
            {
                "eventid",
                "event_id",
            },
        )

        timestamp_value = (
            self._find_value(
                payload,
                {
                    "timestamp",
                    "eventtime",
                    "event_time",
                    "datetime",
                    "date_time",
                },
            )
        )

        if camera_id is None:

            camera_id = CAMERA_ID

        if event_id is None:

            event_id = str(
                uuid.uuid4()
            )

        timestamp = (
            self._parse_timestamp(
                timestamp_value
            )
        )

        return PlateEvent(
            plate=str(plate),
            camera_id=str(camera_id),
            event_id=str(event_id),
            timestamp=timestamp,
            source="bosch_mqtt",
        )

    # ========================================================
    # FIND VALUE
    # ========================================================

    def _find_value(
        self,
        data,
        possible_keys,
    ):

        if isinstance(
            data,
            dict,
        ):

            # Search current object.

            for key, value in (
                data.items()
            ):

                normalized_key = (
                    str(key)
                    .strip()
                    .lower()
                )

                if (
                    normalized_key
                    in possible_keys
                    and value is not None
                ):

                    return value

            # Search nested objects.

            for value in (
                data.values()
            ):

                result = (
                    self._find_value(
                        value,
                        possible_keys,
                    )
                )

                if result is not None:

                    return result

        elif isinstance(
            data,
            list,
        ):

            for item in data:

                result = (
                    self._find_value(
                        item,
                        possible_keys,
                    )
                )

                if result is not None:

                    return result

        return None

    # ========================================================
    # TIMESTAMP
    # ========================================================

    def _parse_timestamp(
        self,
        value,
    ):

        if value is None:

            return datetime.now(
                timezone.utc
            )

        # ISO 8601

        if isinstance(
            value,
            str,
        ):

            try:

                normalized = (
                    value.strip()
                )

                if normalized.endswith(
                    "Z"
                ):

                    normalized = (
                        normalized[:-1]
                        + "+00:00"
                    )

                return (
                    datetime.fromisoformat(
                        normalized
                    )
                )

            except ValueError:

                logger.warning(
                    "Unable to parse Bosch "
                    "timestamp | value=%s",
                    value,
                )

        # Unix timestamp

        if isinstance(
            value,
            (int, float),
        ):

            try:

                return (
                    datetime.fromtimestamp(
                        value,
                        tz=timezone.utc,
                    )
                )

            except (
                ValueError,
                OSError,
                OverflowError,
            ):

                pass

        return datetime.now(
            timezone.utc
        )