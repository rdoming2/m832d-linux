import unittest
from unittest.mock import patch

from m832d_ble.config import DeviceConfig
from m832d_ble.diagnose import diagnose


class RecordingDiagnosticTransport:
    last_instance = None

    def __init__(
            self, config, callback, cancel_event=None, pairing_callback=None,
            allow_pairing=True):
        self.allow_pairing = allow_pairing
        RecordingDiagnosticTransport.last_instance = self

    async def connect(self):
        pass

    async def close(self):
        pass


class DiagnoseTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostic_explicitly_disables_pairing(self):
        config = DeviceConfig('D6:4D:F2:16:B6:BF')
        with patch('m832d_ble.diagnose.BleTransport', RecordingDiagnosticTransport), \
                patch('builtins.print'):
            await diagnose(config)
        self.assertFalse(RecordingDiagnosticTransport.last_instance.allow_pairing)


if __name__ == '__main__':
    unittest.main()
