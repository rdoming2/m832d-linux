"""Explicit-LE BlueZ/Bleak transport for the M832D."""
import asyncio

from .model import CancelledError, PairingRequiredError, SetupRequiredError
from .pairing import ensure_paired


WRITE_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000ff03-0000-1000-8000-00805f9b34fb'


class BleTransport:
    def __init__(
            self, config, notification_callback, cancel_event=None,
            pairing_callback=None, allow_pairing=True):
        self.config = config
        self.notification_callback = notification_callback
        self.cancel_event = cancel_event or asyncio.Event()
        self.pairing_callback = pairing_callback or (lambda active: None)
        self.allow_pairing = allow_pairing
        self.client = None
        self.write_characteristic = None
        self.notify_characteristic = None
        self.submitted_bytes = 0
        self.acknowledged_bytes = 0

    async def connect(self):
        from bleak import BleakClient, BleakScanner

        scanner_options = {'filters': {'Transport': 'le'}}
        if self.config.adapter:
            scanner_options['adapter'] = self.config.adapter
        device = await BleakScanner.find_device_by_filter(
            lambda found, advertisement: found.address.lower() == self.config.address.lower(),
            timeout=self.config.scan_timeout,
            bluez=scanner_options,
        )
        if device is None:
            raise RuntimeError('Configured printer was not found during the bounded LE scan')
        try:
            await explicit_le_connect(
                device, self.config.adapter, self.cancel_event,
                self.config.connect_timeout, self.allow_pairing,
                self.pairing_callback,
            )
        except Exception as exc:
            if _is_authentication_error(exc):
                raise SetupRequiredError(
                    'LE authentication failed; automatic pairing or bond recovery is required'
                ) from exc
            raise
        self.client = BleakClient(device, timeout=self.config.connect_timeout)
        try:
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
        except Exception as exc:
            if _is_authentication_error(exc):
                raise SetupRequiredError(
                    'LE authentication failed; automatic pairing or bond recovery is required'
                ) from exc
            raise

    async def close(self):
        if self.client is None:
            return
        try:
            if self.notify_characteristic is not None and self.client.is_connected:
                await asyncio.wait_for(
                    self.client.stop_notify(self.notify_characteristic), 5.0,
                )
        finally:
            if self.client.is_connected:
                await asyncio.wait_for(self.client.disconnect(), 5.0)
            self.client = None

    async def write(self, data):
        if self.client is None or self.write_characteristic is None:
            raise RuntimeError('BLE transport is not connected')
        for offset in range(0, len(data), self.config.chunk_size):
            if self.cancel_event.is_set():
                raise CancelledError('Job cancelled; already accepted data may still print')
            chunk = data[offset:offset + self.config.chunk_size]
            self.submitted_bytes += len(chunk)
            try:
                await _wait_or_cancel(
                    self.client.write_gatt_char(
                        self.write_characteristic, chunk, response=True,
                    ),
                    self.cancel_event, self.config.write_timeout, 'write',
                )
            except Exception:
                # submitted_bytes deliberately remains advanced: the peripheral may have received it.
                raise
            self.acknowledged_bytes += len(chunk)

    def _notify(self, sender, data):
        self.notification_callback(bytes(data))


async def explicit_le_connect(
        device, configured_adapter=None, cancel_event=None, pair_timeout=25.0,
        allow_pairing=False, pairing_callback=None):
    """Use BlueZ APIs that select LE explicitly; never use a generic bearer fallback."""
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
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    async def call(interface, member, signature='', body=None, target=path):
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path=target, interface=interface,
            member=member, signature=signature, body=body or [],
        )), 30)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        return reply

    try:
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
                return
            # The new LE bond is the only bond because pairing was entered only
            # after verifying that no bond existed. BlueZ selects the sole bonded
            # bearer even when its experimental bearer-selection APIs are absent.
            await connect_device(call)
            return
        try:
            await call('org.bluez.Adapter1', 'ConnectDevice', 'a{sv}', [{
                'Address': Variant('s', device.address),
                'AddressType': Variant('s', address_type),
            }], target=adapter_path)
        except RuntimeError as exc:
            if 'AlreadyConnected' in str(exc):
                pass
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
