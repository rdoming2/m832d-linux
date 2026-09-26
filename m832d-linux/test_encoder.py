import unittest
import tempfile
from pathlib import Path
from PIL import Image
from m832d import LZO, encode_image, validate

HERE = Path(__file__).resolve().parent

class EncoderTests(unittest.TestCase):
    def test_captured_jobs(self):
        for name in ('test', 'best'):
            width, height, raw = validate((HERE/f'{name}.bin').read_bytes())
            self.assertEqual((width, height, len(raw)), (576, 164, 11808))

    def test_reencode_capture(self):
        original = (HERE/'test.bin').read_bytes()
        encoded = encode_image(HERE/'test.png')
        self.assertEqual(validate(encoded), validate(original))
        self.assertEqual(encoded, original)

    def test_various_block_lengths(self):
        import random
        rng = random.Random(42)
        lzo = LZO()
        for length in (1, 72, 3616, 4096):
            raw = rng.randbytes(length)
            self.assertEqual(lzo.decompress(lzo.compress(raw)), raw)

    def test_pixel_polarity_and_transparency(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'image.png'
            im = Image.new('RGBA', (8, 1), (0, 0, 0, 0))
            im.putpixel((0, 0), (0, 0, 0, 255)); im.save(p)
            self.assertEqual(validate(encode_image(p, width=8))[2], b'\x80')

    def test_bad_block_rejected(self):
        job = bytearray((HERE/'test.bin').read_bytes())
        job[30:33] = b'\xff\xff\xff'
        with self.assertRaises(ValueError):
            validate(bytes(job))

if __name__ == '__main__':
    unittest.main()
