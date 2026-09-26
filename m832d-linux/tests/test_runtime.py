import asyncio
from io import BytesIO
import os
import unittest

from m832d_ble.channels import SideCommand, SideRequest, SideStatus
from m832d_ble.model import CancelledError
from m832d_ble.runtime import BackendRuntime, TransferTracker


class FakeTransport:
    def __init__(self, *, fail_after=None, delay=0):
        self.data = bytearray()
        self.fail_after = fail_after
        self.delay = delay

    async def write(self, data):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_after is not None and len(self.data) >= self.fail_after:
            raise RuntimeError('injected write failure')
        self.data.extend(data)


class FakeChannels:
    def __init__(self, requests=(), back_error=None, side_error=None):
        self.requests = list(requests)
        self.responses = []
        self.back = []
        self.back_error = back_error
        self.side_error = side_error

    def read_side(self, timeout):
        if self.side_error:
            raise self.side_error
        return self.requests.pop(0) if self.requests else None

    def write_side(self, command, status, data=b'', timeout=1.0):
        self.responses.append((command, status, data))

    def write_back(self, data, timeout=1.0):
        if self.back_error:
            raise self.back_error
        self.back.append(data)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_large_binary_stream(self):
        payload = bytes(range(256)) * 80
        transport = FakeTransport()
        channels = FakeChannels()
        runtime = BackendRuntime(
            transport, channels, BytesIO(payload), asyncio.Event(), queue_chunks=2,
        )
        await runtime.run()
        self.assertEqual(bytes(transport.data), payload)
        self.assertEqual(runtime.tracker.produced, len(payload))
        self.assertEqual(runtime.tracker.acknowledged, len(payload))

    async def test_drain_and_capability_responses(self):
        requests = [
            SideRequest(SideCommand.GET_BIDI, b''),
            SideRequest(SideCommand.GET_CONNECTED, b''),
            SideRequest(SideCommand.GET_STATE, b''),
            SideRequest(SideCommand.SOFT_RESET, b''),
            SideRequest(SideCommand.DRAIN_OUTPUT, b''),
        ]
        payload = b'x' * 8192
        transport = FakeTransport(delay=0.002)
        channels = FakeChannels(requests)
        runtime = BackendRuntime(
            transport, channels, BytesIO(payload), asyncio.Event(), queue_chunks=4,
        )
        await runtime.run()
        response_map = {command: (status, data) for command, status, data in channels.responses}
        self.assertEqual(response_map[SideCommand.GET_BIDI], (SideStatus.OK, b'\x01'))
        self.assertEqual(response_map[SideCommand.GET_CONNECTED], (SideStatus.OK, b'\x01'))
        self.assertEqual(response_map[SideCommand.SOFT_RESET], (SideStatus.NOT_IMPLEMENTED, b''))
        self.assertEqual(response_map[SideCommand.DRAIN_OUTPUT], (SideStatus.OK, b''))

    async def test_tracker_drain_waits_for_barrier(self):
        tracker = TransferTracker()
        await tracker.add_produced(100)
        waiter = asyncio.create_task(tracker.wait_acknowledged(100, timeout=1))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        await tracker.add_acknowledged(99)
        self.assertFalse(waiter.done())
        await tracker.add_acknowledged(1)
        await waiter

    async def test_drain_barrier_captures_cross_descriptor_race(self):
        tracker = TransferTracker()

        async def delayed_producer():
            await asyncio.sleep(0.002)
            await tracker.add_produced(3)

        producer = asyncio.create_task(delayed_producer())
        self.assertEqual(await tracker.capture_drain_barrier(), 3)
        await producer

    async def test_drain_returns_timeout_before_stale_response(self):
        channels = FakeChannels([SideRequest(SideCommand.DRAIN_OUTPUT, b'')])
        runtime = BackendRuntime(
            FakeTransport(delay=0.2), channels, BytesIO(b'x' * 4096),
            asyncio.Event(),
        )
        await runtime.run()
        self.assertIn(
            (SideCommand.DRAIN_OUTPUT, SideStatus.TIMEOUT, b''),
            channels.responses,
        )

    async def test_cancellation_stops_before_next_chunk(self):
        cancel = asyncio.Event()

        class CancellingTransport(FakeTransport):
            async def write(inner_self, data):
                await super(CancellingTransport, inner_self).write(data)
                cancel.set()

        runtime = BackendRuntime(
            CancellingTransport(), FakeChannels(), BytesIO(b'a' * 8192), cancel,
            queue_chunks=1,
        )
        with self.assertRaises(CancelledError):
            await runtime.run()

    async def test_blocked_pipe_input_cancels_promptly(self):
        read_fd, write_fd = os.pipe()
        source = os.fdopen(read_fd, 'rb', buffering=0)
        cancel = asyncio.Event()
        runtime = BackendRuntime(
            FakeTransport(), FakeChannels(), source, cancel, queue_chunks=1,
        )
        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.01)
        cancel.set()
        with self.assertRaises(CancelledError):
            await asyncio.wait_for(task, 0.5)
        source.close()
        os.close(write_fd)

    async def test_accepted_notifications_are_forwarded_in_order(self):
        channels = FakeChannels()
        runtime = BackendRuntime(
            FakeTransport(), channels, BytesIO(b''), asyncio.Event(),
        )
        values = [bytes((0x1a, number, 0x00)) for number in range(20)]
        for value in values:
            runtime.notification(value)
        await runtime.run()
        self.assertEqual(channels.back, values)

    async def test_back_channel_failure_fails_job(self):
        channels = FakeChannels(back_error=BrokenPipeError('closed'))
        runtime = BackendRuntime(
            FakeTransport(), channels, BytesIO(b''), asyncio.Event(),
        )
        runtime.notification(b'\x1a\x0f\x0c')
        with self.assertRaises(BrokenPipeError):
            await runtime.run()

    async def test_side_channel_failure_fails_job(self):
        channels = FakeChannels(side_error=OSError('closed'))
        runtime = BackendRuntime(
            FakeTransport(), channels, BytesIO(b''), asyncio.Event(),
        )
        with self.assertRaises(OSError):
            await runtime.run()


if __name__ == '__main__':
    unittest.main()
