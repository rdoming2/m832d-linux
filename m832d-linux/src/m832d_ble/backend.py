"""CUPS backend entry point."""
import asyncio
import os
import signal
import sys

from .channels import CupsChannels
from .config import format_device_uri, parse_device_uri
from .lock import PrinterLock
from .log import error, info, state
from .model import BackendExit, CancelledError, JobInvocation, SetupRequiredError
from .runtime import BackendRuntime
from .transport import BleTransport


def parse_invocation(argv):
    if len(argv) not in (6, 7):
        raise ValueError('Expected job-id user title copies options [filename]')
    try:
        copies = int(argv[4])
    except ValueError:
        raise ValueError('copies must be an integer') from None
    if copies < 1:
        raise ValueError('copies must be positive')
    return JobInvocation(
        job_id=argv[1], user=argv[2], title=argv[3], copies=copies,
        options=argv[5], filename=argv[6] if len(argv) == 7 else None,
    )


async def discover(timeout=5.0):
    from bleak import BleakScanner

    devices = await BleakScanner.discover(
        timeout=timeout, return_adv=True,
        bluez={'filters': {'Transport': 'le'}},
    )
    records = []
    for device, advertisement in devices.values():
        name = advertisement.local_name or device.name or ''
        if name == 'M832D':
            records.append((device.address, name))
    return sorted(set(records))


async def run_job(invocation, config, channels=None, transport_factory=BleTransport):
    cancel_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, cancel_event.set)
        except NotImplementedError:
            pass
    source = open(invocation.filename, 'rb') if invocation.filename else sys.stdin.buffer
    channels = channels or CupsChannels()
    transport = None
    try:
        with PrinterLock(config.lock_key):
            info(f'job {invocation.job_id}: connecting to configured LE printer')
            state(add='connecting-to-device')
            transport = transport_factory(config, lambda data: runtime.notification(data), cancel_event)
            runtime = BackendRuntime(transport, channels, source, cancel_event)
            await transport.connect()
            state(remove='connecting-to-device')
            info(f'job {invocation.job_id}: BLE ready; transmitting vendor-filter output')
            await runtime.run()
            info(
                f'job {invocation.job_id}: transport accepted '
                f'{transport.acknowledged_bytes} bytes; physical completion is unconfirmed'
            )
            return BackendExit.OK
    except SetupRequiredError as exc:
        error(f'job {invocation.job_id}: setup required: {exc}')
        state(add='authentication-required')
        return BackendExit.HOLD
    except CancelledError as exc:
        error(f'job {invocation.job_id}: {exc}')
        return BackendExit.CANCEL
    except Exception as exc:
        submitted = transport.submitted_bytes if transport is not None else 0
        if submitted:
            error(
                f'job {invocation.job_id}: transport failed after {submitted} bytes may '
                f'have reached the printer; automatic replay is unsafe: {exc}'
            )
            state(add='uncertain-partial-print')
            return BackendExit.STOP
        error(f'job {invocation.job_id}: failed before transmission; retry is safe: {exc}')
        state(add='offline-report')
        return BackendExit.RETRY
    finally:
        if transport is not None:
            try:
                await transport.close()
            except Exception as exc:
                error(f'job {invocation.job_id}: cleanup failed: {exc}')
        if invocation.filename:
            source.close()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) == 1:
        try:
            for address, name in asyncio.run(discover()):
                uri = format_device_uri(address)
                print(f'direct {uri} "Phomemo {name}" "Phomemo {name} BLE"')
            return int(BackendExit.OK)
        except Exception as exc:
            error(f'BLE discovery failed: {exc}')
            return int(BackendExit.FAILED)
    try:
        invocation = parse_invocation(argv)
        uri = os.environ.get('DEVICE_URI')
        if not uri:
            raise ValueError('DEVICE_URI is required for a print job')
        config = parse_device_uri(uri)
    except (ValueError, OSError) as exc:
        error(str(exc))
        return int(BackendExit.STOP)
    return int(asyncio.run(run_job(invocation, config)))


if __name__ == '__main__':
    raise SystemExit(main())
