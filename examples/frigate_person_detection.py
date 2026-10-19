import json
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# --- Configuration ---
MQTT_HOST = "docker.local.moustos.net"  # IP of the machine running Mosquitto
MQTT_PORT = 1883
MQTT_USER = ""               # Leave empty for anonymous access
MQTT_PASSWORD = ""

MQTT_TOPIC = "frigate/events"

CAMERA = "reolink_cam_3"
ZONE = "spooky"


# Track events already reported to avoid duplicate alerts.
reported_events = set()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        print(f"Monitoring camera '{CAMERA}', zone '{ZONE}'")
        print("Waiting for person detections...")
    else:
        print(f"MQTT connection failed: {reason_code}")


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode("utf-8"))

        # Print all incoming events for troubleshooting if needed.
        # print(json.dumps(payload, indent=2))

        event = payload.get("after") or {}

        if event.get("camera") != CAMERA:
            return

        if event.get("label") != "person":
            return

        zones = set(event.get("current_zones") or [])
        zones.update(event.get("entered_zones") or [])

        if ZONE not in zones:
            return

        event_id = event.get("id")

        if not event_id or event_id in reported_events:
            return

        reported_events.add(event_id)

        print(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"PERSON DETECTED in zone '{ZONE}' "
            f"(camera: {CAMERA}, event: {event_id})"
        )

        # Keep the cache bounded during long-running use.
        if len(reported_events) > 5000:
            reported_events.clear()

    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"Invalid MQTT message: {error}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code != 0:
        print(f"MQTT disconnected: {reason_code}. Reconnecting...")


def main():
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Retry if Mosquitto is temporarily unavailable.
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopping MQTT listener...")
    except OSError as error:
        print(f"MQTT connection error: {error}")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()

