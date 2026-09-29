import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME = "M832D"

async def main():
    found = asyncio.Event()
    result = {}

    def callback(device, adv):
        name = adv.local_name or device.name

        if name == TARGET_NAME:
            print("Found M832D:")
            print(" device:", device)
            print(" address:", device.address)
            print(" details:", device.details)
            print(" adv:", adv)

            result["device"] = device
            found.set()

    scanner = BleakScanner(callback)

    print("Scanning for M832D...")
    await scanner.start()

    try:
        await asyncio.wait_for(found.wait(), timeout=30)
    finally:
        await scanner.stop()

    device = result["device"]

    print("\nConnecting directly to discovered BLEDevice...")

    async with BleakClient(device, timeout=20) as client:
        print("CONNECTED:", client.is_connected)

        for service in client.services:
            print(f"\nSERVICE {service.uuid}")

            for char in service.characteristics:
                print(
                    f"  CHAR {char.uuid}"
                    f" handle=0x{char.handle:04x}"
                    f" properties={char.properties}"
                )

                for desc in char.descriptors:
                    print(
                        f"    DESC {desc.uuid}"
                        f" handle=0x{desc.handle:04x}"
                    )

asyncio.run(main())
