# Experimental Phomemo M832D Linux printing

This script sends the image protocol decoded from your iPhone capture through Bleak/BlueZ. It also encodes PNG/JPEG and other Pillow-readable images into the same format. No kernel driver is needed.

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

Each command prints one job. Replay preserves the captured payload bytes but uses conservative 20 ms delays between writes. It subscribes to FF03 first, queries status, requires a matching query response, then sends the remaining bytes through FF02 without response. It listens for ten seconds after upload. A completed transfer is not proof that the paper printed successfully.

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
- Chunk size is capped at 182 and at Bleak's `max_write_without_response_size`; 20-byte fallback is supported. See [Bleak's API](https://bleak.readthedocs.io/en/latest/api/client.html).
- Default pacing: 20 ms between writes. `--delay-ms 40` slows transmission; `--chunk-size 20` requests smaller writes. Neither setting is a proven substitute for printer flow control on large jobs.
- `--wait 30` keeps the connection open longer after sending. Notification bytes are logged with elapsed times. No speculative completion or paper-error interpretation is imposed.
- No retries occur after partial transmission, since retrying might print duplicates.
- Vendor setup is copied from the successful capture. Raster bytes are LZO1X-compressed in 4096-byte blocks, each preceded by a 3-byte little-endian compressed length. Footer is two `ESC d 2` commands.

## Validation and next step toward CUPS

Five offline checks pass: both captured jobs decode; the supplied Test PNG regenerates its captured stream byte-for-byte with the installed liblzo2; varied compression block lengths round-trip; transparency/pixel polarity is correct; corrupt framing is rejected. Different liblzo2 versions may generate different but valid compressed bytes, in which case the strict byte-equality test may fail while raster equivalence passes.

Run checks with:

```sh
python -m unittest discover -p test_encoder.py -v
```

Physical printing has not been tested by this script yet. Start with the captured jobs, then a newly encoded short image. After those work, test larger images and determine whether `01 01` implements credits or acknowledgments before relying on long pages.

For CUPS, retain your working USB queue initially. A BLE backend can eventually send this same byte stream, but first inspect what your existing CUPS filter produces: USB output may use a different raster/compression mode. If identical, a transport-only backend is enough; otherwise add an image/raster conversion filter. A reliable backend also needs job serialization, paper/error handling, confirmed completion, and duplicate-safe retry behavior. This bundle is the first standalone sender, not an installed CUPS driver.
