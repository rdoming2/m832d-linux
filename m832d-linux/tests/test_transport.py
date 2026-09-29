import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dbus_fast import MessageType

from m832d_ble.config import DeviceConfig
from m832d_ble.model import CancelledError, PairingRequiredError, SetupRequiredError
from m832d_ble.transport import (
    BleTransport, connect_with_provisioned_le, explicit_le_connect,
)


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

    async def test_diagnostic_connection_does_not_pair(self):
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False},
            },
        )
        with self.assertRaises(PairingRequiredError):
            await explicit_le_connect(device, 'hci0', allow_pairing=False)

    async def test_pairing_precedes_explicit_le_connection(self):
        events = []
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def fake_pair(*args, **kwargs):
            events.append('PairBeforeConnect')

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=fake_pair):
            await explicit_le_connect(device, 'hci0', allow_pairing=True)
        self.assertLess(events.index('PairBeforeConnect'), events.index('ConnectDevice'))


if __name__ == '__main__':
    unittest.main()
