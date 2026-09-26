import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

from .filter_harness import FilterHarness


class FilterHarnessTests(unittest.TestCase):
    def test_back_and_side_channels(self):
        source = textwrap.dedent('''
            import os
            import sys

            os.write(4, bytes((2, 0, 0, 0)))
            response = os.read(4, 4)
            notification = os.read(3, 3)
            sys.stdout.buffer.write(response + notification)
        ''')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'fake_filter.py'
            script.write_text(source)
            with FilterHarness([sys.executable, str(script)]) as harness:
                request = harness.read_side()
                self.assertEqual((request.command, request.status, request.data), (2, 0, b''))
                harness.write_side(request.command, 1)
                harness.send_notification(b'\x1a\x0f\x0c')
                stdout, stderr = harness.process.communicate(timeout=2)
        self.assertEqual(stdout, b'\x02\x01\x00\x00\x1a\x0f\x0c')
        self.assertEqual(stderr, b'')

    def test_libcups_binding_against_real_socket_channels(self):
        source = textwrap.dedent('''
            from m832d_ble.channels import CupsChannels, SideStatus

            channels = CupsChannels()
            request = channels.read_side(1.0)
            channels.write_side(request.command, SideStatus.OK)
            channels.write_back(b'abc')
        ''')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'backend_channels.py'
            script.write_text(source)
            env = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[1] / 'src')
            env['PYTHONPATH'] = source_root
            with FilterHarness([sys.executable, str(script)], env=env) as harness:
                harness.write_side(2, 0)
                response = harness.read_side()
                back = harness.back.recv(3)
                stdout, stderr = harness.process.communicate(timeout=2)
        self.assertEqual((response.command, response.status, response.data), (2, 1, b''))
        self.assertEqual(back, b'abc')
        self.assertEqual(stdout, b'')
        self.assertEqual(stderr, b'')


if __name__ == '__main__':
    unittest.main()
