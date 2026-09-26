# Experimental Phomemo M832D Linux printing

This script sends the image protocol decoded from your iPhone capture through Bleak/BlueZ. It also encodes PNG/JPEG and other Pillow-readable images into the same format. No kernel driver is needed.

This repository now also contains the first offline-tested implementation of a
`m832dble` CUPS backend. It requires the manufacturer PPD and `rastertoM08F`
filter to be installed separately. Deployment and hardware validation remain
explicit administrator actions; see `docs/OPERATIONS.md`.

The initial CUPS/BLE media target is the PPD's `w53h70` (approximately 53 × 70
mm) choice, matching the workflow used to derive the standalone sender. The
manufacturer PPD defaults to A4; the BLE queue and test jobs must override that
default. A4 output is currently outside the validated BLE scope.

## Install and first print

On your Arch system, `python-bleak`, `python-pillow`, and `lzo` are required. They were already available in the environment used to build this script. If needed:

```sh
sudo pacman -S python-bleak python-pillow lzo
```

Alternatively install Bleak and Pillow in a Python virtual environment, plus your distribution's system liblzo2 package (Debian/Ubuntu: `liblzo2-2`).

Extract this directory, open a terminal there, turn the printer on, and disconnect the phone app. Run as your regular desktop user:

```sh
python m832d.py replay test.bin --address D6:4D:F2:16:B6:BF
python m832d.py replay best.bin --address D6:4D:F2:16:B6:BF
```

Each command prints one job. Replay preserves the captured payload bytes and, by default, sends acknowledged writes in chunks of up to 182 bytes without an artificial delay. It subscribes to FF03 first, queries status, requires a matching query response, then sends the remaining bytes through FF02. It listens for 30 seconds after upload. A completed transfer is not proof that the paper printed successfully.

Your earlier BlueZ troubleshooting established that this dual-mode printer needed `PreferredBearer: le`. Keep that existing configuration. If connection attempts again report `br-connection-not-supported`, check the printer's bearer in `bluetoothctl`; encoding changes will not fix a Classic-versus-LE connection problem.

## New images

Create a job and inspect a preview without connecting to the printer:

```sh
python m832d.py encode image.png image.bin --preview preview.png
python m832d.py replay image.bin --address D6:4D:F2:16:B6:BF
```

Or encode and send in one command:

```sh
python m832d.py print image.png --address D6:4D:F2:16:B6:BF
```

Images wider than 576 pixels are shrunk proportionally. Smaller images are centered without enlargement. Transparency is composited onto white. Threshold defaults to 160; adjust with `--threshold 128`, for example. No dithering is applied. The preview shows the actual binary raster.

576 pixels is the width verified in your two captures, **not a confirmed full-paper printer width**. `--width` allows other multiples of eight for experiments, but physical resolution, full-page dimensions, and long-job behavior still need verification. PDF rendering is not included; export a page to PNG first.

## Transport and limits

- Characteristics are resolved by UUID, not the differing Linux/iPhone numeric handles.
- Chunk size is capped at 182. Command-mode writes are also capped at Bleak's `max_write_without_response_size`. See [Bleak's API](https://bleak.readthedocs.io/en/latest/api/client.html).
- Default pacing is no artificial delay and the default mode is acknowledged `request` writes. `--delay-ms 40` slows transmission; `--chunk-size 20` requests smaller writes; `--write-mode command` selects unacknowledged writes for experiments. These are not substitutes for printer flow control.
- `--wait 30` keeps the connection open longer after sending. Notification bytes are logged with elapsed times. No speculative completion or paper-error interpretation is imposed.
- No retries occur after partial transmission, since retrying might print duplicates.
- Vendor setup is copied from the successful capture. Raster bytes are LZO1X-compressed in 4096-byte blocks, each preceded by a 3-byte little-endian compressed length. Footer is two `ESC d 2` commands.

## Validation and next step toward CUPS

Five offline checks pass: both captured jobs decode; the supplied Test PNG regenerates its captured stream byte-for-byte with the installed liblzo2; varied compression block lengths round-trip; transparency/pixel polarity is correct; corrupt framing is rejected. Different liblzo2 versions may generate different but valid compressed bytes, in which case the strict byte-equality test may fail while raster equivalence passes.

Run checks with:

```sh
python -m unittest discover -p test_encoder.py -v
```

The acknowledged-write configuration has printed short and larger standalone jobs on the development printer. `01 01` and the other observed notifications still have provisional meanings and must not be treated as completion evidence.

For CUPS, retain the working USB queue. The manufacturer filter emits uncompressed M832 raster data and depends on CUPS back-channel status replies and side-channel drain requests. The planned `m832dble` backend transports that output unchanged; it must not pass it through this script's mobile-job validator or prepend the captured setup sequence. See `M832D-BLE-Backend-BRD.md` for the release requirements.

## Backend development

Run all offline tests with:

```sh
python -m unittest discover -v
```

The backend modules are under `src/m832d_ble`. They separate strict device URI
handling, CUPS channels, explicit-LE transport, bounded job streaming, locking,
and outcome policy. The test suite includes a subprocess harness that assigns
the same fd 3/fd 4 channels used by a real CUPS filter.
