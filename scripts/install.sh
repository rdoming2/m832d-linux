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
if ! command -v ppdc >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: ppdc is required to compile cups/drv/m832d.drv.' >&2
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
FILTER_PACKAGE_DIR="$DESTDIR$PURELIB/m832d_filter"
PROTOCOL_PACKAGE_DIR="$DESTDIR$PURELIB/m832d_protocol"
BACKEND_DIR="$DESTDIR$CUPS_SERVERBIN/backend"
FILTER_DIR="$DESTDIR$CUPS_SERVERBIN/filter"
BIN_DIR="$DESTDIR$PREFIX/bin"
MODEL_DIR=${CUPS_DATADIR:-$(cups-config --datadir)}/model

install -d -m 0755 "$PACKAGE_DIR" "$FILTER_PACKAGE_DIR" "$PROTOCOL_PACKAGE_DIR" "$BACKEND_DIR" "$FILTER_DIR" "$BIN_DIR" "$DESTDIR$MODEL_DIR"
for source in "$SOURCE_ROOT"/src/m832d_ble/*.py; do
    install -m 0644 "$source" "$PACKAGE_DIR/$(basename -- "$source")"
done
for package in m832d_filter m832d_protocol; do
    for source in "$SOURCE_ROOT"/src/$package/*.py; do
        install -m 0644 "$source" "$DESTDIR$PURELIB/$package/$(basename -- "$source")"
    done
done
install -m 0755 "$SOURCE_ROOT/scripts/rastertom832d" "$FILTER_DIR/rastertom832d"
PPD_BUILD=$(mktemp -d)
trap 'rm -rf "$PPD_BUILD"' EXIT HUP INT TERM
ppdc -d "$PPD_BUILD" "$SOURCE_ROOT/cups/drv/m832d.drv"
install -m 0644 "$PPD_BUILD/Phomemo-M832D.ppd" "$DESTDIR$MODEL_DIR/Phomemo-M832D.ppd"
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
