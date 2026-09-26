#!/usr/bin/env python3
"""Experimental M832D BLE image sender, derived from two successful captures."""
import argparse
import asyncio
import ctypes as C
import ctypes.util
from pathlib import Path
import struct
import time

WRITE_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000ff03-0000-1000-8000-00805f9b34fb'
SETUP = bytes.fromhex('1f1108 1f113764 aaabac02 1f110202 1f110b 1f113501')
FOOTER = bytes.fromhex('1b6402 1b6402')

class LZO:
    def __init__(self):
        name = ctypes.util.find_library('lzo2')
        if not name:
            raise RuntimeError('Install liblzo2 (Arch: lzo; Debian/Ubuntu: liblzo2-2).')
        self.lib = C.CDLL(name)
        for name in ('lzo1x_1_compress', 'lzo1x_decompress_safe'):
            fn = getattr(self.lib, name)
            fn.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.POINTER(C.c_size_t), C.c_void_p]
            fn.restype = C.c_int

    def decompress(self, data, capacity=4096):
        dst = C.create_string_buffer(capacity)
        size = C.c_size_t(capacity)
        rc = self.lib.lzo1x_decompress_safe(data, len(data), dst, C.byref(size), None)
        if rc:
            raise ValueError(f'LZO decode failed: {rc}')
        return dst.raw[:size.value]

    def compress(self, data):
        dst = C.create_string_buffer(len(data) + len(data)//16 + 128)
        size = C.c_size_t(len(dst))
        # Generous aligned workspace for the userspace liblzo2 compressor.
        workspace = (C.c_size_t * 131072)()
        rc = self.lib.lzo1x_1_compress(data, len(data), dst, C.byref(size), workspace)
        if rc:
            raise RuntimeError(f'LZO encode failed: {rc}')
        result = dst.raw[:size.value]
        if self.decompress(result) != data:
            raise RuntimeError('Compression round-trip failed')
        return result

def encode_image(path, width=576, threshold=160, preview=None, compression="lzo"):
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        white = Image.new('RGBA', rgba.size, 'white')
        white.alpha_composite(rgba)
        im = white.convert('L')
    if im.width > width:
        im = im.resize((width, max(1, round(im.height*width/im.width))), Image.Resampling.LANCZOS)
    canvas = Image.new('L', (width, im.height), 255)
    canvas.paste(im, ((width-im.width)//2, 0))
    # Pillow bit value 1 represents white; the printer uses 1 for black.
    black_bits = canvas.point(lambda x: 255 if x < threshold else 0, mode='1')
    raw = black_bits.tobytes()
    if not 1 <= canvas.height <= 65535:
        raise ValueError('Image height must be 1..65535 pixels')
    if preview:
        ImageOps.invert(black_bits.convert('L')).save(preview)
    header = b'\x1d\x76\x30\x00' + struct.pack('<HH', width//8, canvas.height)
    if compression == 'none':
        return SETUP[:-1] + b'\x00' + header + raw + FOOTER
    if compression != 'lzo':
        raise ValueError('Unknown compression mode')
    lzo = LZO()
    blocks = []
    for offset in range(0, len(raw), 4096):
        block = lzo.compress(raw[offset:offset+4096])
        blocks.append(len(block).to_bytes(3, 'little') + block)
    return SETUP + b'\x1d\x76\x30\x00' + struct.pack('<HH', width//8, canvas.height) + b''.join(blocks) + FOOTER

def validate(job):
    if (len(job) < 36 or job[:21] != SETUP[:21] or job[21] not in (0, 1)
            or job[22:26] != b'\x1d\x76\x30\x00' or not job.endswith(FOOTER)):
        raise ValueError('Not a supported M832D image job')
    row_bytes, height = struct.unpack_from('<HH', job, 26)
    if not row_bytes or not height:
        raise ValueError('Empty raster')
    if job[21] == 0:
        raw = job[30:-6]
        if len(raw) != row_bytes*height:
            raise ValueError('Uncompressed raster size mismatch')
        return row_bytes*8, height, raw
    pos, raw, lzo = 30, bytearray(), LZO()
    while pos < len(job)-6:
        if pos+3 > len(job)-6:
            raise ValueError('Truncated block header')
        length = int.from_bytes(job[pos:pos+3], 'little')
        pos += 3
        if length == 0 or pos+length > len(job)-6:
            raise ValueError('Invalid compressed block length')
        raw.extend(lzo.decompress(job[pos:pos+length]))
        pos += length
    if pos != len(job)-6 or len(raw) != row_bytes*height:
        raise ValueError('Raster size mismatch')
    return row_bytes*8, height, bytes(raw)

async def connect_le(device):
    """Establish an LE bearer explicitly before Bleak's generic Connect path."""
    from dbus_fast import Message, MessageType, Variant, BusType
    from dbus_fast.aio import MessageBus
    path = device.details['path']
    adapter = path.rsplit('/', 1)[0]
    address_type = device.details.get('props', {}).get('AddressType')
    if address_type not in ('public', 'random'):
        raise RuntimeError('Discovery did not provide an LE address type')
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    async def call(interface, member, signature='', body=None, target=path):
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path=target, interface=interface,
            member=member, signature=signature, body=body or [])), 30)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        return reply
    try:
        print(f'Requesting explicit LE connection ({address_type}) via {adapter}…')
        try:
            await call('org.bluez.Adapter1', 'ConnectDevice', 'a{sv}', [{
                'Address': Variant('s', device.address),
                'AddressType': Variant('s', address_type),
            }], target=adapter)
        except RuntimeError as exc:
            if not any(x in str(exc) for x in ('UnknownMethod', 'NotSupported')):
                raise
            # Older BlueZ may expose PreferredBearer but not ConnectDevice.
            print(f'ConnectDevice unavailable: {exc}')
            try:
                await call('org.freedesktop.DBus.Properties', 'Set', 'ssv',
                           ['org.bluez.Device1', 'PreferredBearer', Variant('s', 'le')])
                reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss',
                                   ['org.bluez.Device1', 'PreferredBearer'])
                if reply.body[0].value != 'le':
                    raise RuntimeError('PreferredBearer did not become le')
                print('Verified PreferredBearer=le; connecting…')
                await call('org.bluez.Device1', 'Connect')
            except RuntimeError as fallback:
                raise RuntimeError(
                    f'Cannot select LE: {fallback}. BlueZ must expose ConnectDevice '
                    'or PreferredBearer; both are experimental APIs. '
                    'Check bluetoothd configuration and busctl introspection.') from fallback
        print('BlueZ connection established; waiting for GATT through Bleak…')
    finally:
        bus.disconnect()

async def send(job, args):
    from bleak import BleakClient, BleakScanner
    validate(job)
    print('Scanning for M832D…')
    device = await BleakScanner.find_device_by_filter(
        lambda d, a: d.address.lower() == args.address.lower() if args.address
        else (a.local_name or d.name) == 'M832D', timeout=20,
        bluez={'filters': {'Transport': 'le'}})
    if device is None:
        raise RuntimeError('Printer not found. Power it on and disconnect the phone app.')
    await connect_le(device)
    started = time.monotonic()
    query_reply = asyncio.Event()
    def notify(sender, data):
        print(f'{time.monotonic()-started:8.3f}s notify {sender.handle:#06x}: {data.hex(" ")}', flush=True)
        if bytes(data).startswith(b'\x1a\x04'):
            query_reply.set()
    print('Stage: opening Bleak connection and resolving services', flush=True)
    async with BleakClient(device, timeout=25) as client:
        print('Stage: GATT services resolved', flush=True)
        for service in client.services:
            for char in service.characteristics:
                if char.uuid in (WRITE_UUID, NOTIFY_UUID):
                    print(f'  {char.uuid} handle={char.handle:#06x} properties={char.properties}', flush=True)
                    for desc in char.descriptors:
                        print(f'    descriptor {desc.uuid} handle={desc.handle:#06x}', flush=True)
        write = client.services.get_characteristic(WRITE_UUID)
        status = client.services.get_characteristic(NOTIFY_UUID)
        if write is None or status is None:
            raise RuntimeError('FF02/FF03 missing. Do not substitute capture handles without discovery.')
        response = args.write_mode == 'request'
        required = 'write' if response else 'write-without-response'
        if required not in write.properties:
            raise RuntimeError(f'FF02 does not support {required}')
        print(f'Stage: enabling FF03 notifications at {status.handle:#06x}', flush=True)
        await client.start_notify(status, notify)
        print('Stage: notifications enabled', flush=True)
        await asyncio.sleep(0.5)
        # BlueZ handles ATT request sizing; commands must respect Bleak's limit.
        size = min(182, args.chunk_size) if response else min(182, args.chunk_size, write.max_write_without_response_size)
        print(f'FF02={write.handle:#06x}, FF03={status.handle:#06x}; mode={args.write_mode}; chunks ≤{size} bytes')
        sent = 0
        async def write_bytes(data):
            nonlocal sent
            for offset in range(0, len(data), size):
                chunk = data[offset:offset+size]
                try:
                    await asyncio.wait_for(client.write_gatt_char(write, chunk, response=response), 15)
                except Exception as exc:
                    raise RuntimeError(f'Write failed at job offset {sent}, length {len(chunk)}: {exc}') from exc
                previous = sent
                sent += len(chunk)
                if sent // 2048 != previous // 2048 or sent == len(job):
                    print(f'{time.monotonic()-started:8.3f}s transfer {sent}/{len(job)} bytes', flush=True)
                await asyncio.sleep(args.delay_ms/1000)
        print('Stage: sending status query 1f 11 08', flush=True)
        await write_bytes(job[:3])
        try:
            await asyncio.wait_for(query_reply.wait(), timeout=3)
        except TimeoutError:
            raise RuntimeError('No query reply; stopped before sending the print data') from None
        print('Stage: query reply received; sending print job', flush=True)
        await write_bytes(job[3:7])
        await write_bytes(job[7:11])
        await write_bytes(job[11:])
        print(f'Sent {len(job)} bytes. Listening for {args.wait:g}s; status meanings remain provisional.')
        await asyncio.sleep(args.wait)
        print('Stage: disabling notifications', flush=True)
        await client.stop_notify(status)
    print('Transfer finished. Check the paper to confirm print success.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('encode', 'print', 'replay'):
        p = sub.add_parser(name)
        p.add_argument('input', type=Path)
        if name != 'replay':
            p.add_argument('--width', type=int, default=576, help='Canvas pixels; 576 is capture-verified')
            p.add_argument('--threshold', type=int, default=160)
            p.add_argument('--preview', type=Path)
            p.add_argument('--compression', choices=['lzo', 'none'], default='lzo',
                           help='Raster encoding; none tests the CUPS filter’s uncompressed mode')
        if name == 'encode':
            p.add_argument('output', type=Path)
        else:
            p.add_argument('--debug', action='store_true', help='Log Bleak details and full error traceback')
            p.add_argument('--address', help='Optional Bluetooth MAC to select the printer')
            p.add_argument('--write-mode', choices=['command', 'request'], default='request',
                           help='request waits for ATT acknowledgments (default); command uses unacknowledged writes')
            p.add_argument('--chunk-size', type=int, default=182)
            p.add_argument('--delay-ms', type=float, default=0)
            p.add_argument('--wait', type=float, default=30)
    args = parser.parse_args()
    if getattr(args, 'debug', False):
        import logging
        logging.basicConfig(level=logging.DEBUG)
    if args.command != 'replay' and (not 8 <= args.width <= 65528 or args.width % 8 or not 0 <= args.threshold <= 255):
        parser.error('Width must be a multiple of 8 in 8..65528; threshold must be 0..255')
    if args.command != 'encode' and (args.chunk_size < 1 or not 0 <= args.delay_ms <= 60000 or not 0 <= args.wait <= 3600):
        parser.error('Invalid chunk size, delay, or wait')
    job = args.input.read_bytes() if args.command == 'replay' else encode_image(args.input, args.width, args.threshold, args.preview, args.compression)
    width, height, _ = validate(job)
    print(f'{width} × {height} pixels; {len(job)} job bytes; compression={"lzo" if job[21] else "none"}')
    if args.command == 'encode':
        args.output.write_bytes(job)
        print(f'Saved {args.output}')
    else:
        asyncio.run(send(job, args))

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted; printer may have received part of the job.')
        raise SystemExit(130)
    except Exception as exc:
        print(f'Error: {exc}', flush=True)
        import sys
        if '--debug' in sys.argv:
            import traceback
            traceback.print_exc()
        raise SystemExit(1)

