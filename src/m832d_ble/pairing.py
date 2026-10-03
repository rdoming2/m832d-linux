"""Bounded, exact-device BlueZ pairing for print jobs."""
import asyncio
import os

from dbus_fast import DBusError
from dbus_fast.service import ServiceInterface, method

from .model import CancelledError, PairingFailedError, PairingRequiredError


AGENT_MANAGER_PATH = '/org/bluez'
AGENT_INTERFACE = 'org.bluez.Agent1'
AGENT_MANAGER_INTERFACE = 'org.bluez.AgentManager1'
DEVICE_INTERFACE = 'org.bluez.Device1'
LE_BEARER_INTERFACE = 'org.bluez.Bearer.LE1'


class ExactDeviceAgent(ServiceInterface):
    """Temporary exact-device Just Works authorization without credentials.

    Confirmation and authorization are accepted only for the configured object
    path.  PIN, passkey, and display flows are rejected because the backend does
    not support interactive credentials.  The agent is never made BlueZ's
    default agent.
    """

    def __init__(self, device_path):
        super().__init__(AGENT_INTERFACE)
        self.device_path = device_path

    def _require_device(self, device):
        if device != self.device_path:
            raise DBusError('org.bluez.Error.Rejected', 'Unexpected pairing device')

    def _reject_credentials(self, device):
        self._require_device(device)
        raise DBusError(
            'org.bluez.Error.Rejected',
            'The printer requires interactive PIN or passkey entry',
        )

    @method()
    def Release(self):
        pass

    @method()
    def RequestPinCode(self, device: 'o') -> 's':
        self._reject_credentials(device)

    @method()
    def DisplayPinCode(self, device: 'o', pincode: 's'):
        self._reject_credentials(device)

    @method()
    def RequestPasskey(self, device: 'o') -> 'u':
        self._reject_credentials(device)

    @method()
    def DisplayPasskey(self, device: 'o', passkey: 'u', entered: 'q'):
        self._reject_credentials(device)

    @method()
    def RequestConfirmation(self, device: 'o', passkey: 'u'):
        self._require_device(device)

    @method()
    def RequestAuthorization(self, device: 'o'):
        self._require_device(device)

    @method()
    def AuthorizeService(self, device: 'o', uuid: 's'):
        self._require_device(device)

    @method()
    def Cancel(self):
        pass


async def pairing_state(call, device_path, discovered_props=None):
    """Return verified paired state, preferring exported LE bearer state.

    Every exported LE bearer must be paired, and explicit ``Bonded=False``
    invalidates ``Paired=True``; absent Bonded is tolerated for older BlueZ.
    Unsupported inspection APIs and inconclusive successful replies fall through
    to less detailed state.  Permission and other inspection failures do not
    silently trust stale discovery properties.
    """
    discovered_props = discovered_props or {}
    try:
        reply = await call(
            'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', target='/',
        )
    except RuntimeError as exc:
        if not _is_unsupported_inspection(exc):
            raise
    else:
        managed = reply.body[0]
        bearer_states = []
        device_state = None
        for path, interfaces in managed.items():
            if path == device_path and DEVICE_INTERFACE in interfaces:
                properties = interfaces[DEVICE_INTERFACE]
                paired = _property_bool(properties, 'Paired')
                bonded = _property_bool(properties, 'Bonded')
                device_state = paired is True and bonded is not False
            if path != device_path and not path.startswith(device_path + '/'):
                continue
            properties = interfaces.get(LE_BEARER_INTERFACE)
            if properties is not None:
                paired = _property_bool(properties, 'Paired')
                bonded = _property_bool(properties, 'Bonded')
                bearer_states.append(paired is True and bonded is not False)
        if bearer_states:
            return all(bearer_states)
        if device_state is not None:
            return device_state
    try:
        reply = await call(
            'org.freedesktop.DBus.Properties', 'GetAll', 's',
            [DEVICE_INTERFACE], target=device_path,
        )
    except RuntimeError as exc:
        if not _is_unsupported_inspection(exc):
            raise
    else:
        properties = reply.body[0]
        paired = _property_bool(properties, 'Paired')
        bonded = _property_bool(properties, 'Bonded')
        if paired is not None:
            return paired is True and bonded is not False
    paired = discovered_props.get('Paired')
    bonded = discovered_props.get('Bonded')
    if isinstance(paired, bool):
        return paired is True and bonded is not False
    return None


async def ensure_paired(
        bus, call, device_path, discovered_props, cancel_event, timeout,
        pairing_callback=None):
    """Pair once through a temporary non-default agent and verify the LE bond.

    Pairing is refused when existing bond state cannot be inspected.  Completion
    is rechecked before returning, and timeout/cancellation requests
    CancelPairing.  Cleanup attempts to unregister and unexport the temporary
    agent; unregister errors are suppressed.  Trust is deliberately applied
    later, only after verification.
    """
    try:
        paired = await pairing_state(call, device_path, discovered_props)
    except PairingRequiredError:
        raise
    except Exception as exc:
        raise PairingFailedError(
            f'Unable to inspect the configured LE pairing state: {exc}'
        ) from exc
    if paired is True:
        return False
    if paired is None:
        raise PairingRequiredError(
            'BlueZ did not expose enough state to verify the configured LE bond'
        )

    pairing_callback = pairing_callback or (lambda active: None)
    pairing_callback(True)
    agent_path = f'/org/m832d_ble/agent/{os.getpid()}_{id(bus):x}'
    agent = ExactDeviceAgent(device_path)
    registered = False
    exported = False
    try:
        bus.export(agent_path, agent)
        exported = True
        await call(
            AGENT_MANAGER_INTERFACE, 'RegisterAgent', 'os',
            [agent_path, 'NoInputNoOutput'], target=AGENT_MANAGER_PATH,
        )
        registered = True
        try:
            await _wait_for_pairing(
                call(DEVICE_INTERFACE, 'Pair', target=device_path),
                cancel_event, timeout,
            )
        except asyncio.CancelledError:
            await _cancel_pairing(call, device_path)
            raise
        except Exception:
            await _cancel_pairing(call, device_path)
            raise
        if await pairing_state(call, device_path, discovered_props) is not True:
            raise PairingFailedError(
                'BlueZ completed pairing without a verifiable LE bond'
            )
        return True
    except CancelledError:
        raise
    except PairingFailedError:
        raise
    except Exception as exc:
        raise PairingFailedError(f'Automatic LE pairing failed: {exc}') from exc
    finally:
        if registered:
            try:
                await call(
                    AGENT_MANAGER_INTERFACE, 'UnregisterAgent', 'o', [agent_path],
                    target=AGENT_MANAGER_PATH,
                )
            except Exception:
                pass
        try:
            if exported:
                bus.unexport(agent_path, agent)
        finally:
            pairing_callback(False)


async def _wait_for_pairing(awaitable, cancel_event, timeout):
    """Bound the sole Pair call and distinguish cancellation from failure."""
    pairing_task = asyncio.create_task(awaitable)
    cancellation_task = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {pairing_task, cancellation_task}, timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done and cancellation_task.result():
            pairing_task.cancel()
            await asyncio.gather(pairing_task, return_exceptions=True)
            raise CancelledError('Job cancelled during automatic LE pairing')
        if pairing_task not in done:
            pairing_task.cancel()
            await asyncio.gather(pairing_task, return_exceptions=True)
            raise PairingFailedError(
                f'Automatic LE pairing timed out after {timeout:g}s'
            )
        return pairing_task.result()
    finally:
        cancellation_task.cancel()
        await asyncio.gather(cancellation_task, return_exceptions=True)


async def _cancel_pairing(call, device_path):
    try:
        await call(DEVICE_INTERFACE, 'CancelPairing', target=device_path)
    except Exception:
        pass


def _property_bool(properties, name):
    value = properties.get(name)
    value = getattr(value, 'value', value)
    return value if isinstance(value, bool) else None


def _is_unsupported_inspection(exc):
    return any(marker in str(exc) for marker in (
        'UnknownMethod', 'UnknownInterface', 'NotSupported',
    ))
