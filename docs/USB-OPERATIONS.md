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
feed before a bounded output drain. Because the printer continues physically
printing after USB transfer completes, the USB path then adds a bounded
page-height allowance before the selected tear-off interval. The allowance
assumes a conservative 8 mm/s at the fixed 300 dpi resolution and is capped at
60 seconds. It is an empirical timing allowance, not physical-completion
detection. Transfer acknowledgement, the drain, the allowance, and CUPS job
completion do not confirm physical print completion.

Further USB protocol research is required to determine whether the connection
provides a reliable status or notification that identifies actual page
completion. If such a signal can be validated against physical output, it
should replace the feed-rate estimate as the start of the configured tear-off
interval.

This path relies on the standard CUPS USB backend implementing
`CUPS_SC_CMD_DRAIN_OUTPUT`; the Linux/libusb backend in CUPS 2.4.19 has been
checked for that support. Other CUPS versions or platform USB backends require
separate validation. An existing queue keeps its installed PPD copy, so merely
reinstalling the model PPD may not add `M832DPagePause` to an older queue. Check
the option list below before printing, and do not alter the queue without
explicit approval.

Verify the new queue without printing:

```sh
lpstat -v M832D-USB
lpoptions -p M832D-USB -l
```

The option list for the project queue should include `M832DPagePause`. If it
does not, stop and inspect the queue's selected model rather than modifying the
manufacturer queue.

USB transfer acknowledgement or CUPS completion is not confirmation of
physical print completion. If the printer exposes a non-standard interface,
stop and document it before considering a custom backend.
