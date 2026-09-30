# Phomemo M832D Linux printing

This project provides a functional, maturing Linux CUPS printing path for the
Phomemo M832D:

- The project-owned generated PPD and `rastertom832d` filter convert ordinary
  CUPS jobs into the printer's uncompressed M832 raster stream.
- The `m832dble` backend transports that filter output byte-for-byte over BLE;
  the standard CUPS USB backend can use the same driver and filter.

The CUPS implementation is functional and continues to mature.
Successful physical printing has been tested over both USB and BLE with the
53 mm and 110 mm named media and with a custom 2.25 in (57.15 mm) print width.
These results cover the tested setup and configurations; they do not establish
all firmware, media lengths, margins, failure conditions, or physical-completion
semantics. The separate `m832d.py` sender and the protocol-investigation tools
under [`research/`](research/README.md) remain historical, unsupported research
utilities rather than the primary print path.

## Repository layout

- `src/` contains the maintained CUPS backend, filter, and protocol packages.
- `scripts/` contains supported installation and CUPS entry-point wrappers.
- `tests/` contains deterministic offline tests for the maintained implementation.
- `research/` contains unsupported protocol-investigation utilities and their
  capture-derived encoder fixtures. See [`research/README.md`](research/README.md)
  before using them.
- `research/artifacts/local/` is for ignored captures, logs, images, and vendor
  material. It is not part of the distributable project.

The generated PPD's `w53h70` choice (approximately 53 × 70 mm) remains the
conservative default. The `w110h146` choice (approximately 110 × 146 mm) and a
custom 2.25 in (57.15 mm) width have also been physically tested over USB and
BLE. The generated PPD declares named labels and custom media full-page
imageable, while retaining hardware margins for A4 and Letter. A4, Letter,
other media lengths, maximum physical printable width, edge behavior, feed
calibration, fault recovery, and physical-completion detection remain outside
the validated scope.

## Safety and outcome semantics

Hardware tests must be deliberate. Installation and offline tests do not
contact the printer. A submitted BLE print job may create a bond automatically
before sending print data; installation does not. Preserve existing manufacturer
drivers and USB queues, and do not implicitly change BlueZ preferences, D-Bus
policy, CUPS queues, or system services.

Never automatically retry after print data may have reached the printer. A
failure after submission can represent an uncertain partial print; replaying it
could produce a duplicate. Cancellation prevents additional writes but cannot
recall bytes already accepted by the printer.

An ATT acknowledgement confirms BLE transport acceptance only. A CUPS drain
confirms that preceding bytes completed acknowledged writes only. Neither those
events, a successful backend exit, nor an elapsed delay proves physical output
or physical print completion. Observed notification meanings remain
provisional.

## Historical standalone sender and research tools

The maintained print path is the CUPS driver, filter, and backend described
below. The standalone sender is retained for protocol research and controlled
experiments; see [`research/README.md`](research/README.md) for the research
utilities and artifact-handling guidance.

### Standalone sender prerequisites

The standalone encoder requires Python, Pillow, and the system `liblzo2`
library. BLE sending additionally requires Bleak, dbus-fast, BlueZ, and an
account authorized to access BlueZ. Install equivalent packages for the target
distribution.

Run commands from this source directory. Before an approved BLE transfer,
ensure that the selected printer is available and disconnect competing clients
such as the phone application.

### Standalone image use

Create a job and inspect its binary-raster preview without connecting to a
printer:

```sh
python m832d.py encode image.png image.bin --preview preview.png
```

Replay a prepared job or encode and send an image by specifying the printer's
Bluetooth address explicitly:

```sh
python m832d.py replay image.bin --address AA:BB:CC:DD:EE:FF
python m832d.py print image.png --address AA:BB:CC:DD:EE:FF
```

Each sending command attempts one transfer.

The sender accepts PNG, JPEG, and other Pillow-readable image formats. Images
wider than the selected canvas are reduced proportionally; narrower images are
centered without enlargement. Transparency is composited onto white. The
default threshold is 160, and `--threshold 128`, for example, selects a
different cutoff. No dithering is applied. The preview displays the resulting
binary raster. PDF rendering is not included in the standalone encoder; render
the page to an image first. CUPS may perform its own document-to-raster
conversion before invoking the project filter.

The included capture-derived fixtures use a 576-pixel raster width. `--width` 
permits other multiples of eight for experiments, but physical dimensions and 
long-job behavior require separate validation.

### Standalone BLE transport

- FF02 and FF03 are resolved by UUID rather than copied numeric handles.
- The default mode uses acknowledged writes, a maximum chunk size of 182 bytes,
  and no artificial inter-write delay.
- `--delay-ms 40` introduces a delay, `--chunk-size 20` requests smaller
  writes, and `--write-mode command` selects unacknowledged writes for
  experiments. These options are not substitutes for printer flow control.
- `--wait 30` keeps the connection open after upload. Waiting and received
  notifications do not confirm printing.
- Raster bytes are LZO1X-compressed in 4096-byte blocks, each prefixed by a 
  three-byte little-endian compressed length. The footer contains two `ESC d 2` 
  commands.

The tested dual-mode printer requires explicit LE bearer selection. The CUPS
backend requests an LE connection when BlueZ supports `ConnectDevice`. A fresh
automatic pairing connection is on the selected LE discovery path and
is reused; if it closes, BlueZ reconnects the sole new LE bond. Existing devices
with a random address are also LE-only and can use `Device1.Connect`. An existing
public-address device instead requires `ConnectDevice` or an
available `PreferredBearer` property. The print pipeline sets and verifies that
property as `le` before pairing or connecting.

## CUPS backend and filter

Backend device URIs contain an explicit Bluetooth address. Specify the adapter
as well when multiple adapters are available or reproducibility is required:

```text
m832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0
```

The backend scans on the LE transport and matches the configured address. It
uses acknowledged FF02 writes, FF03 notifications, bounded channels and waits,
per-printer locking, and conservative retry/stop outcomes. If no LE bond exists,
a print job makes one bounded Just Works pairing attempt for the exact configured
device before transmitting data. The service identity needs permission to set
the exact device's bearer preference, pair it, and mark the verified bond as
trusted.

The temporary pairing agent is not made the BlueZ default and rejects callbacks
for every other device. After verifying the LE bond, the backend sets
`Trusted=true` only for the exact configured printer. It does not alter adapter
settings or delete stale bonds. Just Works has no human confirmation and no
meaningful MITM protection. Verify the complete printer address and adapter
before creating the queue. Pairing rejection, PIN/passkey requirements, stale
keys, or insufficient service permissions hold the job with zero submitted
bytes instead of looping.

Pairing, trust, and the selected LE bearer are persistent setup; the active BLE
connection is not. Each job holds the per-printer lock through notification
shutdown and verified disconnect. If the printer is already connected and no
advertisement is available, the backend recovers the exact configured device
from BlueZ and adopts that LE connection. If disconnect cannot be confirmed,
the backend reports cleanup failure; after any submitted bytes it stops the
queue rather than replaying the job automatically.

`m832dble-diagnose` performs a non-printing check of scanning, connection,
bond/access state, FF02/FF03 capabilities, and notification subscription. It
does not pair, send status queries, or send raster data; an unpaired printer is
reported as requiring setup.

Use a separately named BLE queue with `PageSize=w53h70` and
`printer-error-policy=stop-printer`. Do not replace or modify an existing USB
or manufacturer queue. Deployment is an explicit administrator action; follow
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) and
[`docs/USB-OPERATIONS.md`](docs/USB-OPERATIONS.md).

The installer does not create queues, pair the printer, set BlueZ preferences,
change D-Bus policy, restart CUPS, or install Python dependencies.

The driver also provides `M832DPagePause`, with choices `Off`, `5`, `10`, `20`,
or `30` seconds. It is disabled by default and can be selected per job, for
example `lp -d M832D-BLE -o M832DPagePause=10 document.pdf`. For a multi-page
job the filter ends each page with the captured footer, waits for a bounded
backend output drain, and then pauses before sending the next page. It does not
add the normal inter-page feed as well, avoiding additional paper length on
paused pages. The same option is available on the separate USB queue. The drain
fences host-side transport only, and the elapsed pause does not confirm physical
print completion.

On USB this uses the standard CUPS backend's `DRAIN_OUTPUT` side-channel
operation; support has been checked against the Linux/libusb backend in CUPS
2.4.19. Existing queues retain their installed PPD copy, so verify that the
separate project USB queue lists `M832DPagePause` before relying on it. USB also
adds a bounded page-height settling allowance, based on a conservative 8 mm/s
at 300 dpi, before the selected tear-off interval because transport drain can
precede the end of physical printing. This remains timing policy, not physical
completion detection. USB status traffic still needs investigation to determine
whether a validated page-complete signal can replace the feed-rate estimate.

## Install the CUPS components

### Build the generated PPD

`ppdc` compiles the project-owned driver source into a PPD:

```sh
make ppd
```

The default output is `build/ppd/Phomemo-M832D.ppd`. Override the build
directory with `PPD_BUILD`, if needed:

```sh
make PPD_BUILD=/tmp/m832d-ppd ppd
```

Remove the generated PPD build directory with:

```sh
make clean
```

Use the same `PPD_BUILD` override with `make clean` when a custom output
directory was selected.

### Install

The installer requires:

- Python 3.10 or newer, with Bleak and dbus-fast available to the selected
  interpreter;
- `cups-config` and `ppdc`;
- the system `libcups` library; and
- permission to write to the selected Python, CUPS, and prefix directories.

After reviewing the script, install from this source directory:

```sh
sudo make install
```

`make install` runs `scripts/install.sh`, which compiles a fresh PPD before
installing it. The script can also be invoked directly with
`sudo ./scripts/install.sh`.

The script installs:

- the `m832d_ble`, `m832d_filter`, and `m832d_protocol` Python packages into
  the selected interpreter's `purelib` directory;
- the `m832dble` CUPS backend into CUPS's backend directory;
- the `rastertom832d` CUPS filter into CUPS's filter directory;
- a generated `Phomemo-M832D.ppd` into CUPS's model directory; and
- `m832dble-diagnose` under the selected prefix, `/usr/local` by default.

`PYTHON`, `PYTHON_LIB`, `CUPS_SERVERBIN`, `CUPS_DATADIR`, `PREFIX`, and
`DESTDIR` can override detected installation paths. Pass overrides to `make`,
for example `sudo make PYTHON=/usr/bin/python3 PREFIX=/usr/local install`. The
selected Python must have the runtime dependencies installed before the script
is run. The installer reports the installed paths and versions but does not
restart CUPS or create a printer queue.

Continue with the pairing, diagnostic, and separate queue procedure in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Uninstall the CUPS components

Stop submitting jobs to the dedicated BLE queue and inspect it for pending or
uncertain jobs. Then remove the project-installed files from this source
directory:

```sh
sudo make uninstall
```

`make uninstall` runs `scripts/uninstall.sh`; the script can also be invoked
directly with `sudo ./scripts/uninstall.sh`.

If installation used path overrides, supply the same `PYTHON`, `PYTHON_LIB`,
`CUPS_SERVERBIN`, `CUPS_DATADIR`, `PREFIX`, and `DESTDIR` values when
uninstalling. The script removes the backend, filter, generated PPD, diagnostic,
and the three installed Python packages.

The uninstaller deliberately leaves all CUPS queues, manufacturer drivers,
Bluetooth pairing, and BlueZ settings untouched. If the dedicated BLE queue is
no longer needed, remove it separately after confirming the queue name:

```sh
sudo lpadmin -x M832D-BLE
```

Do not remove or rename an existing USB or manufacturer queue.

## Set up a CUPS printer

Install the project components before creating a queue. Identify the generated
PPD's CUPS model name with:

```sh
lpinfo -m
```

Find the `Phomemo-M832D.ppd` entry and use its first field as the value passed
to `lpadmin -m`. The examples below use `Phomemo-M832D.ppd`; use the exact model
name reported by the local CUPS installation if it differs.

Queue creation is a hardware deployment action. Use separately named test
queues, preserve existing manufacturer queues, and do not submit a job merely
to verify queue creation.

### USB queue

Connect and power on the intended printer, then ask the standard CUPS backends
to report available device URIs:

```sh
lpinfo -v
```

Locate the entry for the intended M832D and copy its complete `usb://` URI. A
typical entry resembles this, but the manufacturer, model, escaping, and query
parameters vary by device:

```text
direct usb://Phomemo/M832D?serial=DEVICE_SERIAL
```

Do not construct a USB URI from the example or remove its serial/query values;
use the exact URI reported for the intended physical printer. Create a separate
USB queue with that URI:

```sh
sudo lpadmin -p M832D-USB -E \
  -v 'usb://Phomemo/M832D?serial=DEVICE_SERIAL' \
  -m 'Phomemo-M832D.ppd' \
  -o PageSize=w53h70 \
  -o printer-error-policy=stop-printer
```

Replace both placeholders with the discovered URI and model name. Confirm the
result without printing:

```sh
lpstat -v M832D-USB
lpoptions -p M832D-USB -l
```

See [`docs/USB-OPERATIONS.md`](docs/USB-OPERATIONS.md) before an approved USB
hardware test.

### BLE queue

After the backend is installed, BLE discovery through CUPS reports candidate
device URIs. Discovery does not pair the printer:

```sh
lpinfo -v
```

The backend reports an explicit address in a URI resembling:

```text
direct m832dble://AA-BB-CC-DD-EE-FF/
```

Verify that the address belongs to the intended physical printer; do not select
it by advertised name alone. The first print will silently accept Just Works
pairing for that exact address if it is not already bonded. Identify the BlueZ
adapter interface that CUPS must use. Adapter interfaces are normally named
`hci0`, `hci1`, and so on, and can be listed without changing configuration:

```sh
ls -1 /sys/class/bluetooth
bluetoothctl list
```

If multiple controllers are present, use the local BlueZ tooling to match the
chosen controller address to its `hci` interface rather than assuming `hci0`.
Build the final URI by retaining the hyphen-separated printer address and
adding the verified adapter after the slash:

```text
m832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0
```

Use the non-printing diagnostic to verify an existing bond and service access.
It deliberately does not create a missing bond:

```sh
m832dble-diagnose 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0'
```

Then create a separately named BLE queue:

```sh
sudo lpadmin -p M832D-BLE -E \
  -v 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0' \
  -m 'Phomemo-M832D.ppd' \
  -o PageSize=w53h70 \
  -o printer-error-policy=stop-printer
```

Confirm the configured URI and options without submitting a job:

```sh
lpstat -v M832D-BLE
lpoptions -p M832D-BLE -l
```

Follow [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for pairing, service-identity
diagnosis, explicit-LE requirements, testing, and recovery.

## Offline validation

Run the complete offline suite from this directory:

```sh
python -m unittest discover -v
```

The Makefile provides a source-tree check that builds the generated PPD first
and therefore requires `ppdc`:

```sh
make check
```

Run only the legacy standalone encoder suite with:

```sh
python -m unittest discover -p test_encoder.py -v
```

The tests cover capture-derived encoding fixtures, LZO round trips, raster
equivalence, transparency and pixel polarity, malformed framing, PPD/filter
generation, URI parsing, explicit-LE policy, chunk ordering, cancellation,
retry outcomes, locking, CUPS channels, and byte-preserving streaming. Exact
compressed bytes can vary between valid `liblzo2` implementations, and some
tests depend on optional CUPS tools or system libraries.

## Known limitations

- The broader USB and BLE CUPS hardware acceptance matrix remains incomplete
  despite successful tests at 53 mm, 110 mm, and custom 57.15 mm width.
- Maximum physical printable width, edge-to-edge output, arbitrary custom media
  heights, and A4/Letter behavior remain unvalidated.
- Physical completion and detailed printer status semantics are not
  established.
- Media tracking, reconnect behavior, fault injection, long jobs, multi-page
  jobs, and broad firmware compatibility require further hardware validation.
- Existing public-address devices require BlueZ `ConnectDevice` support or an
  available `PreferredBearer` property that the backend can set to `le`. Fresh
  automatic pairing and random-address LE devices do not require those APIs.
- Classic PPD/filter workflows are deprecated in newer CUPS releases.
- Backend queues are bounded, but the current raster filter constructs the
  converted output in memory.
- Competing Bluetooth clients can prevent or interrupt a connection.
- A competing client or an unconfirmed post-job disconnect requires operator
  inspection before releasing or resubmitting a job; forgetting the device is
  not part of normal repeated printing.

## Licensing and third-party material

This project is distributed under GPLv3; see [`LICENSE`](LICENSE). Attribution
is recorded in [`NOTICE`](NOTICE).
