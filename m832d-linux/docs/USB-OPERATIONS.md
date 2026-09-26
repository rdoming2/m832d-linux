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
test queue using the discovered `usb://` URI. Start with one small job using
the default `w53h70` media. Do not retry after any bytes may have reached the
printer; inspect the paper and queue state manually before another attempt.

USB transfer acknowledgement or CUPS completion is not confirmation of
physical print completion. If the printer exposes a non-standard interface,
stop and document it before considering a custom backend.
