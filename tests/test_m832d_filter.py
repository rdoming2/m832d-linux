import io
import os
import struct
import unittest

from m832d_filter.cups_raster import Page, read_pages
from m832d_filter.filter import (
    _black_rows, _ble_ready, _usb_pause_seconds, _write_output, convert,
)
from m832d_filter.options import parse_options
from m832d_filter.side_channel import CupsSideChannel


def raster(width, height, pixels, bits=8, magic=b"RaS2"):
    header = bytearray(1796)
    # cups_page_header2_t fields after the four-byte magic.
    fields = [(372, width), (376, height), (384, bits), (388, bits),
              (392, width if bits == 8 else (width + 7) // 8),
              (400, 0 if bits == 8 else 1), (420, 1)]
    for offset, value in fields:
        struct.pack_into("<I", header, offset, value)
    return magic + bytes(header) + pixels


class FilterTests(unittest.TestCase):
    def test_reads_page_and_emits_raw_raster(self):
        source = raster(8, 1, b"\x00\xff\xff\xff\xff\xff\xff\xff")
        page = read_pages(io.BytesIO(source))[0]
        self.assertEqual((page.width, page.height), (8, 1))
        output = convert(io.BytesIO(source), parse_options(""))
        self.assertIn(b"\x1dv0\x00\x01\x00\x01\x00\x80", output)
        self.assertTrue(output.endswith(b"\x1bd\x02\x1bd\x02"))

    def test_custom_page_dimensions_preserve_raster_height_without_final_feed(self):
        # 57.15 x 79.25 mm at 300 dpi, as supplied by
        # PageSize=Custom.57.15x79.25mm.
        source = raster(675, 936, b"\xff" * (675 * 936))
        output = convert(io.BytesIO(source), parse_options(""))
        block = b"\x1dv0\x00" + struct.pack("<HH", 675 // 8 + 1, 936)
        self.assertIn(block, output)
        self.assertEqual(output.count(b"\x1bd"), 2)
        self.assertTrue(output.endswith(b"\x1bd\x02\x1bd\x02"))

    def test_feed_separates_pages_but_not_final_page(self):
        page = raster(8, 1, b"\0\xff\xff\xff\xff\xff\xff\xff")
        source = page + page[4:]
        output = convert(io.BytesIO(source), parse_options("M832DFeed=6"))
        self.assertEqual(output.count(b"\x1bd"), 3)
        self.assertIn(b"\x1bd\x06\x1f\x11\x08", output)
        self.assertTrue(output.endswith(b"\x1bd\x02\x1bd\x02"))

    def test_options(self):
        options = parse_options(
            "M832DDensity=Heavy M832DHeat=Slow M832DThreshold=128 "
            "M832DRotation=90 M832DRendering=FloydSteinberg")
        self.assertEqual((options.density, options.heat, options.threshold,
                          options.rotation, options.rendering),
                         (4, 0x20, 128, 90, "floyd-steinberg"))

    def test_default_rendering_is_atkinson(self):
        self.assertEqual(parse_options("").rendering, "atkinson")
        source = raster(8, 1, b"\x80" * 8)
        output = convert(io.BytesIO(source), parse_options(""))
        self.assertIn(b"\x33", output)

    def test_rendering_option_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            parse_options("M832DRendering=Ordered")

    def test_threshold_mode_preserves_configured_cutoff(self):
        page = Page(4, 1, 8, 8, 4, 0, 1, bytes((127, 128, 159, 160)),
                    "", 1, 0, ())
        self.assertEqual(list(_black_rows(page, 160, "threshold")),
                         [b"\xe0"])

    def test_one_bit_input_bypasses_rendering(self):
        page = Page(4, 1, 1, 1, 1, 0, 1, b"\xa0", "", 1, 0, ())
        self.assertEqual(list(_black_rows(page, 0, "atkinson")), [b"\xa0"])

    def test_page_pause_options_are_bounded(self):
        self.assertEqual(parse_options("M832DPagePause=20").page_pause, 20)
        for value in ("1", "6", "31", "-5"):
            with self.assertRaises(ValueError):
                parse_options(f"M832DPagePause={value}")

    def test_usb_pause_adds_bounded_page_settling_allowance(self):
        # 827 rows is approximately 70 mm at the fixed 300 dpi resolution.
        self.assertAlmostEqual(_usb_pause_seconds(827, 10), 18.75, places=1)
        self.assertEqual(_usb_pause_seconds(65535, 10), 70.0)

    def test_page_pause_finalizes_each_page_without_extra_feed(self):
        page = raster(8, 1, b"\0\xff\xff\xff\xff\xff\xff\xff")
        source = page + page[4:]
        options = parse_options("M832DPagePause=5 M832DFeed=6")
        expected = convert(io.BytesIO(source), options)
        output = io.BytesIO()
        events = []

        class Drain:
            def drain(self):
                events.append("drain")

        class Output(io.BytesIO):
            def flush(self):
                events.append("flush")
                super().flush()

        actual = Output()
        _write_output(actual, io.BytesIO(source), options, drain=Drain(),
                      sleep=lambda seconds: events.append(seconds))
        # Incremental output matches the pause-enabled conversion exactly.
        self.assertEqual(actual.getvalue(), expected)
        self.assertEqual(events.count("drain"), 1)
        self.assertEqual(events[:3], ["flush", "drain", 5])
        boundary = b"\x1bd\x02\x1bd\x02" + b"\x1f\x11\x08"
        self.assertIn(boundary, actual.getvalue())
        self.assertNotIn(b"\x1bd\x06" + boundary, actual.getvalue())
        self.assertEqual(actual.getvalue().count(b"\x1bd"), 4)

    def test_side_channel_uses_bounded_cups_request(self):
        class Call:
            def __init__(self):
                self.args = None

            def __call__(self, *args):
                self.args = args
                return 1

        class Library:
            cupsSideChannelDoRequest = Call()

        library = Library()
        CupsSideChannel(fd=1, library=library).drain()
        self.assertEqual(library.cupsSideChannelDoRequest.args[0], 2)
        self.assertEqual(library.cupsSideChannelDoRequest.args[3], 65.0)

    def test_side_channel_rejects_failure_and_missing_descriptor(self):
        class Call:
            def __call__(self, *args):
                return 7

        class Library:
            cupsSideChannelDoRequest = Call()

        with self.assertRaisesRegex(RuntimeError, "status 7"):
            CupsSideChannel(fd=1, library=Library()).drain()
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            CupsSideChannel(fd=9999, library=Library()).drain()

    def test_accepts_cupsfilter_little_endian_magic(self):
        source = raster(8, 1, b"\0\xff\xff\xff\xff\xff\xff\xff", magic=b"3SaR")
        output = convert(io.BytesIO(source), parse_options(""))
        self.assertTrue(output.startswith(b"\x1f\x11\x08"))

    @unittest.skipUnless(os.name == "posix", "requires POSIX descriptors")
    def test_ble_ready_waits_for_query_reply(self):
        read_fd, write_fd = os.pipe()
        output = io.BytesIO()
        import threading
        old_fd = os.dup(3) if _fd_exists(3) else None
        os.dup2(read_fd, 3)
        error = []
        def wait_for_reply():
            try:
                _ble_ready(b"\x1f\x11\x08payload", output)
            except Exception as exc:
                error.append(exc)
        thread = threading.Thread(target=wait_for_reply)
        thread.start()
        try:
            os.write(write_fd, b"\x1a\x04\x64")
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(error, [])
            self.assertEqual(output.getvalue(), b"\x1f\x11\x08")
        finally:
            os.close(read_fd)
            os.close(write_fd)
            if old_fd is None:
                os.close(3)
            else:
                os.dup2(old_fd, 3)
                os.close(old_fd)

    def test_rejects_truncated_page(self):
        with self.assertRaises(ValueError):
            read_pages(io.BytesIO(raster(8, 2, b"\0")))


def _fd_exists(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True

if __name__ == "__main__":
    unittest.main()
