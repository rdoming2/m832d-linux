# Experimental Phomemo M832D Linux printing

This project contains two related, but distinct, printing paths for the
Phomemo M832D:

- `m832d.py` is a standalone image encoder and experimental BLE sender for a
  mobile-image protocol inferred from captures.
- The CUPS implementation consists of a project-owned raster filter, generated
  PPD, and the `m832dble` backend. The filter emits an uncompressed M832 raster
  stream, and the backend transports those bytes unchanged over BLE.

The implementation is experimental. Historical testing reported successful
short and larger standalone transfers, but that evidence does not validate the
complete CUPS pipeline, all printer firmware, or the hardware acceptance matrix
in [`M832D-BLE-Backend-BRD.md`](M832D-BLE-Backend-BRD.md).

The initial BLE media target is the generated PPD's `w53h70` choice
(approximately 53 × 70 mm). A4, Letter, other large media, final printable
width, margins, feed calibration, multi-page behavior, fault recovery, and
physical-completion detection remain outside the validated BLE scope.

## Safety and outcome semantics

Hardware tests must be deliberate. Installation and offline tests do not
contact the printer. Preserve existing manufacturer drivers and USB queues, and
do not implicitly change pairing, BlueZ preferences, D-Bus policy, CUPS queues,
or system services.

Never automatically retry after print data may have reached the printer. A
failure after submission can represent an uncertain partial print; replaying it
could produce a duplicate. Cancellation prevents additional writes but cannot
recall bytes already accepted by the printer.

An ATT acknowledgement confirms BLE transport acceptance only. A CUPS drain
confirms that preceding bytes completed acknowledged writes only. Neither those
events, a successful backend exit, nor an elapsed delay proves physical output
or physical print completion. Observed notification meanings remain
provisional.

## Standalone sender prerequisites

The standalone encoder requires Python, Pillow, and the system `liblzo2`
library. BLE sending additionally requires Bleak, dbus-fast, BlueZ, and an
account authorized to access BlueZ. Install equivalent packages for the target
distribution; for example, the LZO runtime is commonly provided by `lzo` on
Arch Linux and `liblzo2-2` on Debian-family systems.

Run commands from this source directory. Before an approved BLE transfer,
ensure that the selected printer is available and disconnect competing clients
such as the phone application.

## Standalone image use

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

Each sending command attempts one transfer. Transfer completion does not
establish physical print completion.

The sender accepts PNG, JPEG, and other Pillow-readable image formats. Images
wider than the selected canvas are reduced proportionally; narrower images are
centered without enlargement. Transparency is composited onto white. The
default threshold is 160, and `--threshold 128`, for example, selects a
different cutoff. No dithering is applied. The preview displays the resulting
binary raster. PDF rendering is not included in the standalone encoder; render
the page to an image first. CUPS may perform its own document-to-raster
conversion before invoking the project filter.

The included capture-derived fixtures use a 576-pixel raster width. This is not
confirmation of the printer's full physical width. `--width` permits other
multiples of eight for experiments, but physical dimensions and long-job
behavior require separate validation.

## Standalone BLE transport

- FF02 and FF03 are resolved by UUID rather than copied numeric handles.
- The default mode uses acknowledged writes, a maximum chunk size of 182 bytes,
  and no artificial inter-write delay.
- `--delay-ms 40` introduces a delay, `--chunk-size 20` requests smaller
  writes, and `--write-mode command` selects unacknowledged writes for
  experiments. These options are not substitutes for printer flow control.
- `--wait 30` keeps the connection open after upload. Waiting and received
  notifications do not confirm printing.
- Vendor setup follows the successful capture-derived protocol. Raster bytes
  are LZO1X-compressed in 4096-byte blocks, each prefixed by a three-byte
  little-endian compressed length. The footer contains two `ESC d 2` commands.

The tested dual-mode printer required explicit LE bearer selection. The CUPS
backend requests an LE connection when BlueZ supports `ConnectDevice` and
otherwise verifies an administrator-provisioned `PreferredBearer=le`; it does
not silently fall back to Classic Bluetooth or select a printer only by its
advertised name. The backend and diagnostic do not modify the BlueZ bearer
preference.

## CUPS backend and filter

The CUPS filter output is not the standalone sender's compressed mobile-image
envelope. The `m832dble` backend must transport filter output byte-for-byte and
must not run it through the standalone validator or prepend the standalone
setup sequence.

Backend device URIs contain an explicit Bluetooth address. Specify the adapter
as well when multiple adapters are available or reproducibility is required:

```text
m832dble://AA-BB-CC-DD-EE-FF/?adapter=hci0
```

The backend scans on the LE transport and matches the configured address. It
uses acknowledged FF02 writes, FF03 notifications, bounded channels and waits,
per-printer locking, and conservative retry/stop outcomes. Pairing and bearer
configuration must be provisioned separately and verified under the service
identity that runs the backend.

`m832dble-diagnose` performs a non-printing check of scanning, connection,
bond/access state, FF02/FF03 capabilities, and notification subscription. It
does not send status queries or raster data.

Use a separately named BLE queue with `PageSize=w53h70` and
`printer-error-policy=stop-printer`. Do not replace or modify an existing USB
or manufacturer queue. Deployment is an explicit administrator action; follow
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) and
[`docs/USB-OPERATIONS.md`](docs/USB-OPERATIONS.md).

The installer does not create queues, pair the printer, set BlueZ preferences,
change D-Bus policy, restart CUPS, or install Python dependencies. A plain
`pip install` also does not perform the complete CUPS deployment.

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

- The complete USB and BLE CUPS hardware acceptance matrix remains outstanding.
- Physical completion and detailed printer status semantics are not
  established.
- Media tracking, reconnect behavior, fault injection, long jobs, multi-page
  jobs, and broad firmware compatibility require further hardware validation.
- Explicit LE requires BlueZ `ConnectDevice` support or an
  administrator-provisioned `PreferredBearer=le` setting.
- Classic PPD/filter workflows are deprecated in newer CUPS releases.
- Backend queues are bounded, but the current raster filter constructs the
  converted output in memory.
- Competing Bluetooth clients can prevent or interrupt a connection.

## Licensing and third-party material

This project is distributed under GPLv3; see [`LICENSE`](LICENSE). Attribution
is recorded in [`NOTICE`](NOTICE). Manufacturer PPDs, filters, proprietary
source, raw packet captures, logs, and document payloads are not licensed for
redistribution by this project and may contain sensitive information.
