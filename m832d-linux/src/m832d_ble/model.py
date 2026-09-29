"""Shared backend state and CUPS result definitions."""
from dataclasses import dataclass
from enum import Enum, IntEnum


class BackendExit(IntEnum):
    OK = 0
    FAILED = 1
    AUTH_REQUIRED = 2
    HOLD = 3
    STOP = 4
    CANCEL = 5
    RETRY = 6
    RETRY_CURRENT = 7


class JobState(Enum):
    WAITING = 'waiting-for-printer'
    CONNECTING = 'connecting-to-device'
    AUTH_REQUIRED = 'authentication-required'
    READY = 'ready'
    TRANSMITTING = 'transmitting'
    DELIVERED = 'transport-delivered'
    UNCERTAIN = 'uncertain-partial-print'
    CANCELLED = 'cancelled'


@dataclass(frozen=True)
class JobInvocation:
    job_id: str
    user: str
    title: str
    copies: int
    options: str
    filename: str | None


class SetupRequiredError(RuntimeError):
    """The selected device needs setup before printing can continue."""


class PairingRequiredError(SetupRequiredError):
    """The selected device is not paired on its LE bearer."""


class PairingFailedError(SetupRequiredError):
    """Automatic pairing could not establish a verified LE bond."""


class CancelledError(RuntimeError):
    """The scheduler or user cancelled the job."""


class TransportCleanupError(RuntimeError):
    """The BLE transport could not confirm that its connection was closed."""
