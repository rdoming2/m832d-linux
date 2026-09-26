"""The confirmed uncompressed M832D command stream."""

import numbers

FOOTER = bytes.fromhex("1b6402 1b6402")


def _byte(value, name):
    if not isinstance(value, numbers.Integral) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer from 0 to 255")
    return bytes((value,))


def build_setup(density=2, heat=0x37, media=0x0b, compression=0):
    """Return the raw-mode setup used by the M832D CUPS path."""
    return (b"\x1f\x11\x08" + b"\x1f\x117" + _byte(heat, "heat") +
            b"\xaa\xab\xac\x02" + b"\x1f\x11\x02" + _byte(density, "density") +
            b"\x1f\x11\x0b" + b"\x1f\x1135" + _byte(compression, "compression"))


SETUP = build_setup()


def feed(units=2):
    return b"\x1bd" + _byte(units, "feed")
