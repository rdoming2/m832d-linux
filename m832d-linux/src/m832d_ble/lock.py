"""Non-blocking per-printer process locks."""
import fcntl
import os
from pathlib import Path


class PrinterLock:
    def __init__(self, key, directory=None):
        root = Path(directory or os.environ.get('M832D_BLE_LOCK_DIR', '/tmp'))
        self.path = root / f'm832dble-{key}.lock'
        self._file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open('a+')
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            self._file = None
            raise RuntimeError('Printer is already in use by another backend process') from None
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f'{os.getpid()}\n')
        self._file.flush()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None
