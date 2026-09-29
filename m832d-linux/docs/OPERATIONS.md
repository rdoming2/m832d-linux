# M832D BLE backend operations

This project installs a GPLv3 `rastertom832d` filter and generated M832D PPD.
The BLE backend carries that filter output unchanged. Keep the existing
manufacturer USB queue until USB and BLE acceptance testing are complete.

## Supported baseline

Initial development used CUPS 2.4.19, BlueZ 5.87, Python 3.14, Bleak 3.0.2,
and dbus-fast 5.0.22. Other versions are not yet validated. The backend prefers
BlueZ `ConnectDevice`, but it can reuse a fresh LE pairing connection or connect
an existing random-address LE device without experimental BlueZ APIs. An
existing public-address device still requires `ConnectDevice` or a verified
`PreferredBearer=le` setting so Classic cannot be selected silently.

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
set `PreferredBearer`. On BlueZ versions without `ConnectDevice`, an existing
public-address device requires an administrator to provision and verify
`PreferredBearer=le` separately; random-address LE devices do not. Failure under
the CUPS identity, despite success as a desktop user, indicates a bond, BlueZ
API, or system-bus permission problem. Determine the minimum local permission
change required before modifying policy; automatic pairing additionally
requires permission to register an agent and call `Device1.Pair`. This package
does not install a permissive D-Bus rule.

The backend never sets `Trusted`, makes its agent the BlueZ default, changes
adapter pairability/discoverability, or removes a bond. Pairing rejection,
PIN/passkey requests, timeouts, stale keys, and permission failures hold the job
with zero submitted bytes. Recover a stale bond by explicitly removing it with
normal administrator BlueZ tooling, re-verifying the address, and releasing or
resubmitting the held job; bond removal is never automatic.

## Create the separate queue

Queue creation is an administrator deployment action. After installing the
backend, list CUPS device records:

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

The generated PPD defaults to `w53h70`, which is the initial BLE validation
target. Select `w53h70` explicitly when an application supplies its own media
setting. For a controlled test:

```sh
lp -d M832D-BLE -o PageSize=w53h70 -o fit-to-page document.pdf
```

An A4 job produces roughly a megabyte of uncompressed raster and commands a
much longer feed than the capture-validated 53 mm workflow. A4 is not currently
a BLE release target.

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
- Printable width, media tracking, feed calibration, and physical completion
  semantics require controlled hardware validation.
- Physical completion semantics for observed notifications are not established.
- Automatic first-print pairing is limited to Just Works. Printers requiring a
  PIN or passkey must be paired separately with interactive BlueZ tooling.
- Classic PPD/filter workflows are deprecated in newer CUPS versions.
