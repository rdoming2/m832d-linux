import asyncio
from bleak import BleakScanner

async def callback(device, advertisement_data):
    if device.name == "M832D" or advertisement_data.local_name == "M832D":
        print("DEVICE:")
        print(device)

        print("\nADVERTISEMENT:")
        print(advertisement_data)

        print("\nService UUIDs:")
        for uuid in advertisement_data.service_uuids:
            print(" ", uuid)

        print("\nManufacturer data:")
        for company, data in advertisement_data.manufacturer_data.items():
            print(f"  {company:#06x}: {data.hex(' ')}")

        print("\nService data:")
        for uuid, data in advertisement_data.service_data.items():
            print(f"  {uuid}: {data.hex(' ')}")

async def main():
    scanner = BleakScanner(callback)

    await scanner.start()
    await asyncio.sleep(10)
    await scanner.stop()

asyncio.run(main())
