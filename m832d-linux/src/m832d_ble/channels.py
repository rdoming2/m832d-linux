"""Typed libcups bindings for backend back- and side-channel I/O."""
from dataclasses import dataclass
from enum import IntEnum
import ctypes
import ctypes.util
import os


class SideCommand(IntEnum):
    NONE = 0
    SOFT_RESET = 1
    DRAIN_OUTPUT = 2
    GET_BIDI = 3
    GET_DEVICE_ID = 4
    GET_STATE = 5
    SNMP_GET = 6
    SNMP_GET_NEXT = 7
    GET_CONNECTED = 8


class SideStatus(IntEnum):
    NONE = 0
    OK = 1
    IO_ERROR = 2
    TIMEOUT = 3
    NO_RESPONSE = 4
    BAD_MESSAGE = 5
    TOO_BIG = 6
    NOT_IMPLEMENTED = 7


@dataclass(frozen=True)
class SideRequest:
    command: SideCommand
    data: bytes


class CupsChannels:
    def __init__(self, library=None, back_fd=3, side_fd=4):
        self.back_fd = back_fd
        self.side_fd = side_fd
        self._lib = library or self._load_library()
        self._configure()

    @staticmethod
    def _load_library():
        name = ctypes.util.find_library('cups')
        if not name:
            raise RuntimeError('libcups is required for CUPS channel support')
        return ctypes.CDLL(name, use_errno=True)

    def _configure(self):
        self._lib.cupsBackChannelWrite.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_double]
        self._lib.cupsBackChannelWrite.restype = ctypes.c_ssize_t
        self._lib.cupsSideChannelRead.argtypes = [
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int), ctypes.c_double,
        ]
        self._lib.cupsSideChannelRead.restype = ctypes.c_int
        self._lib.cupsSideChannelWrite.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_double,
        ]
        self._lib.cupsSideChannelWrite.restype = ctypes.c_int

    def has_back_channel(self):
        return _fd_open(self.back_fd)

    def has_side_channel(self):
        return _fd_open(self.side_fd)

    def write_back(self, data, timeout=1.0):
        if not data or not self.has_back_channel():
            return
        buffer = ctypes.create_string_buffer(data)
        written = self._lib.cupsBackChannelWrite(buffer, len(data), timeout)
        if written != len(data):
            errno = ctypes.get_errno()
            raise OSError(errno, f'CUPS back-channel wrote {written}/{len(data)} bytes')

    def read_side(self, timeout=0.1):
        if not self.has_side_channel():
            return None
        command = ctypes.c_int()
        status = ctypes.c_int()
        capacity = ctypes.c_int(2048)
        buffer = ctypes.create_string_buffer(capacity.value)
        result = self._lib.cupsSideChannelRead(
            ctypes.byref(command), ctypes.byref(status), buffer,
            ctypes.byref(capacity), timeout,
        )
        if result != 0:
            return None
        try:
            parsed = SideCommand(command.value)
        except ValueError:
            parsed = SideCommand.NONE
        return SideRequest(parsed, buffer.raw[:capacity.value])

    def write_side(self, command, status, data=b'', timeout=1.0):
        if not self.has_side_channel():
            return
        buffer = ctypes.create_string_buffer(data) if data else None
        result = self._lib.cupsSideChannelWrite(
            int(command), int(status), buffer, len(data), timeout,
        )
        if result != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, 'Unable to write CUPS side-channel response')


def _fd_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True
