# M832D Bluetooth research and experimental Linux printing

This repository contains exploratory Bluetooth Low Energy (BLE) research for
the Phomemo M832D and an experimental Linux printing implementation. The work
is not a production-ready printer driver, and the complete CUPS USB/BLE
hardware acceptance matrix has not yet been demonstrated.

## Repository layout

- `m832d-linux/` contains the maintained implementation: a standalone image
  encoder and sender, a CUPS raster filter and generated PPD, the `m832dble`
  CUPS backend, a non-printing diagnostic, installation scripts, documentation,
  and deterministic offline tests.
- `scan.py`, `sniff.py`, and `listen.py` are early protocol-investigation
  utilities. They are not supported printing or installation entry points and
  do not provide all of the address-selection and explicit-LE safeguards used
  by the CUPS backend.
- Local captures, packet traces, logs, Bluetooth addresses, and other research
  evidence may contain private or third-party material. Treat them as
  sensitive and review them before sharing or committing them.

For normal development and usage, start with
[`m832d-linux/README.md`](m832d-linux/README.md). The requirements baseline is
[`M832D-BLE-Backend-BRD.md`](m832d-linux/M832D-BLE-Backend-BRD.md), and
administrator procedures are documented in
[`docs/OPERATIONS.md`](m832d-linux/docs/OPERATIONS.md) and
[`docs/USB-OPERATIONS.md`](m832d-linux/docs/USB-OPERATIONS.md).

## Choosing a tool

- Use the software under `m832d-linux/` for implementation, offline testing,
  diagnosis, and installation work.
- Use `m832d-linux/m832d.py` only for standalone image encoding and deliberate
  BLE transfer experiments. It is not a CUPS backend.
- Use `m832dble-diagnose` to check backend prerequisites without sending status
  queries or print data.
- Use the root-level research scripts only for deliberate protocol
  investigation. Numeric GATT handles reported by exploratory tools are
  observations, not stable configuration; production code resolves FF02 and
  FF03 by UUID.

## Safety and privacy

Hardware tests are explicit actions and are not part of installation or the
offline test suite. Preserve existing manufacturer drivers and USB queues, and
do not implicitly change pairing, BlueZ preferences, D-Bus policy, CUPS queues,
or system services. Disconnect competing clients, such as a phone application,
before an approved BLE test.

Never automatically retry a job after print data may have reached the printer:
the result could be a duplicate or partial print. An ATT acknowledgement, CUPS
drain, successful backend exit, or elapsed delay confirms neither physical
printing nor physical completion. Notification meanings remain provisional.

Do not publish raw captures, logs, Bluetooth addresses, PPDs, document
payloads, or full notifications without confirming that they are safe and
licensed to share.

## Development

The maintained project requires Python 3.10 or newer. From `m832d-linux/`, run
the complete offline test suite with:

```sh
PYTHONPATH=src python -m unittest discover -v
```

The suite does not contact the printer. See the nested README for dependency,
standalone sender, CUPS deployment, and known-limitation details.

## Licensing

The `m832d-linux/` project is distributed under GPLv3; see
[`m832d-linux/LICENSE`](m832d-linux/LICENSE) and
[`m832d-linux/NOTICE`](m832d-linux/NOTICE). Manufacturer software, proprietary
PPDs, and raw research evidence are not licensed for redistribution by this
project. No broader license claim is made here for the root-level exploratory
utilities.
