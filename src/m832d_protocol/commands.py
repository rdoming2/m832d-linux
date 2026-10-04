"""The confirmed uncompressed M832D command stream."""

import numbers

# The confirmed job/page terminator is two ESC d 2 feed commands.
FOOTER = bytes.fromhex("1b6402 1b6402")


def _byte(value, name):
    if not isinstance(value, numbers.Integral) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer from 0 to 255")
    return bytes((value,))


def build_setup(density=2, media=0x0b, compression=0):
    """Return the confirmed setup sequence used by the M832D CUPS path.

    Density and compression are the only variable bytes in the maintained
    project path; heat remains fixed at ``0x37`` and production uses
    compression zero for raw GS v 0 payloads.  ``media`` remains an API
    compatibility placeholder because the sequence does not encode a variable
    media value. Transports must forward this framing without interpreting or
    modifying it.
    """
    return (b"\x1f\x11\x08" + b"\x1f\x117\x37" +
            b"\xaa\xab\xac\x02" + b"\x1f\x11\x02" + _byte(density, "density") +
            b"\x1f\x11\x0b" + b"\x1f\x11\x35" + _byte(compression, "compression"))


SETUP = build_setup()


def feed(units=2):
    return b"\x1bd" + _byte(units, "feed")
