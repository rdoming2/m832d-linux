# M832D BLE backend operations

This project installs a GPLv3 `rastertom832d` filter and generated M832D PPD.
The BLE backend carries that filter output unchanged. Keep the existing
manufacturer USB queue until USB and BLE acceptance testing are complete.

## Supported baseline

Initial development used CUPS 2.4.19, BlueZ 5.87, Python 3.14, Bleak 3.0.2,
and dbus-fast 5.0.22. The transport also supports the older Bleak API shipped
by Raspbian Trixie, including recovery of an already-connected device between
jobs. Other combinations remain subject to validation. The backend prefers
BlueZ `ConnectDevice`, but it can reuse a fresh LE pairing connection or connect
an existing random-address LE device without experimental BlueZ APIs. An
existing public-address device still requires `ConnectDevice` or a verified
`PreferredBearer=le` setting so Classic cannot be selected silently. The print
pipeline provisions and verifies that device property when it is available.

The backend does not use `bluetoothctl`, so `bluetoothctl --experimental` is
not required. Some BlueZ daemon experimental APIs (`ConnectDevice` and
`PreferredBearer`) may still be needed for an existing public-address dual-mode
device; random-address LE devices can use the explicit LE fallbacks when those
APIs are unavailable.

## Install

Install Bleak and dbus-fast for the system Python used by CUPS. The installer
compiles and installs the project filter and PPD; it does not remove the
manufacturer driver or USB queue. From this source tree, review and then run:

```sh
sudo ./scripts/install.sh
```

`PREFIX`, `DESTDIR`, `PYTHON`, `PYTHON_LIB`, and `CUPS_SERVERBIN` can override
detected installation paths. The backend package is installed into the selected
interpreter's default `purelib` directory; `PREFIX` controls the diagnostic
command location. `DESTDIR` applies only to files installed by this project.
The installer does not restart CUPS, create queues, pair devices, or change
D-Bus policy. Pairing can occur only when an actual BLE print job is submitted.

## Pairing and diagnosis

Record and independently verify the selected printer's complete Bluetooth
address and the adapter to use. Do not configure a queue by advertised name
alone. If the printer has no LE bond, the first print job registers a temporary,
non-default `NoInputNoOutput` agent and makes one bounded Just Works pairing
attempt before sending print bytes. Just Works supplies no human confirmation
and no meaningful MITM protection.

Before creating a queue, run the non-printing diagnostic as the same service
identity that will execute CUPS backends:

```sh
m832dble-diagnose 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0'
```

The diagnostic performs a bounded LE scan and connection, resolves FF02/FF03,
and subscribes to notifications. It does not pair, send status queries, or send
raster data. An unpaired printer therefore reports setup required. It does not
set `PreferredBearer` or `Trusted`. The print pipeline does: for a public-address
device it sets and verifies `PreferredBearer=le` before pairing or connecting,
then sets `Trusted=true` after verifying the LE bond. Random-address LE devices
do not need a bearer preference. Failure under the CUPS identity, despite
success as a desktop user, indicates a bond, BlueZ API, or system-bus permission
problem. Determine the minimum local permission change required before modifying
policy; automatic setup requires permission to write those exact-device
properties, register an agent, and call `Device1.Pair`. This package does not
install a permissive D-Bus rule.

The backend never makes its agent the BlueZ default, changes adapter
pairability/discoverability, or removes a bond. It changes only the configured
device's `PreferredBearer` and `Trusted` properties described above. Pairing
rejection, PIN/passkey requests, timeouts, stale keys, and permission failures
hold the job with zero submitted bytes. Recover a stale bond by explicitly
removing it with normal administrator BlueZ tooling, re-verifying the address,
and releasing or resubmitting the held job; bond removal is never automatic.

## Create the separate queue

Queue creation is an administrator deployment action. After installing the
backend, list CUPS device records:

Graphical CUPS setup tools that use backend discovery can list an advertising
M832D automatically, making basic single-adapter setup simple without manually
constructing its URI. Still verify the printer address, and select the adapter
explicitly when multiple adapters are available. The equivalent command-line
discovery is:

```sh
lpinfo -v
```

The BLE backend reports candidates in this form:

```text
direct m832dble://AA-BB-CC-DD-EE-FF/
```

Verify that the address belongs to the intended physical printer; do not select
a printer by advertised name alone. Identify the BlueZ adapter interface that
the CUPS service must use. List adapter interfaces and controllers without
changing their configuration:

```sh
ls -1 /sys/class/bluetooth
bluetoothctl list
```

Adapter interfaces are normally named `hci0`, `hci1`, and so on. If multiple
controllers are present, match the chosen controller address to its interface
instead of assuming `hci0`. Add the verified interface to the discovered URI
after the slash:

```text
m832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0
```

Find the installed generated PPD's CUPS model identifier with `lpinfo -m` and
use the first field of its `Phomemo-M832D.ppd` entry. The following example
assumes that identifier is `Phomemo-M832D.ppd`:

```sh
sudo lpadmin -p M832D-BLE -E \
  -v 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0' \
  -m 'Phomemo-M832D.ppd' \
  -o PageSize=w53h70 \
  -o printer-error-policy=stop-printer
```

Use the exact model identifier reported by the local CUPS installation. Confirm
the resulting queue does not replace or rename the USB queue. The
`stop-printer` policy is intentional: a backend failure after submission is
uncertain and must not silently replay a whole job. Verify the queue without
printing:

```sh
lpstat -v M832D-BLE
lpoptions -p M832D-BLE -l
```

The generated PPD defaults to `w53h70` (approximately 53 × 70 mm). Physical
printing has also been successfully tested over both USB and BLE with
`w110h146` (approximately 110 × 146 mm) and with a custom 2.25 in (57.15 mm)
width. Select `w53h70` explicitly when an application supplies its own media
setting. For a controlled default-size test:

```sh
lp -d M832D-BLE -o PageSize=w53h70 -o fit-to-page document.pdf
```

An A4 job produces roughly a megabyte of uncompressed raster and commands a
much longer feed than the capture-validated 53 mm workflow. A4 is not currently
a BLE release target. For custom media, the filter does not append an additional
page feed after the final raster; its configured feed is used only between
pages.

For manual tear-off, select `M832DPagePause=5`, `10`, `20`, or `30` seconds;
`0`/`Off` is the default. The pause applies only between pages and is available
on both the BLE and separately named USB queues. For a paused job, the filter
ends each page with the captured footer instead of adding the normal
inter-page feed as well, then waits for a bounded output drain before starting
the timer. The drain fences host-side transport only; it and the elapsed pause
do not confirm that the page has physically finished printing.

For grayscale documents, the filter defaults to Atkinson halftoning. Select
`M832DRendering=FloydSteinberg` for Floyd–Steinberg diffusion, or select
`M832DRendering=Threshold` to use the legacy binary cutoff. Atkinson and
Floyd–Steinberg use a fixed midpoint of 128; threshold mode uses
`M832DThreshold`, which defaults to 160. These options affect raster rendering
only and do not alter transport or printer completion semantics.

The generated PPD declares custom media, including a 2.25-inch-wide page, full
page imageable. A4 and Letter retain their declared hardware margins. The
2.25-inch width has been physically tested over USB and BLE, but this is not
confirmation of full edge-to-edge output, arbitrary custom heights, maximum
printable width, or custom-media feed behavior.

## Outcome and recovery

- An ATT write response confirms transport acceptance only.
- A side-channel drain confirms prior host output completed acknowledged BLE
  writes only.
- Backend success does not prove that paper was physically printed.
- A failure before the first write is safe for a later retry.
- A pairing failure holds the job rather than repeatedly accepting pairing;
  correct the bond or service permission problem before explicitly releasing it.
- A disconnect or write error after submission stops the queue and reports an
  uncertain partial print. Inspect the paper and logs before explicitly
  releasing or resubmitting the job.
- The backend keeps the printer lock until its job-owned connection has been
  disconnected and BlueZ reports it closed. If the printer is already
  connected but not advertising, the backend recovers the exact configured
  device from BlueZ and adopts that LE connection. Other clients may still
  interrupt the connection.
- Pairing, trust, and `PreferredBearer=le` remain persistent; forgetting and
  re-trusting the printer between ordinary jobs is not expected. If teardown
  cannot be confirmed, inspect competing clients and the BlueZ connection
  before explicitly releasing the job. Do not replay a job after submission
  merely because cleanup failed.
- Cancellation stops new writes, but bytes already accepted may still print.

Backend messages are sent to CUPS on stderr. They include the job identifier,
stage, and submitted/acknowledged byte counts without logging document bytes.
Full notification logging is intentionally absent.

## Upgrade and removal

Stop submitting BLE jobs and inspect the queue before upgrading. Re-run the
installer from the reviewed release; it replaces only backend package files.

To remove the files:

```sh
sudo ./scripts/uninstall.sh
```

The script deliberately leaves queues, pairing, BlueZ configuration, the
manufacturer driver, and the USB queue untouched. Remove only the dedicated BLE
queue separately if desired:

```sh
sudo lpadmin -x M832D-BLE
```

## Known limitations

- The project filter emits uncompressed raster and currently uses only the
  confirmed command family; vendor status semantics still require hardware
  validation.
- Maximum printable width, edge behavior, media tracking, feed calibration, and
  physical completion semantics require additional controlled hardware
  validation. Selected 53 mm, 110 mm, and 57.15 mm-width configurations have
  already been tested over USB and BLE.
- Physical completion semantics for observed notifications are not established.
- Automatic first-print pairing is limited to Just Works. Printers requiring a
  PIN or passkey must be paired separately with interactive BlueZ tooling.
- Classic PPD/filter workflows are deprecated in newer CUPS versions.
