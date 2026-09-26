"""Small, explicit parser for CUPS Raster 3 pages."""

import struct
from dataclasses import dataclass

# This is the cups_page_header2_t layout from cups/raster.h.  Keeping the
# complete header here avoids depending on libcups or native struct padding.
_FORMAT = (
    "<64s64s64s64s I I I I I II IIII I I I II I I I I I I I I II I I I I I I I I I I I I I "
    "I I I f ff ffff IIIIIIIIIIIIIIII ffffffffffffffff " + "64s " * 19
)
if struct.calcsize(_FORMAT) != 1796:
    raise RuntimeError("CUPS Raster 3 header definition has the wrong size")


@dataclass(frozen=True)
class Page:
    width: int
    height: int
    bits_per_pixel: int
    bits_per_color: int
    bytes_per_line: int
    color_space: int
    num_colors: int
    pixels: bytes
    media_name: str
    num_copies: int
    orientation: int
    integer: tuple


def _text(value):
    return value.split(b"\0", 1)[0].decode("utf-8", "replace")


def read_pages(stream, max_page_bytes=128 * 1024 * 1024):
    data = stream.read()
    if len(data) < 4 or data[:4] not in (b"RaS3", b"3SaR"):
        raise ValueError("input is not CUPS Raster 3")
    little = data[:4] == b"RaS3"
    if not little:
        raise ValueError("big-endian CUPS raster is not supported")
    position = 4
    pages = []
    while position < len(data):
        if len(data) - position < 1796:
            raise ValueError("truncated CUPS raster header")
        values = struct.unpack_from(_FORMAT, data, position)
        position += 1796
        width, height = values[32], values[33]
        bits_color, bits_pixel, bytes_line = values[35:38]
        color_space, num_colors = values[39], values[44]
        if not 1 <= width <= 65535 or not 1 <= height <= 65535:
            raise ValueError("invalid raster dimensions")
        if not 1 <= bytes_line <= 16 * 1024 * 1024:
            raise ValueError("invalid raster row stride")
        size = bytes_line * height
        if size > max_page_bytes or position + size > len(data):
            raise ValueError("truncated or oversized raster page")
        pages.append(Page(width, height, bits_pixel, bits_color, bytes_line,
                          color_space, num_colors, data[position:position + size],
                          _text(values[0]), max(1, values[25]), values[26],
                          tuple(values[64:80])))
        position += size
    if not pages:
        raise ValueError("raster contains no pages")
    return pages
