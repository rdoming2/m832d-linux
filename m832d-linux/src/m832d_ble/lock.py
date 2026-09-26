"""Non-blocking per-printer process locks."""
import fcntl
import os
from pathlib import Path
import stat
import tempfile


class PrinterLock:
    def __init__(self, key, directory=None):
        configured = directory or os.environ.get('M832D_BLE_LOCK_DIR')
        root = Path(configured) if configured else Path(tempfile.gettempdir()) / f'm832dble-{os.getuid()}'
        self.path = root / f'm832dble-{key}.lock'
        self._file = None

    def __enter__(self):
        self._prepare_directory()
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            os.close(descriptor)
            raise RuntimeError('Printer lock file has unsafe ownership or type')
        self._file = os.fdopen(descriptor, 'r+')
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

    def _prepare_directory(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True)
        except FileExistsError:
            pass
        details = self.path.parent.lstat()
        permissions = stat.S_IMODE(details.st_mode)
        if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid()
                or permissions & 0o077):
            raise RuntimeError('Printer lock directory must be private and owned by the backend user')

    def __exit__(self, exc_type, exc, traceback):
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None
