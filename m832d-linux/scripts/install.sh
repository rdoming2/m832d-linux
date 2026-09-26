#!/bin/sh
set -eu

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
PREFIX=${PREFIX:-/usr/local}
DESTDIR=${DESTDIR:-}
PYTHON_PATH=$(command -v "$PYTHON" || true)

if [ -z "$PYTHON_PATH" ]; then
    printf 'ERROR: Python interpreter not found: %s\n' "$PYTHON" >&2
    exit 1
fi

if ! command -v cups-config >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: cups-config is required to locate the CUPS installation.' >&2
    exit 1
fi

CUPS_SERVERBIN=${CUPS_SERVERBIN:-$(cups-config --serverbin)}
FILTER=${M832D_FILTER:-$CUPS_SERVERBIN/filter/rastertoM08F}
if [ ! -x "$FILTER" ]; then
    printf 'ERROR: manufacturer filter not found at %s\n' "$FILTER" >&2
    printf '%s\n' 'Install the manufacturer M832D driver separately before this backend.' >&2
    exit 1
fi

if [ -n "${M832D_PPD:-}" ]; then
    if [ ! -r "$M832D_PPD" ]; then
        printf 'ERROR: M832D_PPD is not readable: %s\n' "$M832D_PPD" >&2
        exit 1
    fi
elif command -v lpinfo >/dev/null 2>&1 && lpinfo -m 2>/dev/null | grep -qi 'M832D'; then
    :
else
    printf '%s\n' 'ERROR: no installed M832D PPD was reported by CUPS.' >&2
    printf '%s\n' 'Set M832D_PPD to the separately installed PPD path if CUPS cannot list it.' >&2
    exit 1
fi

if ! "$PYTHON" -c 'import bleak, dbus_fast' >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: the selected Python needs bleak and dbus-fast.' >&2
    exit 1
fi
if ! "$PYTHON" -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("cups") else 1)' >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: libcups is required.' >&2
    exit 1
fi

PURELIB=${PYTHON_LIB:-$(
    "$PYTHON_PATH" - <<'PY'
import sysconfig

print(sysconfig.get_path('purelib'))
PY
)}
PACKAGE_DIR="$DESTDIR$PURELIB/m832d_ble"
BACKEND_DIR="$DESTDIR$CUPS_SERVERBIN/backend"
BIN_DIR="$DESTDIR$PREFIX/bin"

install -d -m 0755 "$PACKAGE_DIR" "$BACKEND_DIR" "$BIN_DIR"
for source in "$SOURCE_ROOT"/src/m832d_ble/*.py; do
    install -m 0644 "$source" "$PACKAGE_DIR/$(basename -- "$source")"
done
{
    printf '%s\n' '#!/bin/sh'
    printf 'exec "%s" -m m832d_ble.backend "$@"\n' "$PYTHON_PATH"
} > "$BACKEND_DIR/m832dble"
{
    printf '%s\n' '#!/bin/sh'
    printf 'exec "%s" -m m832d_ble.diagnose "$@"\n' "$PYTHON_PATH"
} > "$BIN_DIR/m832dble-diagnose"
chmod 0755 "$BACKEND_DIR/m832dble" "$BIN_DIR/m832dble-diagnose"

printf 'Installed backend: %s\n' "$BACKEND_DIR/m832dble"
printf 'Installed diagnostic: %s\n' "$BIN_DIR/m832dble-diagnose"
printf 'Installed Python package: %s\n' "$PACKAGE_DIR"
printf 'CUPS version: %s\n' "$(cups-config --version)"
"$PYTHON_PATH" - <<'PY'
from importlib.metadata import version
import platform

print(f'Python version: {platform.python_version()}')
print(f'Bleak version: {version("bleak")}')
print(f'dbus-fast version: {version("dbus-fast")}')
PY
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl --version || true
fi
printf '%s\n' 'CUPS was not restarted and no queue or Bluetooth setting was changed.'
printf '%s\n' 'Continue with docs/OPERATIONS.md.'
