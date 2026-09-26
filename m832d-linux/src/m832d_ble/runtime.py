"""Bounded job streaming and CUPS channel coordination."""
import asyncio

from .channels import SideCommand, SideStatus
from .model import CancelledError


class TransferTracker:
    def __init__(self):
        self.produced = 0
        self.acknowledged = 0
        self.finished = False
        self.failed = None
        self.changed = asyncio.Condition()

    async def add_produced(self, count):
        async with self.changed:
            self.produced += count
            self.changed.notify_all()

    async def add_acknowledged(self, count):
        async with self.changed:
            self.acknowledged += count
            self.changed.notify_all()

    async def wait_acknowledged(self, barrier, timeout=30.0):
        async def wait():
            async with self.changed:
                await self.changed.wait_for(
                    lambda: self.acknowledged >= barrier or self.failed is not None
                )
                if self.failed is not None:
                    raise self.failed
        await asyncio.wait_for(wait(), timeout)

    async def capture_drain_barrier(self, quiet_period=0.01):
        """Include bytes flushed just before a request on the separate fd 4."""
        observed = self.produced
        while not self.finished and self.failed is None:
            try:
                async with self.changed:
                    await asyncio.wait_for(
                        self.changed.wait_for(lambda: self.produced != observed),
                        quiet_period,
                    )
                    observed = self.produced
            except TimeoutError:
                break
        return self.produced


class BackendRuntime:
    def __init__(self, transport, channels, source, cancel_event, queue_chunks=16):
        self.transport = transport
        self.channels = channels
        self.source = source
        self.cancel_event = cancel_event
        self.queue = asyncio.Queue(maxsize=queue_chunks)
        self.notifications = asyncio.Queue(maxsize=64)
        self.tracker = TransferTracker()
        self.connected = True
        self.transmitting = False
        self._stopping = asyncio.Event()

    async def notification(self, data):
        try:
            self.notifications.put_nowait(data)
        except asyncio.QueueFull:
            raise RuntimeError('Notification queue limit exceeded') from None

    async def run(self):
        tasks = [
            asyncio.create_task(self._produce()),
            asyncio.create_task(self._consume()),
            asyncio.create_task(self._notification_pump()),
            asyncio.create_task(self._side_channel_pump()),
        ]
        try:
            await asyncio.gather(tasks[0], tasks[1])
        finally:
            self._stopping.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _produce(self):
        try:
            while not self.cancel_event.is_set():
                data = await asyncio.to_thread(self.source.read, 4096)
                if not data:
                    break
                await self.tracker.add_produced(len(data))
                await self.queue.put(data)
            if self.cancel_event.is_set():
                raise CancelledError('Job cancelled before all input was submitted')
        finally:
            await self.queue.put(None)
            self.tracker.finished = True

    async def _consume(self):
        self.transmitting = True
        try:
            while True:
                data = await self.queue.get()
                if data is None:
                    return
                try:
                    await self.transport.write(data)
                except Exception as exc:
                    self.tracker.failed = exc
                    async with self.tracker.changed:
                        self.tracker.changed.notify_all()
                    raise
                await self.tracker.add_acknowledged(len(data))
        finally:
            self.transmitting = False

    async def _notification_pump(self):
        while not self._stopping.is_set():
            data = await self.notifications.get()
            await asyncio.to_thread(self.channels.write_back, data)

    async def _side_channel_pump(self):
        while not self._stopping.is_set():
            request = await asyncio.to_thread(self.channels.read_side, 0.05)
            if request is None:
                await asyncio.sleep(0)
                continue
            if request.command == SideCommand.DRAIN_OUTPUT:
                barrier = await self.tracker.capture_drain_barrier()
                try:
                    await self.tracker.wait_acknowledged(barrier)
                    status, data = SideStatus.OK, b''
                except (Exception, asyncio.CancelledError):
                    status, data = SideStatus.IO_ERROR, b''
            elif request.command == SideCommand.GET_BIDI:
                status, data = SideStatus.OK, b'\x01'
            elif request.command == SideCommand.GET_CONNECTED:
                status, data = SideStatus.OK, bytes([1 if self.connected else 0])
            elif request.command == SideCommand.GET_STATE:
                state = 2 if self.transmitting else 1
                status, data = SideStatus.OK, bytes([state])
            else:
                status, data = SideStatus.NOT_IMPLEMENTED, b''
            await asyncio.to_thread(
                self.channels.write_side, request.command, status, data,
            )
