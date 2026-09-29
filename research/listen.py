import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME = "M832D"

WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff03-0000-1000-8000-00805f9b34fb"


def notification_handler(sender, data: bytearray):
    print(
        f"NOTIFY handle={sender.handle:#06x} "
        f"len={len(data):3d} "
        f"data={data.hex(' ')}"
    )


async def main():
    print("Scanning...")

    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: adv.local_name == TARGET_NAME,
        timeout=30,
    )

    if device is None:
        raise RuntimeError("M832D not found")

    print(f"Found: {device}")

    async with BleakClient(device, timeout=20) as client:
        print("Connected:", client.is_connected)

        await client.start_notify(
            NOTIFY_UUID,
            notification_handler,
        )

        print("Listening for notifications.")
        print("Try opening cover, closing cover, feeding paper, etc.")
        print("Ctrl-C to exit.")

        while True:
            await asyncio.sleep(1)


asyncio.run(main())
