#!/bin/sh
set -eu

PYTHON=${PYTHON:-python3}
PREFIX=${PREFIX:-/usr/local}
DESTDIR=${DESTDIR:-}

if ! command -v cups-config >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: cups-config is required to locate the CUPS installation.' >&2
    exit 1
fi

CUPS_SERVERBIN=${CUPS_SERVERBIN:-$(cups-config --serverbin)}
PURELIB=$(
    "$PYTHON" - "$PREFIX" <<'PY'
import sys
import sysconfig

prefix = sys.argv[1]
print(sysconfig.get_path('purelib', vars={'base': prefix, 'platbase': prefix}))
PY
)

rm -f "$DESTDIR$CUPS_SERVERBIN/backend/m832dble"
rm -f "$DESTDIR$PREFIX/bin/m832dble-diagnose"
rm -rf "$DESTDIR$PURELIB/m832d_ble"

printf '%s\n' 'Removed the M832D BLE backend files.'
printf '%s\n' 'No CUPS queue, vendor driver, pairing, or BlueZ setting was changed.'
