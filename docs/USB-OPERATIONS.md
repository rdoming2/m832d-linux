# USB operations

USB validation uses the standard CUPS USB backend and a separate test queue.
The existing manufacturer queue must not be changed or removed.

Before hardware testing, inspect the existing queue and available devices
without changing them:

```sh
lpstat -v
lpinfo -v
```

Install the project filter and generated PPD, then create a separately named
test queue using the discovered `usb://` URI. The default `w53h70` media
(approximately 53 × 70 mm), `w110h146` (approximately 110 × 146 mm), and a
custom 2.25 in (57.15 mm) width have been successfully tested over the USB and
BLE paths. Start with one small job using the default `w53h70` media. Do not
retry after any bytes may have reached the printer; inspect the paper and queue
state manually before another attempt. These results do not establish
arbitrary custom heights, full-bleed output, or maximum printable width.

The `lpinfo -v` output contains complete device records such as:

```text
direct usb://Phomemo/M832D?serial=DEVICE_SERIAL
```

That URI is illustrative. Copy the entire URI reported for the intended
physical printer, including escaping and query parameters; do not infer a URI
from the model name or remove a serial value. Find the generated PPD's model
identifier with:

```sh
lpinfo -m
```

Use the first field of the `Phomemo-M832D.ppd` entry as the `-m` value. Create
a separate queue, substituting the exact discovered URI and model identifier:

```sh
sudo lpadmin -p M832D-USB -E \
  -v 'usb://Phomemo/M832D?serial=DEVICE_SERIAL' \
  -m 'Phomemo-M832D.ppd' \
  -o PageSize=w53h70 \
  -o printer-error-policy=stop-printer
```

The shared filter supports `M832DPagePause=5`, `10`, `20`, or `30` seconds for
manual tear-off between pages; the default is `Off`. For a paused job, each
page receives the captured footer instead of an additional normal inter-page
feed before a bounded output drain and the timer. Transfer acknowledgement, the
drain, and CUPS job completion do not confirm physical print completion.

Verify the new queue without printing:

```sh
lpstat -v M832D-USB
lpoptions -p M832D-USB -l
```

USB transfer acknowledgement or CUPS completion is not confirmation of
physical print completion. If the printer exposes a non-standard interface,
stop and document it before considering a custom backend.
