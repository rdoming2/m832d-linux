"""Explicit-LE BlueZ/Bleak transport for the M832D."""
import asyncio

from .model import (
    CancelledError, PairingRequiredError, SetupRequiredError,
    TransportCleanupError,
)
from .pairing import ensure_paired


WRITE_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000ff03-0000-1000-8000-00805f9b34fb'


class BleTransport:
    """Exact-address, explicit-LE transport for one ordered byte stream.

    Characteristics are resolved by UUID for each connection and writes are
    serialized with ATT responses; no transport retry is performed.  A byte is
    ``submitted`` before its write is awaited because an error cannot prove
    non-delivery, and is ``acknowledged`` only after that await succeeds.  Both
    counters describe host-side transport, not physical printing.
    """
    def __init__(
            self, config, notification_callback, cancel_event=None,
            pairing_callback=None, allow_pairing=True):
        self.config = config
        self.notification_callback = notification_callback
        self.cancel_event = cancel_event or asyncio.Event()
        self.pairing_callback = pairing_callback or (lambda active: None)
        self.allow_pairing = allow_pairing
        self.client = None
        self.device_path = None
        self.owns_connection = False
        self.write_characteristic = None
        self.notify_characteristic = None
        self.notifications_started = False
        self.submitted_bytes = 0
        self.acknowledged_bytes = 0

    async def connect(self):
        """Select the exact LE device and establish the required GATT channels."""
        from bleak import BleakClient, BleakScanner

        # A connected printer may stop advertising. Check BlueZ first so the
        # filter can begin its readiness exchange without waiting for a full
        # discovery timeout.
        device = await find_connected_device(self.config)
        if device is None:
            scanner_options = _scanner_options(self.config)
            device = await BleakScanner.find_device_by_filter(
                lambda found, advertisement: found.address.lower() == self.config.address.lower(),
                timeout=self.config.scan_timeout,
                **scanner_options,
            )
        if device is None:
            raise RuntimeError(
                'Configured printer was not found during the bounded LE scan '
                'or as an already-connected BlueZ LE device'
            )
        self.device_path = device.details.get('path')
        try:
            self.owns_connection = await explicit_le_connect(
                device, self.config.adapter, self.cancel_event,
                self.config.connect_timeout, self.allow_pairing,
                self.pairing_callback,
            )
        except Exception as exc:
            if _is_authentication_error(exc):
                exc = SetupRequiredError(
                    'LE authentication failed; automatic pairing or bond recovery is required'
                )
            await self._rollback_connection()
            raise exc
        try:
            self.client = BleakClient(device, timeout=self.config.connect_timeout)
            await _wait_or_cancel(
                self.client.connect(), self.cancel_event, self.config.connect_timeout,
                'connection',
            )
        except Exception as exc:
            if _is_authentication_error(exc):
                raise SetupRequiredError(
                    'LE authentication failed; automatic pairing or bond recovery is required'
                ) from exc
            raise
        # ATT handles vary by device and connection, so captured numeric handles
        # are never production configuration.  Acknowledged FF02 writes and FF03
        # notifications are required before any job bytes are accepted.
        self.write_characteristic = self.client.services.get_characteristic(WRITE_UUID)
        self.notify_characteristic = self.client.services.get_characteristic(NOTIFY_UUID)
        if self.write_characteristic is None or self.notify_characteristic is None:
            raise RuntimeError('Required FF02/FF03 characteristics are missing')
        if 'write' not in self.write_characteristic.properties:
            raise RuntimeError('FF02 does not support acknowledged writes')
        if 'notify' not in self.notify_characteristic.properties:
            raise RuntimeError('FF03 does not support notifications')
        try:
            await _wait_or_cancel(
                self.client.start_notify(self.notify_characteristic, self._notify),
                self.cancel_event, self.config.connect_timeout, 'notification setup',
            )
            self.notifications_started = True
        except Exception as exc:
            if _is_authentication_error(exc):
                exc = SetupRequiredError(
                    'LE authentication failed; automatic pairing or bond recovery is required'
                )
            await self._rollback_connection()
            raise exc

    async def close(self):
        """Perform bounded teardown and report an unverified owned disconnect.

        Cleanup continues after individual failures so notifications, Bleak, and
        the exact BlueZ connection all get a chance to close.  Local state is
        reset before raising because callers use cleanup failure in retry policy.
        """
        client = self.client
        device_path = self.device_path
        owns_connection = self.owns_connection
        cleanup_errors = []
        try:
            if (
                    client is not None and self.notify_characteristic is not None
                    and client.is_connected and self.notifications_started
            ):
                try:
                    await asyncio.wait_for(client.stop_notify(self.notify_characteristic), 5.0)
                except Exception as exc:
                    cleanup_errors.append(exc)
        finally:
            if client is not None:
                try:
                    if client.is_connected:
                        await asyncio.wait_for(client.disconnect(), 5.0)
                except Exception as exc:
                    cleanup_errors.append(exc)
            if owns_connection and device_path is not None:
                try:
                    if await device_connected_path(device_path):
                        await disconnect_device_path(device_path)
                except Exception as exc:
                    cleanup_errors.append(exc)
            self.client = None
            self.device_path = None
            self.owns_connection = False
            self.write_characteristic = None
            self.notify_characteristic = None
            self.notifications_started = False
        if cleanup_errors:
            raise TransportCleanupError(
                f'BLE teardown failed: {cleanup_errors[-1]}'
            ) from cleanup_errors[-1]

    async def _rollback_connection(self):
        try:
            await self.close()
        except TransportCleanupError:
            pass

    async def write(self, data):
        """Write opaque bytes sequentially, without delay, framing, or retry."""
        if self.client is None or self.write_characteristic is None:
            raise RuntimeError('BLE transport is not connected')
        for offset in range(0, len(data), self.config.chunk_size):
            if self.cancel_event.is_set():
                raise CancelledError('Job cancelled; already accepted data may still print')
            chunk = data[offset:offset + self.config.chunk_size]
            # Advance before the await: timeout, cancellation, or an error leaves
            # peripheral receipt uncertain.  ATT success still does not establish
            # that the printer physically processed the bytes.
            self.submitted_bytes += len(chunk)
            try:
                await _wait_or_cancel(
                    self.client.write_gatt_char(
                        self.write_characteristic, chunk, response=True,
                    ),
                    self.cancel_event, self.config.write_timeout, 'write',
                )
            except Exception:
                raise
            self.acknowledged_bytes += len(chunk)

    def _notify(self, sender, data):
        self.notification_callback(bytes(data))


async def explicit_le_connect(
        device, configured_adapter=None, cancel_event=None, pair_timeout=25.0,
        allow_pairing=False, pairing_callback=None):
    """Connect the exact BlueZ device without an ambiguous bearer fallback.

    An existing exact-address connection is adopted.  Otherwise this prefers
    Adapter1.ConnectDevice, permits generic Device1.Connect only for a sole new
    LE bond, a random address, or verified PreferredBearer=le, and fails closed
    for an ambiguous public-address device.  Pairing and connection each receive
    one bounded attempt; connections created during a failed attempt receive a
    best-effort rollback.
    """
    from dbus_fast import Message, MessageType, Variant, BusType
    from dbus_fast.aio import MessageBus

    path = device.details.get('path')
    props = device.details.get('props', {})
    if not path:
        raise RuntimeError('BlueZ discovery did not provide a device object path')
    adapter_path = path.rsplit('/', 1)[0]
    if configured_adapter and adapter_path.rsplit('/', 1)[-1] != configured_adapter:
        raise RuntimeError('Printer was discovered through an adapter other than the configured adapter')
    address_type = props.get('AddressType')
    if address_type not in ('public', 'random'):
        raise RuntimeError('BlueZ discovery did not provide an LE address type')
    if not allow_pairing and props.get('Paired') is not True:
        raise PairingRequiredError(
            'Configured printer is not paired on the LE bearer; '
            'diagnostics do not initiate pairing'
        )
    bus = await asyncio.wait_for(
        MessageBus(bus_type=BusType.SYSTEM).connect(), 5,
    )

    async def call(interface, member, signature='', body=None, target=path):
        # Cap every D-Bus call independently and normalize BlueZ error replies so
        # only explicit unsupported-capability errors enter fallback branches.
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path=target, interface=interface,
            member=member, signature=signature, body=body or [],
        )), 30)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        return reply

    initial_connected = False
    owns_connection = False
    try:
        initial_connected = await device_connected(call)
        if initial_connected:
            # A connected exact-address device may not advertise. Bleak can
            # adopt it using the BlueZ object path discovered above.
            return True
        newly_paired = False
        if allow_pairing:
            if address_type == 'public':
                await ensure_preferred_le(call)
            newly_paired = await ensure_paired(
                bus, call, path, props, cancel_event or asyncio.Event(), pair_timeout,
                pairing_callback,
            )
            await ensure_trusted(call, props)
        if newly_paired:
            if await device_connected(call):
                # Device1.Pair connected over the LE discovery path and completed
                # service discovery. Keep that selected bearer for Bleak to reuse.
                return True
            # The new LE bond is the only bond because pairing was entered only
            # after verifying that no bond existed. BlueZ selects the sole bonded
            # bearer even when its experimental bearer-selection APIs are absent.
            await connect_device(call)
            return True
        try:
            await call('org.bluez.Adapter1', 'ConnectDevice', 'a{sv}', [{
                'Address': Variant('s', device.address),
                'AddressType': Variant('s', address_type),
            }], target=adapter_path)
        except RuntimeError as exc:
            if 'AlreadyConnected' in str(exc):
                owns_connection = True
            elif not any(marker in str(exc) for marker in ('UnknownMethod', 'NotSupported')):
                raise
            else:
                try:
                    await connect_with_provisioned_le(call)
                except SetupRequiredError:
                    raise
                except RuntimeError as fallback:
                    unsupported = any(marker in str(fallback) for marker in (
                        'UnknownProperty', 'UnknownInterface', 'NotSupported',
                    ))
                    if not unsupported:
                        raise
                    if address_type == 'random':
                        # A random Bluetooth address cannot identify a BR/EDR
                        # bearer, so Device1.Connect remains explicitly LE.
                        await connect_device(call)
                    else:
                        raise RuntimeError(
                            'BlueZ cannot select an LE bearer explicitly for this '
                            'public-address device; ConnectDevice or PreferredBearer '
                            'support is required'
                        ) from fallback
        if not owns_connection:
            owns_connection = True
        return owns_connection
    except BaseException:
        if not initial_connected:
            try:
                if await device_connected(call):
                    await call('org.bluez.Device1', 'Disconnect')
            except Exception:
                pass
        raise
    finally:
        bus.disconnect()


async def device_connected(call):
    reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
        'org.bluez.Device1', 'Connected',
    ])
    value = getattr(reply.body[0], 'value', reply.body[0])
    if not isinstance(value, bool):
        raise RuntimeError('BlueZ Device1.Connected did not contain a boolean')
    return value


async def find_connected_device(config):
    """Recover an exact configured LE device that is not advertising."""
    from bleak.backends.device import BLEDevice
    from dbus_fast import Message, MessageType, BusType
    from dbus_fast.aio import MessageBus

    bus = await asyncio.wait_for(
        MessageBus(bus_type=BusType.SYSTEM).connect(), config.scan_timeout,
    )
    try:
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path='/',
            interface='org.freedesktop.DBus.ObjectManager',
            member='GetManagedObjects', signature='', body=[],
        )), config.scan_timeout)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        for path, interfaces in reply.body[0].items():
            device_props = interfaces.get('org.bluez.Device1')
            if device_props is None:
                continue
            props = {
                name: getattr(value, 'value', value)
                for name, value in device_props.items()
            }
            if str(props.get('Address', '')).lower() != config.address.lower():
                continue
            adapter_path = path.rsplit('/', 1)[0]
            if config.adapter and adapter_path.rsplit('/', 1)[-1] != config.adapter:
                continue
            if props.get('Connected') is not True:
                continue
            address_type = props.get('AddressType')
            if address_type not in ('public', 'random'):
                continue
            return _make_ble_device(
                BLEDevice,
                config.address, props.get('Alias') or props.get('Name') or '',
                {'path': path, 'props': props},
                props.get('RSSI', -127),
            )
        return None
    finally:
        bus.disconnect()


def _make_ble_device(device_type, address, name, details, rssi):
    """Construct a Bleak device across legacy and current Bleak APIs."""
    try:
        return device_type(address, name, details)
    except TypeError as exc:
        text = str(exc)
        if 'missing' not in text or 'required positional argument' not in text \
                or "'rssi'" not in text:
            raise
        return device_type(address, name, details, rssi=rssi)


def _scanner_options(config):
    """Build scanner arguments accepted by legacy and current Bleak."""
    options = {'bluez': {'filters': {'Transport': 'le'}}}
    if config.adapter:
        options['adapter'] = config.adapter
    return options


async def device_connected_path(path):
    """Read the exact device connection state through the system bus."""
    from dbus_fast import Message, MessageType, BusType
    from dbus_fast.aio import MessageBus

    bus = await asyncio.wait_for(
        MessageBus(bus_type=BusType.SYSTEM).connect(), 5,
    )
    try:
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path=path,
            interface='org.freedesktop.DBus.Properties', member='Get',
            signature='ss', body=['org.bluez.Device1', 'Connected'],
        )), 5)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        value = getattr(reply.body[0], 'value', reply.body[0])
        if not isinstance(value, bool):
            raise RuntimeError('BlueZ Device1.Connected did not contain a boolean')
        return value
    finally:
        bus.disconnect()


async def disconnect_device_path(path):
    """Disconnect and verify the exact BlueZ device path."""
    from dbus_fast import Message, MessageType, BusType
    from dbus_fast.aio import MessageBus

    bus = await asyncio.wait_for(
        MessageBus(bus_type=BusType.SYSTEM).connect(), 5,
    )
    try:
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path=path, interface='org.bluez.Device1',
            member='Disconnect', signature='', body=[],
        )), 5)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
    finally:
        bus.disconnect()
    for _ in range(10):
        if not await device_connected_path(path):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError('BlueZ did not confirm printer disconnection')


async def connect_device(call):
    try:
        await call('org.bluez.Device1', 'Connect')
    except RuntimeError as exc:
        if 'AlreadyConnected' not in str(exc):
            raise


async def ensure_preferred_le(call):
    """Provision and verify the exact device's persistent LE preference."""
    from dbus_fast import Variant

    try:
        reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
            'org.bluez.Device1', 'PreferredBearer',
        ])
        if reply.body[0].value == 'le':
            return False
        await call('org.freedesktop.DBus.Properties', 'Set', 'ssv', [
            'org.bluez.Device1', 'PreferredBearer', Variant('s', 'le'),
        ])
        reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
            'org.bluez.Device1', 'PreferredBearer',
        ])
    except RuntimeError as exc:
        raise SetupRequiredError(
            f'Unable to provision PreferredBearer=le for the configured printer: {exc}'
        ) from exc
    if reply.body[0].value != 'le':
        raise SetupRequiredError(
            'BlueZ did not retain PreferredBearer=le for the configured printer'
        )
    return True


async def ensure_trusted(call, discovered_props=None):
    """Trust only the exact configured device after its LE bond is verified."""
    from dbus_fast import Variant

    discovered_props = discovered_props or {}
    if discovered_props.get('Trusted') is True:
        return False
    try:
        reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
            'org.bluez.Device1', 'Trusted',
        ])
        if reply.body[0].value is True:
            return False
        await call('org.freedesktop.DBus.Properties', 'Set', 'ssv', [
            'org.bluez.Device1', 'Trusted', Variant('b', True),
        ])
        reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
            'org.bluez.Device1', 'Trusted',
        ])
    except RuntimeError as exc:
        raise SetupRequiredError(
            f'Unable to trust the configured printer after pairing: {exc}'
        ) from exc
    if reply.body[0].value is not True:
        raise SetupRequiredError('BlueZ did not retain Trusted=true for the configured printer')
    return True


async def connect_with_provisioned_le(call):
    """Verify an administrator-provisioned LE preference without changing it."""
    reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
        'org.bluez.Device1', 'PreferredBearer',
    ])
    if reply.body[0].value != 'le':
        raise SetupRequiredError(
            'BlueZ PreferredBearer must be provisioned as le before printing'
        )
    await connect_device(call)


async def _wait_or_cancel(awaitable, cancel_event, timeout, operation):
    """Race one bounded operation against cancellation without retrying it.

    Cancellation wins if both tasks complete together.  Abandoned work is
    cancelled and awaited so no write or connection attempt survives the result;
    after a timeout the remote side may nevertheless already have acted.
    """
    operation_task = asyncio.create_task(awaitable)
    cancellation_task = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {operation_task, cancellation_task}, timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done and cancellation_task.result():
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise CancelledError(
                f'Job cancelled during BLE {operation}; accepted data may still print'
            )
        if operation_task not in done:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise TimeoutError(f'BLE {operation} timed out after {timeout:g}s')
        return operation_task.result()
    finally:
        cancellation_task.cancel()
        await asyncio.gather(cancellation_task, return_exceptions=True)


def _is_authentication_error(exc):
    text = str(exc).lower()
    return any(marker in text for marker in (
        'authentication', 'not authorized', 'notauthorized',
        'insufficient authentication',
    ))
