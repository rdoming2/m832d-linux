"""Minimal CUPS side-channel support used by the raster filter."""

import ctypes
import ctypes.util
import os


DRAIN_OUTPUT = 2
SIDE_CHANNEL_OK = 1


class CupsSideChannel:
    def __init__(self, fd=4, library=None):
        self.fd = fd
        self.library = library or self._load_library()
        self.library.cupsSideChannelDoRequest.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
            ctypes.c_double,
        ]
        self.library.cupsSideChannelDoRequest.restype = ctypes.c_int

    @staticmethod
    def _load_library():
        name = ctypes.util.find_library("cups")
        if not name:
            raise RuntimeError("libcups is required for page pauses")
        return ctypes.CDLL(name, use_errno=True)

    def drain(self, timeout=65.0):
        try:
            os.fstat(self.fd)
        except OSError as exc:
            raise RuntimeError("CUPS output drain is unavailable") from exc
        capacity = ctypes.c_int(2048)
        buffer = ctypes.create_string_buffer(capacity.value)
        status = self.library.cupsSideChannelDoRequest(
            DRAIN_OUTPUT, buffer, ctypes.byref(capacity), timeout,
        )
        if status != SIDE_CHANNEL_OK:
            raise RuntimeError(f"CUPS output drain failed with status {status}")
