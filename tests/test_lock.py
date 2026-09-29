import os
from pathlib import Path
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

    def test_symlink_lock_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_text('do not truncate')
            (Path(directory) / 'm832dble-printer.lock').symlink_to(target)
            with self.assertRaises(OSError):
                PrinterLock('printer', directory).__enter__()
            self.assertEqual(target.read_text(), 'do not truncate')

    def test_shared_lock_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            directory = Path(parent) / 'shared'
            directory.mkdir(mode=0o777)
            os.chmod(directory, 0o777)
            with self.assertRaises(RuntimeError):
                PrinterLock('printer', directory).__enter__()


if __name__ == '__main__':
    unittest.main()
