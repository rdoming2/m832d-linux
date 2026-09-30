# Repository guidance

This directory contains the M832D CUPS driver, raster filter, and
BLE backend, plus secondary historical protocol-research tools. The
implementation is functional and maturing; `M832D-BLE-Backend-BRD.md` is the
requirements baseline.

## Safety and scope

- Do not change CUPS queues, BlueZ configuration, pairing, D-Bus policy, system
  services, or files outside this repository without explicit user approval.
- Hardware tests require explicit approval. Offline tests are always preferred
  before using the printer.
- Preserve the existing USB queue and vendor driver installation.
- Never automatically retry after any print data may have reached the printer.
- Do not describe an ATT acknowledgement, CUPS drain, or elapsed delay as
  confirmed physical print completion.
- Resolve FF02 and FF03 by UUID. Never copy numeric handles from captures.
- Select the configured printer and LE bearer explicitly; do not silently fall
  back to Classic Bluetooth or select a printer only by advertised name.

## Sensitive and third-party inputs

PPDs, packet captures, logs, photos, Bluetooth addresses, and raw print payloads
may contain private or third-party material. Keep ignored evidence out of commits
unless the user explicitly approves it. Local evidence belongs under
`research/artifacts/local/`; the release must require a separately installed
manufacturer PPD/filter until redistribution rights are established.

## Development conventions

- Use four-space indentation and preserve the existing Python style.
- Keep CUPS adaptation, BLE transport, and status/recovery policy separated.
- Bound queues, waits, scans, connection attempts, and channel operations.
- Send vendor-filter output byte-for-byte and in order.
- Keep logs actionable, but do not log document data or full notifications by
  default.
- Add deterministic offline tests for protocol or state-policy changes.
- Keep `README.md` and the BRD synchronized with transport defaults and known
  limitations.

## Verification

Run the complete offline suite from this directory:

```sh
python -m unittest discover -v
```

The legacy encoder-only suite can be run with:

```sh
python -m unittest discover -p test_encoder.py -v
```

Do not invent formatter, linter, packaging, or deployment commands that are not
present in the repository.
