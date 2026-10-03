"""M832D GS v 0 raster framing."""

import struct


def raster_block(row_bytes, height, data):
    """Frame unchanged MSB-first rows as one raw GS v 0 block.

    The header stores byte width and row height as little-endian 16-bit values;
    exact payload-length validation prevents silent row loss or malformed
    framing.
    """
    if not 1 <= row_bytes <= 0xffff:
        raise ValueError("row_bytes must be in 1..65535")
    if not 1 <= height <= 0xffff:
        raise ValueError("height must be in 1..65535")
    if len(data) != row_bytes * height:
        raise ValueError("raster data length does not match dimensions")
    return b"\x1dv0\x00" + struct.pack("<HH", row_bytes, height) + data
