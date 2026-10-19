import hid
import time

VENDOR_ID = 0x0519
PRODUCT_ID = 0x2018

RELAYS = {
    1: (0xF1, 0x01),
    2: (0xF2, 0x02),
    3: (0xF3, 0x03),
    4: (0xF4, 0x04),
}

def test_relay():
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
        print("Connected. Testing each relay once...\n")

        for channel, (on_cmd, off_cmd) in RELAYS.items():
            print(f"Relay {channel}: ON")
            device.write([0x00, on_cmd])
            time.sleep(1)

            device.write([0x00, off_cmd])
            print(f"Relay {channel}: OFF")

        print("\nAll four relays tested.")

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        try:
            for _, (_, off_cmd) in RELAYS.items():
                device.write([0x00, off_cmd])
        except Exception:
            pass

        device.close()

if __name__ == "__main__":
    test_relay()