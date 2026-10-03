"""CUPS backend entry point."""
import asyncio
import os
import signal
import sys
import time

from .channels import CupsChannels
from .config import format_device_uri, parse_device_uri
from .lock import PrinterLock
from .log import error, info, state
from .model import (
    BackendExit, CancelledError, JobInvocation, SetupRequiredError,
    TransportCleanupError,
)
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
    """List advertised M832D candidates; print jobs still select by address."""
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
    """Run one serialized job and map uncertainty to conservative CUPS exits.

    Failures requiring administrator setup hold the job, cancellation reports
    cancellation, and ordinary failures are retryable only while no write has
    been submitted.  Once a write may have reached the printer, including when
    teardown subsequently fails, replay could duplicate output and the queue is
    stopped instead.  Success establishes host-side delivery only, never
    physical print completion.
    """
    started = time.monotonic()
    cancel_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, cancel_event.set)
        except NotImplementedError:
            pass
    channels = channels or CupsChannels()
    transport = None
    source = None
    connecting = False
    pairing = False
    cleanup_error = None

    def pairing_status(active):
        nonlocal pairing
        pairing = active
        if active:
            info(f'job {invocation.job_id}: configured printer is unpaired; pairing automatically')
            state(add='authentication-required')
        else:
            state(remove='authentication-required')

    try:
        source = open(invocation.filename, 'rb') if invocation.filename else sys.stdin.buffer
        # Keep the per-printer lock through connection teardown.  Releasing it
        # sooner could let another backend interleave with an uncertain session.
        with PrinterLock(config.lock_key):
            try:
                info(f'job {invocation.job_id}: connecting to configured LE printer')
                state(add='connecting-to-device')
                connecting = True
                # Notifications cannot arrive until connect() subscribes, after
                # runtime has been assigned, so this closure is safe despite the
                # construction order.
                transport = transport_factory(
                    config, lambda data: runtime.notification(data), cancel_event,
                    pairing_status,
                )
                runtime = BackendRuntime(transport, channels, source, cancel_event)
                connect_task = asyncio.create_task(transport.connect())
                cancel_task = asyncio.create_task(cancel_event.wait())
                done, _ = await asyncio.wait(
                    {connect_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED,
                )
                # Cancellation wins a simultaneous race so transmission cannot
                # begin merely because connection setup also completed.
                if cancel_task in done and cancel_task.result():
                    connect_task.cancel()
                    await asyncio.gather(connect_task, return_exceptions=True)
                    raise CancelledError('Job cancelled while connecting')
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)
                await connect_task
                state(remove='connecting-to-device')
                connecting = False
                info(f'job {invocation.job_id}: BLE ready; transmitting vendor-filter output')
                await runtime.run()
                if runtime.back_channel_closed:
                    info(
                        f'job {invocation.job_id}: filter closed the back channel; '
                        'remaining notifications were discarded'
                    )
                info(
                    f'job {invocation.job_id}: submitted={transport.submitted_bytes} '
                    f'acknowledged={transport.acknowledged_bytes} '
                    f'elapsed={time.monotonic() - started:.3f}s; '
                    'physical completion is unconfirmed'
                )
                result = BackendExit.OK
            finally:
                if transport is not None:
                    try:
                        await transport.close()
                    except Exception as exc:
                        cleanup_error = exc
                        error(f'job {invocation.job_id}: cleanup failed: {exc}')
            if cleanup_error is not None:
                raise TransportCleanupError(str(cleanup_error)) from cleanup_error
            return result
    except SetupRequiredError as exc:
        error(f'job {invocation.job_id}: setup required: {exc}')
        state(add='authentication-required')
        return BackendExit.HOLD
    except CancelledError as exc:
        submitted = transport.submitted_bytes if transport is not None else 0
        acknowledged = transport.acknowledged_bytes if transport is not None else 0
        error(
            f'job {invocation.job_id}: {exc}; submitted={submitted} '
            f'acknowledged={acknowledged} elapsed={time.monotonic() - started:.3f}s'
        )
        return BackendExit.CANCEL
    except Exception as exc:
        submitted = transport.submitted_bytes if transport is not None else 0
        # Submission is counted before awaiting the ATT response.  Any positive
        # count therefore means delivery is uncertain and automatic replay is
        # unsafe, regardless of how many bytes were acknowledged.
        if submitted:
            acknowledged = transport.acknowledged_bytes
            error(
                f'job {invocation.job_id}: submitted={submitted} '
                f'acknowledged={acknowledged} elapsed={time.monotonic() - started:.3f}s; '
                f'data may have reached the printer and automatic replay is unsafe: {exc}'
            )
            state(add='uncertain-partial-print')
            return BackendExit.STOP
        error(f'job {invocation.job_id}: failed before transmission; retry is safe: {exc}')
        state(add='offline-report')
        return BackendExit.RETRY
    finally:
        if connecting:
            state(remove='connecting-to-device')
        if pairing:
            state(remove='authentication-required')
        if invocation.filename and source is not None:
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
