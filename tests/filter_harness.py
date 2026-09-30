"""Subprocess harness for CUPS filter back- and side-channel behavior."""
from dataclasses import dataclass
import os
import select
import socket
import subprocess
import time


@dataclass(frozen=True)
class SideMessage:
    command: int
    status: int
    data: bytes


class FilterHarness:
    """Run a filter with CUPS-compatible descriptors 3 and 4.

    The same harness can run the manufacturer filter when its path, normal
    filter arguments, PPD environment, and raster input are supplied.
    """

    def __init__(self, argv, *, stdin=subprocess.PIPE, env=None):
        self.argv = argv
        self.stdin = stdin
        self.env = env
        self.process = None
        self.back = None
        self.side = None
        self._children = ()

    def __enter__(self):
        back_parent, back_child = socket.socketpair()
        side_parent, side_child = socket.socketpair()

        def configure_child():
            os.dup2(back_child.fileno(), 3)
            os.dup2(side_child.fileno(), 4)

        self.process = subprocess.Popen(
            self.argv,
            stdin=self.stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            # Keep target descriptors as well as their sources open across
            # subprocess close-fds processing.
            pass_fds=tuple({3, 4, back_child.fileno(), side_child.fileno()}),
            preexec_fn=configure_child,
        )
        back_child.close()
        side_child.close()
        self.back = back_parent
        self.side = side_parent
        self._children = (back_child, side_child)
        return self

    def __exit__(self, exc_type, exc, traceback):
        for channel in (self.back, self.side):
            if channel is not None:
                channel.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout,
                           self.process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def send_notification(self, data):
        self.back.sendall(data)

    def read_side(self, timeout=1.0):
        self.side.settimeout(timeout)
        header = _recv_exact(self.side, 4)
        length = int.from_bytes(header[2:4], 'big')
        return SideMessage(header[0], header[1], _recv_exact(self.side, length))

    def write_side(self, command, status, data=b''):
        header = bytes((command, status)) + len(data).to_bytes(2, 'big')
        self.side.sendall(header + data)

    def stdout_ready(self, timeout=0.1):
        ready, _, _ = select.select([self.process.stdout.fileno()], [], [], timeout)
        return bool(ready)

    def read_stdout(self, length, timeout=1.0):
        deadline = time.monotonic() + timeout
        result = bytearray()
        while len(result) < length:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select(
                [self.process.stdout.fileno()], [], [], remaining,
            )
            if not ready:
                raise TimeoutError('Filter stdout did not become ready')
            data = os.read(self.process.stdout.fileno(), length - len(result))
            if not data:
                raise EOFError('Filter stdout closed before the expected bytes')
            result.extend(data)
        return bytes(result)


def _recv_exact(channel, length):
    result = bytearray()
    while len(result) < length:
        data = channel.recv(length - len(result))
        if not data:
            raise EOFError('CUPS channel closed before a complete message')
        result.extend(data)
    return bytes(result)
