import asyncio
from types import SimpleNamespace
import unittest

from m832d_ble.config import DeviceConfig
from m832d_ble.model import CancelledError, SetupRequiredError
from m832d_ble.transport import BleTransport, connect_with_provisioned_le


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledged_chunks_preserve_order_and_limit(self):
        transport = BleTransport(DeviceConfig('D6:4D:F2:16:B6:BF'), lambda data: None)
        transport.client = FakeClient()
        transport.write_characteristic = object()
        payload = bytes(range(256)) * 2
        await transport.write(payload)
        chunks = transport.client.writes
        self.assertEqual(b''.join(item[1] for item in chunks), payload)
        self.assertTrue(all(item[2] is True for item in chunks))
        self.assertTrue(all(len(item[1]) <= 182 for item in chunks))
        self.assertEqual(transport.acknowledged_bytes, len(payload))

    async def test_cancelled_write_submits_no_next_chunk(self):
        cancel = asyncio.Event()
        cancel.set()
        transport = BleTransport(
            DeviceConfig('D6:4D:F2:16:B6:BF'), lambda data: None, cancel,
        )
        transport.client = FakeClient()
        transport.write_characteristic = object()
        with self.assertRaises(CancelledError):
            await transport.write(b'data')
        self.assertEqual(transport.client.writes, [])

    async def test_fallback_only_reads_preprovisioned_bearer(self):
        calls = []

        async def call(interface, member, signature='', body=None, target=None):
            calls.append((interface, member, body))
            if member == 'Get':
                return SimpleNamespace(body=[SimpleNamespace(value='le')])
            return SimpleNamespace(body=[])

        await connect_with_provisioned_le(call)
        self.assertEqual([item[1] for item in calls], ['Get', 'Connect'])
        self.assertNotIn('Set', [item[1] for item in calls])

    async def test_unprovisioned_bearer_requires_setup(self):
        async def call(interface, member, signature='', body=None, target=None):
            return SimpleNamespace(body=[SimpleNamespace(value='bredr')])

        with self.assertRaises(SetupRequiredError):
            await connect_with_provisioned_le(call)


if __name__ == '__main__':
    unittest.main()
