# M832D BLE backend operations

This project installs a GPLv3 `rastertom832d` filter and generated M832D PPD.
The BLE backend carries that filter output unchanged. Keep the existing
manufacturer USB queue until USB and BLE acceptance testing are complete.

## Supported baseline

Initial development used CUPS 2.4.19, BlueZ 5.87, Python 3.14, Bleak 3.0.2,
and dbus-fast 5.0.22. Other versions are not yet validated. The BlueZ
`ConnectDevice` or `PreferredBearer` API must be available so the backend can
select LE explicitly.

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
D-Bus policy.

## Pair and diagnose

Pair the selected printer interactively through the normal BlueZ tooling and
confirm the pairing on a visible agent. Record its Bluetooth address and the
adapter to use. Do not configure a queue by advertised name alone.

Before creating a queue, run the non-printing diagnostic as the same service
identity that will execute CUPS backends:

```sh
m832dble-diagnose 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0'
```

The diagnostic performs a bounded LE scan and connection, resolves FF02/FF03,
and subscribes to notifications. It does not send status queries or raster
data. It does not set `PreferredBearer`; on BlueZ versions without
`ConnectDevice`, an administrator must provision and verify
`PreferredBearer=le` separately. Failure under the CUPS identity, despite success as a desktop user,
indicates a bond, BlueZ API, or system-bus permission problem. Determine the
minimum local permission change required before modifying policy; this package
does not install a permissive D-Bus rule.

## Create the separate queue

Queue creation is an administrator deployment action. Select the already
installed M832D PPD and use an explicit address and adapter. For example:

```sh
sudo lpadmin -p M832D-BLE -E \
  -v 'm832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0' \
  -P /path/to/the/installed/M832D.ppd \
  -o PageSize=w53h70 \
  -o printer-error-policy=stop-printer
```

Use the PPD already installed on the host; do not copy it from this repository
for redistribution. Confirm the resulting queue does not replace or rename the
USB queue. The `stop-printer` policy is intentional: a backend failure after
submission is uncertain and must not silently replay a whole job.

The initial BLE validation target is the PPD's `w53h70` media choice. The
manufacturer PPD itself defaults to A4, so select `w53h70` explicitly when an
application supplies its own media setting. For a controlled test:

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
- Classic PPD/filter workflows are deprecated in newer CUPS versions.
