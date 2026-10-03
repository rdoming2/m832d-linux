"""Bounded job streaming and CUPS channel coordination."""
import asyncio
import errno
import os
import select
import stat

from .channels import SideCommand, SideStatus
from .model import CancelledError


class TransferTracker:
    """Track a host-side drain fence, not printer processing or completion.

    ``produced`` counts bytes removed from filter input; ``acknowledged`` counts
    bytes whose complete transport write returned successfully.  A recorded
    failure wakes drain waiters rather than leaving them blocked.
    """
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

    async def wait_acknowledged(self, barrier, timeout=60.0):
        async def wait():
            async with self.changed:
                await self.changed.wait_for(
                    lambda: self.acknowledged >= barrier or self.failed is not None
                )
                if self.failed is not None:
                    raise self.failed
        await asyncio.wait_for(wait(), timeout)

    async def capture_drain_barrier(self, source=None):
        """Fence bytes already in the filter pipe before replying to drain.

        Filter output and side-channel requests use separate descriptors, so a
        drain request can be observed just before earlier pipe data.  For FIFOs,
        yield until currently readable input has been consumed; other sources use
        a short scheduling/quiescence fence.  The returned produced-byte count is
        not evidence of physical print completion.
        """
        if source is None:
            observed = self.produced
            while not self.finished and self.failed is None:
                try:
                    async with self.changed:
                        await asyncio.wait_for(
                            self.changed.wait_for(lambda: self.produced != observed),
                            0.01,
                        )
                        observed = self.produced
                except TimeoutError:
                    break
            return self.produced
        if source is not None:
            try:
                mode = os.fstat(source.fileno()).st_mode
            except (AttributeError, OSError):
                mode = 0
            if stat.S_ISFIFO(mode):
                while not self.finished and self.failed is None:
                    ready, _, _ = select.select([source.fileno()], [], [], 0)
                    if not ready:
                        break
                    await asyncio.sleep(0)
            else:
                await asyncio.sleep(0)
        return self.produced


class BackendRuntime:
    """Coordinate a bounded, ordered data pipeline with CUPS channels.

    One producer and consumer preserve source order through a bounded data queue.
    FF03 values remain opaque and ordered in a separate bounded queue; overflow
    is fatal rather than silently dropping status bytes.  Side- and back-channel
    pumps run concurrently with transmission.
    """
    def __init__(self, transport, channels, source, cancel_event, queue_chunks=16,
                 drain_timeout=60.0):
        self.transport = transport
        self.channels = channels
        self.source = source
        self.cancel_event = cancel_event
        self.queue = asyncio.Queue(maxsize=queue_chunks)
        self.drain_timeout = drain_timeout
        self.notifications = asyncio.Queue(maxsize=64)
        self.tracker = TransferTracker()
        self.connected = True
        self.transmitting = False
        self._stopping = asyncio.Event()
        self._channel_error = None
        self._channel_failed = asyncio.Event()
        self._side_idle = asyncio.Event()
        self.back_channel_closed = False

    def notification(self, data):
        """Queue one opaque FF03 value without assigning it status meaning."""
        if self._stopping.is_set():
            return
        try:
            self.notifications.put_nowait(data)
        except asyncio.QueueFull:
            self._channel_error = RuntimeError('Notification queue limit exceeded')
            self._channel_failed.set()

    async def run(self):
        """Supervise transfer and channel tasks, then stop all remaining work."""
        producer = asyncio.create_task(self._produce())
        consumer = asyncio.create_task(self._consume())
        notifications = asyncio.create_task(self._notification_pump())
        side_channel = asyncio.create_task(self._side_channel_pump())
        channel_failure = asyncio.create_task(self._channel_failed.wait())
        data_tasks = {producer, consumer}
        channel_tasks = {notifications, side_channel, channel_failure}
        try:
            while data_tasks:
                done, _ = await asyncio.wait(
                    data_tasks | channel_tasks, return_when=asyncio.FIRST_COMPLETED,
                )
                if channel_failure in done:
                    raise self._channel_error or RuntimeError('CUPS channel failed')
                for task in done & {notifications, side_channel}:
                    await task
                    raise RuntimeError('CUPS channel pump stopped unexpectedly')
                for task in done & data_tasks:
                    await task
                    data_tasks.remove(task)

            # These bounded waits are flush opportunities for accepted channel
            # work, not printer-completion waits.
            self._side_idle.clear()
            await asyncio.wait_for(self._side_idle.wait(), 0.2)
            if self._channel_failed.is_set():
                raise self._channel_error or RuntimeError('CUPS channel failed')
            for task in (notifications, side_channel):
                if task.done():
                    await task
                    raise RuntimeError('CUPS channel pump stopped unexpectedly')
            await asyncio.wait_for(self.notifications.join(), 2.0)
        finally:
            self._stopping.set()
            try:
                self.notifications.put_nowait(None)
            except asyncio.QueueFull:
                pass
            tasks = data_tasks | channel_tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _produce(self):
        """Read fixed chunks into the bounded queue and account before enqueue."""
        try:
            while not self.cancel_event.is_set():
                data = await self._read_chunk()
                if not data:
                    break
                await self.tracker.add_produced(len(data))
                await self.queue.put(data)
            if self.cancel_event.is_set():
                raise CancelledError('Job cancelled before all input was submitted')
        finally:
            self.tracker.finished = True
            if asyncio.current_task().cancelling():
                try:
                    self.queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            else:
                await self.queue.put(None)

    async def _read_chunk(self):
        """Read files in a worker, but keep pipe reads cancellable by readiness."""
        try:
            fd = self.source.fileno()
            mode = os.fstat(fd).st_mode
        except (AttributeError, OSError):
            return await asyncio.to_thread(self.source.read, 4096)
        if stat.S_ISREG(mode):
            return await asyncio.to_thread(self.source.read, 4096)

        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        cancelled = asyncio.create_task(self.cancel_event.wait())

        def mark_ready():
            if not ready.done():
                ready.set_result(None)

        loop.add_reader(fd, mark_ready)
        try:
            done, _ = await asyncio.wait(
                {ready, cancelled}, return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done and cancelled.result():
                raise CancelledError('Job cancelled while waiting for input')
            return os.read(fd, 4096)
        finally:
            loop.remove_reader(fd)
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    async def _consume(self):
        """Perform one ordered transport write at a time with no requeue."""
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
        """Forward raw notification values to CUPS fd 3 in callback order."""
        while not self._stopping.is_set():
            data = await self.notifications.get()
            try:
                if data is None:
                    return
                if self.back_channel_closed:
                    continue
                try:
                    await asyncio.to_thread(self.channels.write_back, data)
                except OSError as exc:
                    if (not isinstance(exc, BrokenPipeError)
                            and exc.errno not in (errno.EBADF, errno.EPIPE)):
                        raise
                    # The filter has closed fd 3 and cannot consume further
                    # notifications. Continue sending output it already emitted.
                    self.back_channel_closed = True
            finally:
                self.notifications.task_done()

    async def _side_channel_pump(self):
        while not self._stopping.is_set():
            request = await asyncio.to_thread(self.channels.read_side, 0.05)
            if request is None:
                self._side_idle.set()
                await asyncio.sleep(0)
                continue
            self._side_idle.clear()
            if request.command == SideCommand.DRAIN_OUTPUT:
                # OK fences acknowledged transport writes preceding this request;
                # it neither parses printer state nor confirms physical output.
                barrier = await self.tracker.capture_drain_barrier(self.source)
                try:
                    await self.tracker.wait_acknowledged(barrier, self.drain_timeout)
                    status, data = SideStatus.OK, b''
                except TimeoutError:
                    status, data = SideStatus.TIMEOUT, b''
                except Exception:
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
