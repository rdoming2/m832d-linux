# M832D BLE backend operations

This backend carries output from the separately installed manufacturer
`M832D.ppd` and `rastertoM08F` filter. It does not include or replace those
files. Keep the existing USB queue until BLE acceptance testing is complete.

## Supported baseline

Initial development used CUPS 2.4.19, BlueZ 5.87, Python 3.14, Bleak 3.0.2,
and dbus-fast 5.0.22. Other versions are not yet validated. The BlueZ
`ConnectDevice` or `PreferredBearer` API must be available so the backend can
select LE explicitly.

## Install

Install the manufacturer driver first, without removing its USB queue. Install
Bleak and dbus-fast for the system Python used by CUPS. From this source tree,
review and then run:

```sh
sudo ./scripts/install.sh
```

`PREFIX`, `DESTDIR`, `PYTHON`, and `CUPS_SERVERBIN` can override detected
installation paths. If CUPS does not list the manufacturer PPD, provide its
existing path as `M832D_PPD=/path/to/M832D.ppd`. The installer does not restart
CUPS, create queues, pair devices, or change D-Bus policy.

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
data. Failure under the CUPS identity, despite success as a desktop user,
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
  -o printer-error-policy=stop-printer
```

Use the PPD already installed on the host; do not copy it from this repository
for redistribution. Confirm the resulting queue does not replace or rename the
USB queue. The `stop-printer` policy is intentional: a backend failure after
submission is uncertain and must not silently replay a whole job.

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

- BLE replies to all manufacturer filter firmware/paper/cover/idle queries
  still require controlled hardware validation.
- The manufacturer filter has fragile notification framing and competing
  back-channel readers.
- Its raster-path drain timeout is approximately 100 ms and may be shorter than
  a 4096-byte acknowledged BLE transfer.
- Physical completion semantics for observed notifications are not established.
- Classic PPD/filter workflows are deprecated in newer CUPS versions.
