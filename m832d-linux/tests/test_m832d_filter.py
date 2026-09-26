import io
import struct
import unittest

from m832d_filter.cups_raster import read_pages
from m832d_filter.filter import convert
from m832d_filter.options import parse_options


def raster(width, height, pixels, bits=8):
    header = bytearray(1796)
    # cups_page_header2_t fields after the four-byte magic.
    fields = [(368, width), (372, height), (380, bits), (384, bits),
              (388, width if bits == 8 else (width + 7) // 8),
              (396, 0 if bits == 8 else 1), (416, 1)]
    for offset, value in fields:
        struct.pack_into("<I", header, offset, value)
    return b"RaS3" + bytes(header) + pixels


class FilterTests(unittest.TestCase):
    def test_reads_page_and_emits_raw_raster(self):
        source = raster(8, 1, b"\x00\xff\xff\xff\xff\xff\xff\xff")
        page = read_pages(io.BytesIO(source))[0]
        self.assertEqual((page.width, page.height), (8, 1))
        output = convert(io.BytesIO(source), parse_options(""))
        self.assertIn(b"\x1dv0\x00\x01\x00\x01\x00\x80", output)
        self.assertTrue(output.endswith(b"\x1bd\x02\x1bd\x02"))

    def test_options(self):
        options = parse_options(
            "M832DDensity=Heavy M832DHeat=Slow M832DThreshold=128 "
            "M832DRotation=90")
        self.assertEqual((options.density, options.heat, options.threshold,
                          options.rotation), (4, 0x20, 128, 90))

    def test_rejects_truncated_page(self):
        with self.assertRaises(ValueError):
            read_pages(io.BytesIO(raster(8, 2, b"\0")))


if __name__ == "__main__":
    unittest.main()
