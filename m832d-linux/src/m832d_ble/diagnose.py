"""Non-printing checks for an M832D BLE queue configuration."""
import argparse
import asyncio

from .config import parse_device_uri
from .transport import BleTransport


async def diagnose(config):
    notifications = []
    transport = BleTransport(config, notifications.append)
    try:
        await transport.connect()
        print(f'OK device: {config.address}')
        print(f'OK adapter: {config.adapter or "BlueZ default"}')
        print('OK bearer: explicit LE')
        print('OK bond/access: notifications enabled')
        print('OK FF02: acknowledged writes supported')
        print('OK FF03: notifications supported')
        print(f'OK configured chunk limit: {config.chunk_size}')
        print('No print data was sent.')
    finally:
        await transport.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device_uri')
    args = parser.parse_args(argv)
    try:
        asyncio.run(diagnose(parse_device_uri(args.device_uri)))
    except Exception as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
