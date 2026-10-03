"""Strict parsing for M832D BLE device URIs."""
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit
import re


ADDRESS_RE = re.compile(r'^[0-9A-Fa-f]{2}(?:(?::|-)[0-9A-Fa-f]{2}){5}$')
ADAPTER_RE = re.compile(r'^hci[0-9]+$')


@dataclass(frozen=True)
class DeviceConfig:
    """Validated transport bounds for one explicitly addressed printer.

    The 182-byte default is the tested acknowledged-write ceiling, not a claim
    about every negotiated MTU.  These values bound scanning, Bleak setup,
    pairing, and individual writes rather than the complete job lifecycle;
    lower-level BlueZ calls have their own bounds.
    """
    address: str
    adapter: str | None = None
    chunk_size: int = 182
    scan_timeout: float = 20.0
    connect_timeout: float = 25.0
    write_timeout: float = 15.0

    @property
    def lock_key(self):
        """Serialize all adapter-qualified URIs for the same printer address."""
        return self.address.replace(':', '').lower()


def parse_device_uri(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != 'm832dble' or not parsed.netloc or parsed.path not in ('', '/'):
        raise ValueError('Expected m832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0')
    if parsed.username or parsed.password or parsed.port:
        raise ValueError('Credentials and ports are not valid in an M832D BLE URI')
    if not ADDRESS_RE.fullmatch(parsed.hostname or ''):
        raise ValueError('Device URI must contain an explicit Bluetooth address')
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    unknown = set(query) - {'adapter', 'chunk_size'}
    if unknown:
        raise ValueError(f'Unknown device URI option: {sorted(unknown)[0]}')
    adapter = _single(query, 'adapter')
    if adapter is not None and not ADAPTER_RE.fullmatch(adapter):
        raise ValueError('Adapter must be named hci followed by digits')
    chunk_text = _single(query, 'chunk_size')
    chunk_size = 182 if chunk_text is None else int(chunk_text)
    if not 1 <= chunk_size <= 182:
        raise ValueError('chunk_size must be in 1..182')
    address = (parsed.hostname or '').replace('-', ':').upper()
    return DeviceConfig(address=address, adapter=adapter, chunk_size=chunk_size)


def _single(query, name):
    values = query.get(name)
    if values is None:
        return None
    if len(values) != 1 or not values[0]:
        raise ValueError(f'{name} must appear exactly once with a value')
    return values[0]


def format_device_uri(address, adapter=None):
    if not ADDRESS_RE.fullmatch(address):
        raise ValueError('Invalid Bluetooth address')
    authority = address.replace(':', '-').upper()
    suffix = f'?adapter={adapter}' if adapter else ''
    return f'm832dble://{authority}/{suffix}'
