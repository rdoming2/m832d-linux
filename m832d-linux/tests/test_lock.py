import tempfile
import unittest

from m832d_ble.lock import PrinterLock


class LockTests(unittest.TestCase):
    def test_second_process_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            first = PrinterLock('printer', directory)
            second = PrinterLock('printer', directory)
            with first:
                with self.assertRaises(RuntimeError):
                    second.__enter__()
            with second:
                pass


if __name__ == '__main__':
    unittest.main()
