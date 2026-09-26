"""Explicit-LE BlueZ/Bleak transport for the M832D."""
import asyncio

from .model import CancelledError, SetupRequiredError


WRITE_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000ff03-0000-1000-8000-00805f9b34fb'


class BleTransport:
    def __init__(self, config, notification_callback, cancel_event=None):
        self.config = config
        self.notification_callback = notification_callback
        self.cancel_event = cancel_event or asyncio.Event()
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
            await explicit_le_connect(device, self.config.adapter)
        except Exception as exc:
            if _is_authentication_error(exc):
                raise SetupRequiredError(
                    'LE pairing is required before unattended printing'
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
                    'LE pairing is required before unattended printing'
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
                raise SetupRequiredError('LE pairing is required before unattended printing') from exc
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


async def explicit_le_connect(device, configured_adapter=None):
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
    if props.get('Paired') is False:
        raise SetupRequiredError('Configured printer is not paired on the LE bearer')

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
        try:
            await call('org.bluez.Adapter1', 'ConnectDevice', 'a{sv}', [{
                'Address': Variant('s', device.address),
                'AddressType': Variant('s', address_type),
            }], target=adapter_path)
        except RuntimeError as exc:
            if not any(marker in str(exc) for marker in ('UnknownMethod', 'NotSupported')):
                raise
            try:
                await connect_with_provisioned_le(call)
            except SetupRequiredError:
                raise
            except RuntimeError as fallback:
                raise RuntimeError(
                    'BlueZ cannot select an LE bearer explicitly; ConnectDevice or '
                    'PreferredBearer support is required'
                ) from fallback
    finally:
        bus.disconnect()


async def connect_with_provisioned_le(call):
    """Verify an administrator-provisioned LE preference without changing it."""
    reply = await call('org.freedesktop.DBus.Properties', 'Get', 'ss', [
        'org.bluez.Device1', 'PreferredBearer',
    ])
    if reply.body[0].value != 'le':
        raise SetupRequiredError(
            'BlueZ PreferredBearer must be provisioned as le before printing'
        )
    await call('org.bluez.Device1', 'Connect')


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
