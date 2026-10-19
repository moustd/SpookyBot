
import json
import random
import threading
import time
from datetime import datetime
from math import gcd
from pathlib import Path

import hid
import numpy as np
import paho.mqtt.client as mqtt
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly


# ==================================================
# CONFIGURATION
# ==================================================

# MQTT
MQTT_HOST = "docker.local.moustos.net"
MQTT_PORT = 1883
MQTT_USER = ""
MQTT_PASSWORD = ""
MQTT_TOPIC = "frigate/events"

CAMERA = "reolink_cam_3"
ZONE = "spooky"

# Ignore new triggers for this many seconds after a scare starts.
COOLDOWN = 10.0

# Hardware: QYF-UR04
VENDOR_ID = 0x0519
PRODUCT_ID = 0x2018

RELAYS = {
    1: (0xF1, 0x01),
    2: (0xF2, 0x02),
    3: (0xF3, 0x03),
    4: (0xF4, 0x04),
}

# Lighting effect
LIGHT_DURATION = 5.0
MIN_INTERVAL = 0.05
MAX_INTERVAL = 0.15

# Audio
SOUND_DIRS = {
    "thunder": Path("sounds/thunder"),
    "screams": Path("sounds/screams"),
    "spooky": Path("sounds/spooky"),
}

VOLUMES = {
    "thunder": 1.0,
    "screams": 1.0,
    "spooky": 0.8,
}

SAMPLE_RATE = 44100
FADE_IN = 0.5
FADE_OUT = 0.5

DELAYS = {
    "thunder": (0.0, 0.0),
    "screams": (1.5, 2.5),
    "spooky": (0.8, 1.2),
}


# ==================================================
# STATE
# ==================================================

SOUND_CACHE = {}

reported_events = set()
last_trigger_time = 0.0

state_lock = threading.Lock()
effect_lock = threading.Lock()

stop_event = threading.Event()


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


# ==================================================
# AUDIO PREPARATION
# ==================================================

def prepare_sound(filename, category):
    audio, source_rate = sf.read(filename, dtype="float32")

    if audio.ndim == 2:
        audio = audio.mean(axis=1, dtype=np.float32)

    if source_rate != SAMPLE_RATE:
        factor = gcd(source_rate, SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // factor,
            source_rate // factor,
        ).astype(np.float32, copy=False)

    audio *= VOLUMES[category]

    fade_in_samples = min(
        int(FADE_IN * SAMPLE_RATE), len(audio)
    )
    fade_out_samples = min(
        int(FADE_OUT * SAMPLE_RATE), len(audio)
    )

    if fade_in_samples:
        audio[:fade_in_samples] *= np.linspace(
            0.0, 1.0, fade_in_samples, dtype=np.float32
        )

    if fade_out_samples:
        audio[-fade_out_samples:] *= np.linspace(
            1.0, 0.0, fade_out_samples, dtype=np.float32
        )

    return np.ascontiguousarray(audio)


def preload_sounds():
    log("Preloading sound files...")

    for category, directory in SOUND_DIRS.items():
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Missing sound directory: {directory}"
            )

        files = sorted(
            file for file in directory.iterdir()
            if file.is_file()
            and file.suffix.lower() == ".wav"
        )

        if not files:
            raise FileNotFoundError(
                f"No WAV files found in {directory}"
            )

        SOUND_CACHE[category] = []

        for filename in files:
            audio = prepare_sound(filename, category)
            SOUND_CACHE[category].append(
                (filename.name, audio)
            )

        log(f"  {category}: {len(files)} sounds loaded")


# ==================================================
# AUDIO PLAYBACK
# ==================================================

def play_random_mix():
    selected = {}

    for category, sounds in SOUND_CACHE.items():
        filename, audio = random.choice(sounds)
        selected[category] = audio
        log(f"Selected {category}: {filename}")

    delays = {
        category: random.uniform(*DELAYS[category])
        for category in selected
    }

    starts = {
        category: int(delays[category] * SAMPLE_RATE)
        for category in selected
    }

    total_length = max(
        starts[category] + len(audio)
        for category, audio in selected.items()
    )

    # Stereo output: screams left, atmosphere right,
    # thunder centred in both channels.
    mix = np.zeros((total_length, 2), dtype=np.float32)

    for category, audio in selected.items():
        start = starts[category]
        end = start + len(audio)

        if category == "thunder":
            mix[start:end, 0] += audio
            mix[start:end, 1] += audio

        elif category == "screams":
            mix[start:end, 0] += audio

        elif category == "spooky":
            mix[start:end, 1] += audio

    # Prevent digital clipping when sounds overlap.
    peak = np.max(np.abs(mix))

    if peak > 1.0:
        mix /= peak

    log("Playing spooky audio...")

    # Blocking playback; the lighting effect runs separately.
    sd.play(mix, SAMPLE_RATE)
    sd.wait()

    log("Audio finished.")


# ==================================================
# USB RELAY CONTROL
# ==================================================

def all_relays_off(device):
    for channel, (_, off_command) in RELAYS.items():
        try:
            device.write([0x00, off_command])
        except Exception as error:
            log(f"Could not turn relay {channel} off: {error}")


def spooky_lights():
    devices = hid.enumerate()

    if not any(
        device_info["vendor_id"] == VENDOR_ID
        and device_info["product_id"] == PRODUCT_ID
        for device_info in devices
    ):
        log("ERROR: QYF-UR04 relay board not detected.")
        return

    device = hid.device()

    try:
        device.open(VENDOR_ID, PRODUCT_ID)
        log("Relay board connected.")

        states = {channel: False for channel in RELAYS}
        deadline = time.monotonic() + LIGHT_DURATION

        while (
            time.monotonic() < deadline
            and not stop_event.is_set()
        ):
            channel = random.choice(list(RELAYS))
            on_command, off_command = RELAYS[channel]

            states[channel] = not states[channel]

            command = (
                on_command if states[channel] else off_command
            )

            device.write([0x00, command])

            log(
                f"Light channel {channel}: "
                f"{'ON' if states[channel] else 'OFF'}"
            )

            time.sleep(
                random.uniform(MIN_INTERVAL, MAX_INTERVAL)
            )

    except Exception as error:
        log(f"Relay error: {error}")

    finally:
        try:
            all_relays_off(device)
            log("All relays commanded OFF.")
        finally:
            device.close()


# ==================================================
# SCARE EFFECT
# ==================================================

def run_scare():
    # Only one effect may run at a time.
    if not effect_lock.acquire(blocking=False):
        log("Effect already running; ignoring trigger.")
        return

    try:
        if stop_event.is_set():
            return

        log("=== SPOOKY EVENT TRIGGERED ===")

        # Run the lights concurrently with the audio.
        light_thread = threading.Thread(
            target=spooky_lights,
            name="SpookyLights",
            daemon=False,
        )

        light_thread.start()

        try:
            play_random_mix()
        except Exception as error:
            log(f"Audio playback error: {error}")
        finally:
            light_thread.join()

        log("=== SCARE FINISHED ===")

    finally:
        effect_lock.release()


# ==================================================
# FRIGATE MQTT EVENTS
# ==================================================

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log(f"Connected to MQTT broker {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        log(f"Monitoring camera={CAMERA}, zone={ZONE}")
        log("Waiting for person detections...")
    else:
        log(f"MQTT connection failed: {reason_code}")


def on_message(client, userdata, message):
    global last_trigger_time

    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        log(f"Invalid MQTT message: {error}")
        return

    event = payload.get("after") or {}

    if event.get("camera") != CAMERA:
        return

    if event.get("label") != "person":
        return

    # Frigate may publish several updates for one event.
    zones = set(event.get("current_zones") or [])
    zones.update(event.get("entered_zones") or [])

    if ZONE not in zones:
        return

    event_id = event.get("id")

    if not event_id:
        return

    with state_lock:
        if event_id in reported_events:
            return

        # Remember this event even if it is suppressed by cooldown.
        reported_events.add(event_id)

        if len(reported_events) > 5000:
            reported_events.clear()
            reported_events.add(event_id)

        now = time.monotonic()

        if now - last_trigger_time < COOLDOWN:
            log("Person detected, but scare is on cooldown.")
            return

        last_trigger_time = now

    log(
        f"PERSON DETECTED: camera={CAMERA}, "
        f"zone={ZONE}, event={event_id}"
    )

    # Never run a long audio effect inside the MQTT callback.
    threading.Thread(
        target=run_scare,
        name="ScareEffect",
        daemon=False,
    ).start()


def on_disconnect(
    client, userdata, disconnect_flags, reason_code, properties
):
    if reason_code != 0:
        log(f"MQTT disconnected: {reason_code}. Reconnecting...")


# ==================================================
# MAIN
# ==================================================

def main():
    preload_sounds()

    log("Checking relay board...")

    if not any(
        item["vendor_id"] == VENDOR_ID
        and item["product_id"] == PRODUCT_ID
        for item in hid.enumerate()
    ):
        raise RuntimeError("QYF-UR04 relay board not detected.")

    log("Relay board detected.")
    log("Scare machine starting.")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_forever()

    except KeyboardInterrupt:
        log("Shutdown requested.")

    except OSError as error:
        log(f"MQTT connection error: {error}")

    finally:
        stop_event.set()
        client.disconnect()

        # Wait for any active scare to finish safely.
        with effect_lock:
            pass

        log("Scare machine stopped.")


if __name__ == "__main__":
    main()
