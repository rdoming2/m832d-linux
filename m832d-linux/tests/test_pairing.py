import asyncio
from types import SimpleNamespace
import unittest

from dbus_fast import DBusError

from m832d_ble.model import CancelledError, PairingFailedError
from m832d_ble.pairing import ExactDeviceAgent, ensure_paired, pairing_state


DEVICE_PATH = '/org/bluez/hci0/dev_D6_4D_F2_16_B6_BF'


def variant(value):
    return SimpleNamespace(value=value)


def managed_state(paired, bonded=True, generic=None):
    generic = paired if generic is None else generic
    return {
        DEVICE_PATH: {
            'org.bluez.Device1': {
                'Paired': variant(generic),
                'Bonded': variant(bonded),
            },
        },
        DEVICE_PATH + '/le': {
            'org.bluez.Bearer.LE1': {
                'Paired': variant(paired),
                'Bonded': variant(bonded),
            },
        },
    }


class FakeBus:
    def __init__(self):
        self.exported = []
        self.unexported = []

    def export(self, path, agent):
        self.exported.append((path, agent))

    def unexport(self, path, agent):
        self.unexported.append((path, agent))


class PairingTests(unittest.IsolatedAsyncioTestCase):
    async def test_le_bearer_overrides_generic_paired_state(self):
        async def call(interface, member, signature='', body=None, target=None):
            return SimpleNamespace(body=[managed_state(False, generic=True)])

        self.assertFalse(await pairing_state(call, DEVICE_PATH, {'Paired': True}))

    async def test_unbonded_pairing_state_requires_pairing(self):
        async def call(interface, member, signature='', body=None, target=None):
            return SimpleNamespace(body=[managed_state(True, bonded=False)])

        self.assertFalse(await pairing_state(call, DEVICE_PATH, {'Paired': True}))

    async def test_already_paired_skips_agent_and_pair_call(self):
        bus = FakeBus()
        calls = []

        async def call(interface, member, signature='', body=None, target=None):
            calls.append(member)
            return SimpleNamespace(body=[managed_state(True)])

        paired = await ensure_paired(
            bus, call, DEVICE_PATH, {'Paired': True}, asyncio.Event(), 1,
        )
        self.assertFalse(paired)
        self.assertEqual(calls, ['GetManagedObjects'])
        self.assertEqual(bus.exported, [])

    async def test_just_works_pairing_is_verified_and_cleaned_up(self):
        bus = FakeBus()
        calls = []
        states = [managed_state(False), managed_state(True)]
        status = []

        async def call(interface, member, signature='', body=None, target=None):
            calls.append((member, target))
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[states.pop(0)])
            return SimpleNamespace(body=[])

        paired = await ensure_paired(
            bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 1,
            status.append,
        )
        self.assertTrue(paired)
        self.assertIn(('Pair', DEVICE_PATH), calls)
        self.assertEqual(sum(member == 'Pair' for member, target in calls), 1)
        self.assertNotIn(('RequestDefaultAgent', '/org/bluez'), calls)
        self.assertNotIn(('Set', DEVICE_PATH), calls)
        self.assertEqual(status, [True, False])
        self.assertEqual(len(bus.exported), 1)
        self.assertEqual(len(bus.unexported), 1)

    async def test_failed_pairing_is_cancelled_and_holds_as_setup_error(self):
        bus = FakeBus()
        calls = []

        async def call(interface, member, signature='', body=None, target=None):
            calls.append(member)
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[managed_state(False)])
            if member == 'Pair':
                raise RuntimeError('org.bluez.Error.AuthenticationRejected')
            return SimpleNamespace(body=[])

        with self.assertRaises(PairingFailedError):
            await ensure_paired(
                bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 1,
            )
        self.assertIn('CancelPairing', calls)
        self.assertIn('UnregisterAgent', calls)
        self.assertEqual(len(bus.unexported), 1)

    async def test_pairing_state_permission_failure_is_setup_error(self):
        bus = FakeBus()

        async def call(interface, member, signature='', body=None, target=None):
            raise RuntimeError('org.freedesktop.DBus.Error.AccessDenied')

        with self.assertRaises(PairingFailedError):
            await ensure_paired(
                bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 1,
            )
        self.assertEqual(bus.exported, [])

    async def test_unverified_pair_result_is_setup_error(self):
        bus = FakeBus()

        async def call(interface, member, signature='', body=None, target=None):
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[managed_state(False)])
            return SimpleNamespace(body=[])

        with self.assertRaises(PairingFailedError):
            await ensure_paired(
                bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 1,
            )
        self.assertEqual(len(bus.unexported), 1)

    async def test_pairing_timeout_cleans_up(self):
        bus = FakeBus()
        calls = []

        async def call(interface, member, signature='', body=None, target=None):
            calls.append(member)
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[managed_state(False)])
            if member == 'Pair':
                await asyncio.Event().wait()
            return SimpleNamespace(body=[])

        with self.assertRaises(PairingFailedError):
            await ensure_paired(
                bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 0.001,
            )
        self.assertIn('CancelPairing', calls)
        self.assertIn('UnregisterAgent', calls)

    async def test_pairing_cancellation_cleans_up(self):
        bus = FakeBus()
        cancel = asyncio.Event()

        async def call(interface, member, signature='', body=None, target=None):
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[managed_state(False)])
            if member == 'Pair':
                cancel.set()
                await asyncio.Event().wait()
            return SimpleNamespace(body=[])

        with self.assertRaises(CancelledError):
            await ensure_paired(
                bus, call, DEVICE_PATH, {'Paired': False}, cancel, 1,
            )
        self.assertEqual(len(bus.unexported), 1)

    async def test_external_task_cancellation_cancels_bluez_pairing(self):
        bus = FakeBus()
        calls = []
        pair_started = asyncio.Event()

        async def call(interface, member, signature='', body=None, target=None):
            calls.append(member)
            if member == 'GetManagedObjects':
                return SimpleNamespace(body=[managed_state(False)])
            if member == 'Pair':
                pair_started.set()
                await asyncio.Event().wait()
            return SimpleNamespace(body=[])

        task = asyncio.create_task(ensure_paired(
            bus, call, DEVICE_PATH, {'Paired': False}, asyncio.Event(), 1,
        ))
        await pair_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIn('CancelPairing', calls)
        self.assertIn('UnregisterAgent', calls)
        self.assertEqual(len(bus.unexported), 1)


class AgentTests(unittest.TestCase):
    def test_agent_accepts_only_expected_device(self):
        agent = ExactDeviceAgent(DEVICE_PATH)
        agent.RequestAuthorization(DEVICE_PATH)
        agent.RequestConfirmation(DEVICE_PATH, 123456)
        with self.assertRaises(DBusError):
            agent.RequestAuthorization('/org/bluez/hci0/dev_OTHER')

    def test_agent_rejects_pin_and_passkey_methods(self):
        agent = ExactDeviceAgent(DEVICE_PATH)
        with self.assertRaises(DBusError):
            agent.RequestPinCode(DEVICE_PATH)
        with self.assertRaises(DBusError):
            agent.RequestPasskey(DEVICE_PATH)


if __name__ == '__main__':
    unittest.main()
