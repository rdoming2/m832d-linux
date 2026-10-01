import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dbus_fast import MessageType

from m832d_ble.config import DeviceConfig
from m832d_ble.model import (
    CancelledError, PairingRequiredError, SetupRequiredError,
    TransportCleanupError,
)
from m832d_ble.transport import (
    BleTransport, connect_with_provisioned_le, ensure_preferred_le,
    ensure_trusted, explicit_le_connect, find_connected_device, _make_ble_device,
    _scanner_options,
)


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))


class ManagedFakeClient:
    def __init__(self, stop_error=None, disconnect_error=None):
        self.is_connected = True
        self.stop_error = stop_error
        self.disconnect_error = disconnect_error
        self.events = []

    async def stop_notify(self, characteristic):
        self.events.append('stop_notify')
        if self.stop_error:
            raise self.stop_error

    async def disconnect(self):
        self.events.append('disconnect')
        if self.disconnect_error:
            raise self.disconnect_error
        self.is_connected = False


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_ble_device_constructor_supports_current_api(self):
        class CurrentDevice:
            def __init__(self, address, name, details):
                self.values = (address, name, details)

        device = _make_ble_device(CurrentDevice, 'address', 'name', {}, -42)
        self.assertEqual(device.values, ('address', 'name', {}))

    def test_ble_device_constructor_supports_legacy_api_and_rssi(self):
        class LegacyDevice:
            def __init__(self, address, name, details, rssi):
                self.values = (address, name, details, rssi)

        device = _make_ble_device(LegacyDevice, 'address', 'name', {}, -42)
        self.assertEqual(device.values, ('address', 'name', {}, -42))

    def test_ble_device_constructor_preserves_missing_rssi_fallback(self):
        class LegacyDevice:
            def __init__(self, address, name, details, rssi):
                self.rssi = rssi

        device = _make_ble_device(LegacyDevice, 'address', 'name', {}, -127)
        self.assertEqual(device.rssi, -127)

    def test_ble_device_constructor_does_not_hide_other_type_errors(self):
        class BrokenDevice:
            def __init__(self, address, name, details):
                raise TypeError('invalid details')

        with self.assertRaisesRegex(TypeError, 'invalid details'):
            _make_ble_device(BrokenDevice, 'address', 'name', {}, -42)

    def test_scanner_options_keep_le_filter_and_explicit_adapter(self):
        options = _scanner_options(DeviceConfig('D6:4D:F2:16:B6:BF', adapter='hci1'))
        self.assertEqual(options, {
            'adapter': 'hci1',
            'bluez': {'filters': {'Transport': 'le'}},
        })

    async def test_close_stops_notifications_and_confirms_owned_disconnect(self):
        transport = BleTransport(DeviceConfig('D6:4D:F2:16:B6:BF'), lambda data: None)
        client = ManagedFakeClient()
        transport.client = client
        transport.device_path = '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'
        transport.owns_connection = True
        transport.notify_characteristic = object()
        transport.notifications_started = True
        with patch('m832d_ble.transport.device_connected_path', return_value=False) as connected:
            await transport.close()
        self.assertEqual(client.events, ['stop_notify', 'disconnect'])
        connected.assert_awaited_once_with(
            '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'
        )
        self.assertIsNone(transport.client)

    async def test_close_attempts_disconnect_after_stop_notify_failure(self):
        transport = BleTransport(DeviceConfig('D6:4D:F2:16:B6:BF'), lambda data: None)
        client = ManagedFakeClient(stop_error=RuntimeError('stop failed'))
        transport.client = client
        transport.device_path = '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'
        transport.owns_connection = True
        transport.notify_characteristic = object()
        transport.notifications_started = True
        with patch('m832d_ble.transport.device_connected_path', return_value=False):
            with self.assertRaises(TransportCleanupError):
                await transport.close()
        self.assertEqual(client.events, ['stop_notify', 'disconnect'])
        self.assertIsNone(transport.client)

    async def test_close_uses_bluez_fallback_without_bleak_client(self):
        transport = BleTransport(DeviceConfig('D6:4D:F2:16:B6:BF'), lambda data: None)
        path = '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'
        transport.device_path = path
        transport.owns_connection = True
        with patch('m832d_ble.transport.device_connected_path', return_value=True), \
                patch('m832d_ble.transport.disconnect_device_path') as disconnect:
            await transport.close()
        disconnect.assert_awaited_once_with(path)
        self.assertIsNone(transport.client)

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

    async def test_provisioned_bearer_accepts_existing_connection(self):
        async def call(interface, member, signature='', body=None, target=None):
            if member == 'Get':
                return SimpleNamespace(body=[SimpleNamespace(value='le')])
            raise RuntimeError('org.bluez.Error.AlreadyConnected')

        await connect_with_provisioned_le(call)

    async def test_diagnostic_connection_does_not_pair(self):
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False, 'Trusted': True},
            },
        )
        with self.assertRaises(PairingRequiredError):
            await explicit_le_connect(device, 'hci0', allow_pairing=False)

    async def test_existing_connected_device_is_adopted(self):
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': True, 'Trusted': True},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN,
                    body=[SimpleNamespace(value=True)],
                )

            def disconnect(self):
                pass

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()):
            self.assertTrue(await explicit_le_connect(device, 'hci0'))

    async def test_connected_device_can_be_recovered_without_advertisement(self):
        path = '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN,
                    body=[{
                        path: {
                            'org.bluez.Device1': {
                                'Address': SimpleNamespace(value='D6:4D:F2:16:B6:BF'),
                                'AddressType': SimpleNamespace(value='random'),
                                'Alias': SimpleNamespace(value='M832D'),
                                'Connected': SimpleNamespace(value=True),
                                'RSSI': SimpleNamespace(value=-42),
                            },
                        },
                    }],
                )

            def disconnect(self):
                pass

        config = DeviceConfig('D6:4D:F2:16:B6:BF', adapter='hci0')
        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()):
            device = await find_connected_device(config)
        self.assertEqual(device.address, config.address)
        self.assertEqual(device.details['path'], path)
        self.assertEqual(device.details['props']['RSSI'], -42)

    async def test_pairing_precedes_explicit_le_connection(self):
        events = []
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False, 'Trusted': True},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                if message.member == 'Get' and message.body[1] == 'Connected':
                    return SimpleNamespace(
                        message_type=MessageType.METHOD_RETURN,
                        body=[SimpleNamespace(value=False)],
                    )
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

    async def test_fresh_pairing_reuses_connected_le_bearer(self):
        events = []
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False, 'Trusted': True},
            },
        )

        class FakeBus:
            connected_checks = 0

            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                if message.member == 'Get':
                    if message.body[1] == 'Connected':
                        self.connected_checks += 1
                        return SimpleNamespace(
                            message_type=MessageType.METHOD_RETURN,
                            body=[SimpleNamespace(value=self.connected_checks > 1)],
                        )
                    return SimpleNamespace(
                        message_type=MessageType.METHOD_RETURN,
                        body=[SimpleNamespace(value=True)],
                    )
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def fake_pair(*args, **kwargs):
            events.append('Pair')
            return True

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=fake_pair):
            await explicit_le_connect(device, 'hci0', allow_pairing=True)
        self.assertEqual(events, ['Get', 'Pair', 'Get'])

    async def test_fresh_pairing_reconnects_the_sole_new_bond(self):
        events = []
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': False, 'Trusted': True},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                if message.member == 'Get':
                    if message.body[1] == 'Connected':
                        return SimpleNamespace(
                            message_type=MessageType.METHOD_RETURN,
                            body=[SimpleNamespace(value=False)],
                        )
                    return SimpleNamespace(
                        message_type=MessageType.METHOD_RETURN,
                        body=[SimpleNamespace(value=False)],
                    )
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def fake_pair(*args, **kwargs):
            events.append('Pair')
            return True

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=fake_pair):
            await explicit_le_connect(device, 'hci0', allow_pairing=True)
        self.assertEqual(events, ['Get', 'Pair', 'Get', 'Connect'])
        self.assertNotIn('ConnectDevice', events)

    async def test_random_address_reconnects_without_experimental_apis(self):
        events = []
        device = SimpleNamespace(
            address='D6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'random', 'Paired': True, 'Trusted': True},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                if message.member == 'ConnectDevice':
                    return SimpleNamespace(
                        message_type=MessageType.ERROR,
                        error_name='org.freedesktop.DBus.Error.UnknownMethod',
                        body=['ConnectDevice is unavailable'],
                    )
                if message.member == 'Get':
                    if message.body[1] == 'Connected':
                        return SimpleNamespace(
                            message_type=MessageType.METHOD_RETURN,
                            body=[SimpleNamespace(value=False)],
                        )
                    return SimpleNamespace(
                        message_type=MessageType.ERROR,
                        error_name='org.freedesktop.DBus.Error.UnknownProperty',
                        body=['PreferredBearer is unavailable'],
                    )
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def already_paired(*args, **kwargs):
            return False

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=already_paired):
            await explicit_le_connect(device, 'hci0', allow_pairing=True)
        self.assertEqual(events, ['Get', 'ConnectDevice', 'Get', 'Connect'])

    async def test_public_address_still_requires_explicit_bearer_api(self):
        device = SimpleNamespace(
            address='A6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_A6_4D_F2_16_B6_BF',
                'props': {'AddressType': 'public', 'Paired': True, 'Trusted': True},
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                if message.member == 'ConnectDevice':
                    return SimpleNamespace(
                        message_type=MessageType.ERROR,
                        error_name='org.freedesktop.DBus.Error.UnknownMethod',
                        body=['ConnectDevice is unavailable'],
                    )
                if message.member == 'Get':
                    if message.body[1] == 'Connected':
                        return SimpleNamespace(
                            message_type=MessageType.METHOD_RETURN,
                            body=[SimpleNamespace(value=False)],
                        )
                    return SimpleNamespace(
                        message_type=MessageType.ERROR,
                        error_name='org.freedesktop.DBus.Error.UnknownProperty',
                        body=['PreferredBearer is unavailable'],
                    )
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def already_paired(*args, **kwargs):
            return False

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=already_paired):
            with self.assertRaisesRegex(SetupRequiredError, 'PreferredBearer=le'):
                await explicit_le_connect(device, 'hci0', allow_pairing=True)

    async def test_public_address_uses_existing_le_preference(self):
        events = []
        device = SimpleNamespace(
            address='A6:4D:F2:16:B6:BF',
            details={
                'path': '/org/bluez/hci0/dev_A6_4D_F2_16_B6_BF',
                'props': {
                    'AddressType': 'public', 'Paired': True, 'Trusted': True,
                },
            },
        )

        class FakeBus:
            async def connect(self):
                return self

            async def call(self, message):
                events.append(message.member)
                if message.member == 'ConnectDevice':
                    return SimpleNamespace(
                        message_type=MessageType.ERROR,
                        error_name='org.freedesktop.DBus.Error.UnknownMethod',
                        body=['ConnectDevice is unavailable'],
                    )
                if message.member == 'Get':
                    if message.body[1] == 'Connected':
                        return SimpleNamespace(
                            message_type=MessageType.METHOD_RETURN,
                            body=[SimpleNamespace(value=False)],
                        )
                    return SimpleNamespace(
                        message_type=MessageType.METHOD_RETURN,
                        body=[SimpleNamespace(value='le')],
                    )
                return SimpleNamespace(
                    message_type=MessageType.METHOD_RETURN, body=[],
                )

            def disconnect(self):
                pass

        async def already_paired(*args, **kwargs):
            return False

        with patch('dbus_fast.aio.MessageBus', return_value=FakeBus()), \
                patch('m832d_ble.transport.ensure_paired', new=already_paired):
            await explicit_le_connect(device, 'hci0', allow_pairing=True)
        self.assertEqual(events, ['Get', 'Get', 'ConnectDevice', 'Get', 'Connect'])

    async def test_preferred_bearer_is_set_and_verified(self):
        calls = []
        values = ['bredr', 'le']

        async def call(interface, member, signature='', body=None, target=None):
            calls.append((member, body))
            if member == 'Get':
                return SimpleNamespace(body=[SimpleNamespace(value=values.pop(0))])
            return SimpleNamespace(body=[])

        changed = await ensure_preferred_le(call)
        self.assertTrue(changed)
        self.assertEqual([member for member, body in calls], ['Get', 'Set', 'Get'])
        self.assertEqual(calls[1][1][1], 'PreferredBearer')
        self.assertEqual(calls[1][1][2].value, 'le')

    async def test_trusted_is_set_and_verified(self):
        calls = []
        values = [False, True]

        async def call(interface, member, signature='', body=None, target=None):
            calls.append((member, body))
            if member == 'Get':
                return SimpleNamespace(body=[SimpleNamespace(value=values.pop(0))])
            return SimpleNamespace(body=[])

        changed = await ensure_trusted(call, {'Trusted': False})
        self.assertTrue(changed)
        self.assertEqual([member for member, body in calls], ['Get', 'Set', 'Get'])
        self.assertEqual(calls[1][1][1], 'Trusted')
        self.assertIs(calls[1][1][2].value, True)


if __name__ == '__main__':
    unittest.main()
