import unittest

from m832d_ble.backend import parse_invocation
from m832d_ble.config import format_device_uri, parse_device_uri


class ConfigTests(unittest.TestCase):
    def test_uri_round_trip(self):
        uri = format_device_uri('D6:4D:F2:16:B6:BF', 'hci0')
        self.assertEqual(uri, 'm832dble://D6-4D-F2-16-B6-BF/?adapter=hci0')
        config = parse_device_uri(uri)
        self.assertEqual(config.address, 'D6:4D:F2:16:B6:BF')
        self.assertEqual(config.adapter, 'hci0')
        self.assertEqual(config.chunk_size, 182)

    def test_uri_requires_explicit_identity(self):
        for uri in (
            'm832dble://M832D/',
            'bluetooth://D6-4D-F2-16-B6-BF/',
            'm832dble://D6-4D-F2-16-B6-BF/?adapter=default',
            'm832dble://D6-4D-F2-16-B6-BF/?unknown=yes',
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                parse_device_uri(uri)

    def test_invocation_stdin_and_filename(self):
        stdin_job = parse_invocation(['m832dble', '1', 'user', 'title', '1', ''])
        file_job = parse_invocation([
            'm832dble', '2', 'user', 'title', '2', 'media=A4', '/tmp/job',
        ])
        self.assertIsNone(stdin_job.filename)
        self.assertEqual(file_job.filename, '/tmp/job')
        self.assertEqual(file_job.copies, 2)

    def test_invocation_rejects_bad_shape(self):
        with self.assertRaises(ValueError):
            parse_invocation(['m832dble'])
        with self.assertRaises(ValueError):
            parse_invocation(['m832dble', '1', 'u', 't', 'zero', ''])


if __name__ == '__main__':
    unittest.main()
