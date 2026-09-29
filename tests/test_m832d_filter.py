import io
import os
import struct
import unittest

from m832d_filter.cups_raster import read_pages
from m832d_filter.filter import _ble_ready, convert
from m832d_filter.options import parse_options


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
            "M832DRotation=90")
        self.assertEqual((options.density, options.heat, options.threshold,
                          options.rotation), (4, 0x20, 128, 90))

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
