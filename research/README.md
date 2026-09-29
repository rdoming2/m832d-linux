# Research utilities and artifacts

This directory contains historical protocol-investigation utilities, not
supported printing or installation entry points. The scripts may scan for,
connect to, or subscribe to a printer and require deliberate hardware use.
They do not provide the configured-device and explicit-LE safeguards used by
the maintained CUPS backend.

- `scan.py` prints advertisements for devices named `M832D`.
- `sniff.py` discovers a device by advertised name and prints its services,
  characteristics, and numeric handles.
- `listen.py` discovers a device by advertised name and listens for FF03
  notifications.

Numeric handles reported by these exploratory scripts are observations only.
Production code resolves FF02 and FF03 by UUID and selects the configured
printer and LE bearer explicitly.

## Artifacts

`artifacts/fixtures/` contains the small tracked `test.bin`, `best.bin`, and
`test.png` fixtures used by the legacy encoder tests. They are capture-derived
test inputs, not production runtime assets.

`artifacts/local/` is ignored. Keep private captures, logs, images, Bluetooth
addresses, manufacturer PPDs, raw print payloads, and other third-party
material there. Review provenance and sharing rights before adding anything to
version control. Hardware tests require explicit approval; offline tests are
preferred.
