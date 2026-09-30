"""CUPS raster to M832D raw command conversion."""

import os
import select
import sys
import time

from m832d_protocol import FOOTER, build_setup, feed, raster_block

from .cups_raster import Page, read_pages
from .options import Options, parse_options
from .side_channel import CupsSideChannel


RASTER_DPI = 300
USB_SETTLE_MM_PER_SECOND = 8.0
USB_SETTLE_MAX_SECONDS = 60.0


def _black_rows(page: Page, threshold: int):
    if page.bits_per_pixel == 1:
        for source in (page.pixels[i:i + page.bytes_per_line]
                       for i in range(0, len(page.pixels), page.bytes_per_line)):
            # CUPS monochrome convention is one for black.
            yield source[:(page.width + 7) // 8]
        return
    channels = max(1, page.num_colors)
    if page.bits_per_pixel not in (8, 24, 32):
        raise ValueError("only 1-bit, grayscale, RGB, and RGBA raster is supported")
    bytes_pixel = page.bits_per_pixel // 8
    for offset in range(0, len(page.pixels), page.bytes_per_line):
        source = page.pixels[offset:offset + page.bytes_per_line]
        output = bytearray((page.width + 7) // 8)
        for x in range(page.width):
            pixel = source[x * bytes_pixel:x * bytes_pixel + bytes_pixel]
            if len(pixel) < bytes_pixel:
                raise ValueError("truncated raster row")
            if bytes_pixel == 1:
                value = pixel[0]
            else:
                value = (299 * pixel[0] + 587 * pixel[1] + 114 * pixel[2]) // 1000
            if value < threshold:
                output[x // 8] |= 0x80 >> (x % 8)
        yield bytes(output)


def _transform(rows, width, height, options: Options):
    matrix = [bytearray(row) for row in rows]
    if options.offset_x:
        shift = options.offset_x
        byte_shift = shift // 8
        bit_shift = shift % 8
        expanded = []
        for row in matrix:
            shifted = bytearray(len(row) + byte_shift + (1 if bit_shift else 0))
            for index, value in enumerate(row):
                shifted[index + byte_shift] |= (value >> bit_shift) if bit_shift else value
                if bit_shift:
                    shifted[index + byte_shift + 1] |= (value << (8 - bit_shift)) & 0xff
            expanded.append(shifted)
        width += shift
        matrix = expanded
    if options.offset_y > 0:
        matrix = [bytearray(len(matrix[0]))] * options.offset_y + matrix
    if options.offset_y < 0:
        matrix = matrix[-options.offset_y:]
    if options.rotation:
        pixels = [[bool(matrix[y][x // 8] & (0x80 >> (x % 8)))
                   for x in range(width)] for y in range(len(matrix))]
        if options.rotation == 180:
            pixels = [row[::-1] for row in pixels[::-1]]
        elif options.rotation == 90:
            pixels = [list(row) for row in zip(*pixels[::-1])]
        else:
            pixels = [list(row) for row in zip(*pixels)][::-1]
        width = len(pixels[0])
        matrix = [bytearray((width + 7) // 8) for _ in pixels]
        for y, row in enumerate(pixels):
            for x, black in enumerate(row):
                if black:
                    matrix[y][x // 8] |= 0x80 >> (x % 8)
    return width, matrix


def _page_output(page: Page, options: Options, has_next):
    rows = list(_black_rows(page, options.threshold))
    width, rows = _transform(rows, page.width, page.height, options)
    output = bytearray(build_setup(options.density, options.heat))
    row_bytes = (width + 7) // 8
    for start in range(0, len(rows), 65535):
        block = b"".join(rows[start:start + 65535])
        output.extend(raster_block(row_bytes, len(rows[start:start + 65535]), block))
    if has_next:
        if options.page_pause:
            output.extend(FOOTER)
        else:
            output.extend(feed(options.feed))
    return bytes(output), len(rows)


def _converted_pages(stream, options):
    pages = read_pages(stream)
    for page_number, page in enumerate(pages):
        yield _page_output(page, options, page_number + 1 < len(pages))


def _page_outputs(stream, options):
    for output, _ in _converted_pages(stream, options):
        yield output


def convert(stream, options: Options):
    output = bytearray()
    for page in _page_outputs(stream, options):
        output.extend(page)
    output.extend(FOOTER)
    return bytes(output)


def _ble_ready(output, stream, timeout=3.0):
    """Emit the confirmed BLE readiness query and await its notification."""
    stream.write(output[:3])
    stream.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = select.select([3], [], [], remaining)
        if not ready:
            break
        data = os.read(3, 4096)
        if not data:
            break
        if b"\x1a\x04" in data:
            return
    raise RuntimeError("M832D BLE readiness query received no 1a 04 reply")


def _usb_pause_seconds(raster_rows, page_pause):
    millimetres = raster_rows * 25.4 / RASTER_DPI
    settling = min(
        USB_SETTLE_MAX_SECONDS, millimetres / USB_SETTLE_MM_PER_SECOND,
    )
    return page_pause + settling


def _write_output(stream, source, options, ble=False, usb=False, drain=None,
                  sleep=time.sleep):
    pages = iter(_converted_pages(source, options))
    page = next(pages, None)
    first = True
    while page is not None:
        next_page = next(pages, None)
        output, raster_rows = page
        if first and ble:
            _ble_ready(output, stream)
            stream.write(output[3:])
        else:
            stream.write(output)
        first = False
        stream.flush()
        if options.page_pause and next_page is not None:
            (drain or CupsSideChannel()).drain()
            pause = (_usb_pause_seconds(raster_rows, options.page_pause)
                     if usb else options.page_pause)
            sleep(pause)
        page = next_page
    stream.write(FOOTER)
    stream.flush()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    source = sys.stdin.buffer
    if len(argv) > 6 and argv[-1] != "-":
        source = open(argv[-1], "rb")
    try:
        options = parse_options(argv[5] if len(argv) > 5 else "")
        device_uri = os.environ.get("DEVICE_URI", "")
        _write_output(
            sys.stdout.buffer, source, options,
            ble=device_uri.startswith("m832dble://"),
            usb=device_uri.startswith("usb://"),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"rastertom832d: {exc}", file=sys.stderr)
        return 1
    finally:
        if source is not sys.stdin.buffer:
            source.close()
    return 0
