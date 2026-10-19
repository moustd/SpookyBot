
import hid
import time
import random

VENDOR_ID = 0x0519
PRODUCT_ID = 0x2018

RELAYS = {
    1: (0xF1, 0x01),
    2: (0xF2, 0x02),
    3: (0xF3, 0x03),
    4: (0xF4, 0x04),
}

DURATION = 5.0            # Total effect duration in seconds
MIN_INTERVAL = 0.05       # Fastest interval between changes
MAX_INTERVAL = 0.15       # Slowest interval between changes


def spooky_lights():
    print("Scanning for QYF-UR04 Relay Board...")

    if not any(
        d["vendor_id"] == VENDOR_ID
        and d["product_id"] == PRODUCT_ID
        for d in hid.enumerate()
    ):
        print("[ERROR] Relay board not detected.")
        return

    device = hid.device()

    try:
        device.open(VENDOR_ID, PRODUCT_ID)
        print("Connected! Starting spooky light effect...\n")

        start_time = time.monotonic()
        relay_states = {channel: False for channel in RELAYS}

        while time.monotonic() - start_time < DURATION:
            # Randomly select a relay to toggle
            channel = random.choice(list(RELAYS.keys()))
            on_cmd, off_cmd = RELAYS[channel]

            # Toggle this relay's state
            relay_states[channel] = not relay_states[channel]

            if relay_states[channel]:
                device.write([0x00, on_cmd])
                print(f"Relay {channel}: ON")
            else:
                device.write([0x00, off_cmd])
                print(f"Relay {channel}: OFF")

            # Random pause for unpredictable flickering
            time.sleep(random.uniform(MIN_INTERVAL, MAX_INTERVAL))

        print("\nEffect finished. Turning all relays OFF...")

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        # Always attempt to turn every relay off
        try:
            for _, (_, off_cmd) in RELAYS.items():
                device.write([0x00, off_cmd])
            print("All relays switched OFF.")
        except Exception:
            pass

        device.close()


if __name__ == "__main__":
    spooky_lights()
