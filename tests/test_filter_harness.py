import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest

from m832d_protocol import FOOTER, build_setup, feed, raster_block

from .filter_harness import FilterHarness


def raster(width, height, pixels):
    header = bytearray(1796)
    for offset, value in ((372, width), (376, height), (384, 8), (388, 8),
                          (392, width), (400, 0), (420, 1)):
        struct.pack_into("<I", header, offset, value)
    return b"RaS2" + bytes(header) + pixels


def filter_script():
    return textwrap.dedent('''
        import os
        import sys

        from m832d_filter.filter import _write_output
        from m832d_filter.options import parse_options

        def pause(seconds):
            print(f"pause:{seconds}", file=sys.stderr, flush=True)

        try:
            _write_output(
                sys.stdout.buffer, sys.stdin.buffer,
                parse_options(os.environ.get("TEST_OPTIONS", "")),
                usb=True, sleep=pause,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"filter-error:{exc}", file=sys.stderr)
            raise SystemExit(1)
    ''')


class FilterHarnessTests(unittest.TestCase):
    def _environment(self, options):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        env['DEVICE_URI'] = 'usb://Phomemo/M832D?serial=TEST'
        env['TEST_OPTIONS'] = options
        return env

    def _write_script(self, directory):
        script = Path(directory) / 'usb_pause_filter.py'
        script.write_text(filter_script())
        return script

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

    def test_usb_pause_blocks_each_next_page_until_drain(self):
        one_page = raster(8, 1, b'\0\xff\xff\xff\xff\xff\xff\xff')
        source = one_page + one_page[4:] + one_page[4:]
        expected_page = build_setup() + raster_block(1, 1, b'\x80') + FOOTER
        with tempfile.TemporaryDirectory() as directory:
            script = self._write_script(directory)
            with FilterHarness(
                    [sys.executable, str(script)],
                    env=self._environment('M832DPagePause=5')) as harness:
                harness.process.stdin.write(source)
                harness.process.stdin.close()
                harness.process.stdin = None
                for _ in range(2):
                    self.assertEqual(
                        harness.read_stdout(len(expected_page)), expected_page,
                    )
                    request = harness.read_side()
                    self.assertEqual((request.command, request.status, request.data),
                                     (2, 0, b''))
                    self.assertFalse(harness.stdout_ready(0.05))
                    harness.write_side(request.command, 1)
                self.assertEqual(
                    harness.read_stdout(len(expected_page)), expected_page,
                )
                harness.process.wait(timeout=2)
                self.assertEqual(harness.process.stdout.read(), b'')
                stderr = harness.process.stderr.read()
        self.assertEqual(harness.process.returncode, 0)
        pauses = [float(line.split(b':', 1)[1])
                  for line in stderr.splitlines() if line.startswith(b'pause:')]
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(value > 5 for value in pauses))

    def test_usb_pause_failure_stops_before_next_page(self):
        one_page = raster(8, 1, b'\0\xff\xff\xff\xff\xff\xff\xff')
        source = one_page + one_page[4:]
        expected_page = build_setup() + raster_block(1, 1, b'\x80') + FOOTER
        for status in (2, 3, 4, 5, 7):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                script = self._write_script(directory)
                with FilterHarness(
                        [sys.executable, str(script)],
                        env=self._environment('M832DPagePause=5')) as harness:
                    harness.process.stdin.write(source)
                    harness.process.stdin.close()
                    harness.process.stdin = None
                    self.assertEqual(
                        harness.read_stdout(len(expected_page)), expected_page,
                    )
                    request = harness.read_side()
                    harness.write_side(request.command, status)
                    harness.process.wait(timeout=2)
                    self.assertEqual(harness.process.stdout.read(), b'')
                    stderr = harness.process.stderr.read()
                self.assertEqual(harness.process.returncode, 1)
                self.assertIn(b'CUPS output drain failed', stderr)

    def test_usb_pause_off_does_not_require_side_channel(self):
        one_page = raster(8, 1, b'\0\xff\xff\xff\xff\xff\xff\xff')
        source = one_page + one_page[4:]
        page = build_setup() + raster_block(1, 1, b'\x80')
        expected = page + feed(2) + page + FOOTER
        with tempfile.TemporaryDirectory() as directory:
            script = self._write_script(directory)
            result = subprocess.run(
                [sys.executable, str(script)], input=source,
                env=self._environment(''), capture_output=True, timeout=2,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
