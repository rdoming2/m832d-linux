# Business Requirements Document: Phomemo M832D BLE Backend for Linux

Version: 1.4 — Functional implementation baseline
Date: 2026-09-29
Target environment: Linux, BlueZ, CUPS, Phomemo M832D

## 1. Purpose and business outcome

Enable users to print ordinary documents wirelessly to the Phomemo M832D from Linux applications through CUPS. The project provides a project-owned generated PPD, raster filter, and separately installable BLE backend so users retain consistent document rendering and media selection across dedicated USB and BLE queues.

The maintained deliverable is a separately installable driver/filter/backend set and a dedicated M832D-BLE queue. The existing USB queue must remain usable. The implementation is functional and maturing.

## 2. Problem statement

The M832D mobile application uses BLE GATT rather than a usable serial printing interface in the tested workflow. Initial Linux connections selected Classic Bluetooth and failed. Explicit LE connection establishment and interactive LE pairing resolved connection and notification access. Large-image printing initially stopped partway through with unacknowledged 20-byte writes. A configuration using acknowledged writes, chunks up to 182 bytes, and no additional delay printed successfully.

A standalone Python sender now prints compressed and uncompressed monochrome images. It is not a CUPS backend: its job validator expects a particular image-job envelope, and its fixed observation period does not prove physical completion. The vendor filter also exchanges status and output-drain requests with its backend. Simply forwarding a file would leave those interactions unimplemented.

## 3. Evidence and confidence

| Finding | Evidence | Confidence / limit |
|---|---|---|
| Explicit LE establishment solves the observed Classic connection failure | User-tested connection through BlueZ ConnectDevice | Verified on the current setup; reconnect and version coverage remain limited |
| Notification subscription requires authentication on the tested printer | HCI capture shows descriptor write rejected with Insufficient Authentication, followed by pairing confirmation timeout | Verified; visible pairing agent subsequently resolved the failure |
| Acknowledged writes with chunks up to 182 bytes and no added delay print small and larger images | User-confirmed physical prints | Verified configuration; acknowledgment and chunk size changed together, so the independent cause of the earlier failure is not established |
| CUPS printing succeeds with tested media widths | User-confirmed physical prints over USB and BLE at 53 mm, 110 mm, and custom 2.25 in (57.15 mm) width | Verified on the tested setup; custom result records width only, and broader media, firmware, and reliability coverage remain limited |
| The project `rastertom832d` filter produces sharper-looking text than the manufacturer-supplied `rastertoM08F` filter on the tested setup | User-observed output comparison | Observational result, not a guarantee across documents, settings, media, firmware, or upstream CUPS rasterization |
| Uncompressed raster jobs print over BLE | User-confirmed test | Verified for standalone sender jobs, not the complete CUPS filter sequence |
| Captured compressed jobs decode to Test and Best | LZO decoding and rendered images | Verified; 576 × 164 images, three compressed blocks per job |
| The filter's M832 branch uses uncompressed raster output | Source inspection: compression-off command and GS v 0 raster header | Verified in supplied source and exercised by the tested CUPS configurations |
| Filter depends on bidirectional backend interaction | Source uses CUPS back-channel reads and side-channel drain requests | Verified; exact operational expectations must be mapped during implementation |
| Notification meanings and print completion are fully understood | Not established | Open: observed sequences must not be treated as authoritative completion/error states without validation |

Reference inputs: iPhone print capture; Linux failure capture; standalone `m832d.py`; user-confirmed print results. Local captures, logs, images, and vendor material belong under the ignored `research/artifacts/local/` hierarchy. The small capture-derived encoder fixtures under `research/artifacts/fixtures/` support deterministic offline tests. These are engineering evidence, not approval to install or change system services.

## 4. Stakeholders and users

- Primary user: Linux desktop user printing documents and images from applications or scripts.
- Administrator: installs the backend, verifies printer identity, creates the queue, and diagnoses service permissions and pairing failures.
- Maintainer: supports the backend, documents protocol behavior, and manages compatibility with BlueZ, CUPS, and Python dependencies.

The project owner approves scope, deployment, and release acceptance. One person may fulfill all roles.

## 5. Scope

### In scope for the first release

- One M832D printer on the existing Linux/BlueZ host, with explicit printer identity and adapter selection where needed.
- The PPD's `w53h70` choice (approximately 53 × 70 mm) remains the default; physical tests also cover `w110h146` (approximately 110 × 146 mm) and a custom 2.25 in (57.15 mm) width over USB and BLE.
- Project-owned GPLv3 raster filter and generated M832D PPD.
- Unmodified project-filter output carried over USB or BLE, subject to successful compatibility testing.
- Notification delivery to the filter through the CUPS back channel.
- Required CUPS backend lifecycle, side-channel responses, cancellation, queue behavior, logging, and installation/removal instructions.
- Automatic, bounded Just Works pairing of the explicitly addressed printer before the first print transmission when no LE bond exists.
- A separately named BLE queue, with controlled end-to-end validation.

### Out of scope for the first release

- Redistributing the manufacturer PPD or raster filter.
- General support for all Phomemo models or other operating systems.
- Cloud printing, a mobile application, or a custom print dialog.
- Automatic compression conversion of vendor output.
- Guaranteed exactly-once physical printing across loss of connection or power.
- Automatic printer firmware updates, system-wide Bluetooth mode changes, or removal of the USB queue.
- Broad CUPS-version support beyond the documented, tested host configuration.

## 6. Required user journeys

1. **Initial setup:** administrator installs dependencies, verifies the selected printer's address and adapter, creates a separate queue, and ensures the CUPS execution identity has the minimum permission needed for automatic pairing and routine BLE access.
2. **Normal printing:** user selects M832D-BLE, chooses the existing driver options, and prints without opening a terminal or confirming pairing again.
3. **Printer unavailable:** job remains recoverable with a clear queue status; the user can power on the printer and retry without recreating the queue.
4. **Printer fault:** paper-out, cover-open, or another supported condition is reported intelligibly and handled consistently with the vendor filter.
5. **Interrupted job:** the system distinguishes failure before sending data from an uncertain partial print. It does not silently restart a potentially printed job.
6. **Cancellation and removal:** user cancels a job or administrator removes the BLE integration without disabling the USB workflow.

## 7. Functional requirements

Priority: Must = release requirement; Should = desirable after required behavior is reliable.

| ID | Priority | Requirement | Acceptance evidence |
|---|---|---|---|
| FR-01 | Must | Accept the CUPS backend invocation and job input forms required by the selected CUPS version, including file and standard-input jobs. | Integration tests exercise both input forms and required discovery/invocation behavior. |
| FR-02 | Must | Identify the configured printer explicitly and resolve FF02 and FF03 by UUID. Numeric characteristic handles must not be hardcoded. | Logs and tests show the intended device, UUID resolution, and clear rejection when required capabilities are absent. |
| FR-03 | Must | Establish an LE connection explicitly; no silent fallback to Classic Bluetooth. For a public-address device, set and verify `PreferredBearer=le` before pairing or connecting. Reuse a fresh LE pairing connection, and permit generic `Device1.Connect` only when the preference, fresh sole bond, or a random address makes LE unambiguous. | Offline tests cover preference provisioning, fresh-pair reuse, sole-bond reconnect, random-address reconnect, and fail-closed handling when the preference cannot be set. Cold-start and reconnect hardware tests establish LE successfully or produce an actionable error. |
| FR-04 | Must | Before transmitting print data, reuse an existing LE bond or make one bounded automatic Just Works pairing attempt for the explicitly configured device, then set `Trusted=true` only after bond verification. Pairing rejection, unsupported PIN/passkey methods, invalid bonds, property-write failures, and permission failures must produce a clear setup-required outcome without repeated attempts. | Offline tests verify exact-device agent filtering, property writes, timeout/cancellation cleanup, bond verification, and zero submitted bytes on failure; approved hardware testing confirms first-print enrollment. |
| FR-05 | Must | Forward vendor filter output in order without unintended insertion, removal, or modification of bytes. | A recording transport verifies byte-for-byte equivalence, including multiple pages and binary payloads. |
| FR-06 | Must | Use the validated acknowledged-write configuration as the initial transport policy, with chunks up to 182 bytes subject to actual connection/API constraints. | Tests verify response-enabled writes, ordering, limits, and failure reporting. |
| FR-07 | Must | Deliver printer notifications to the CUPS back channel in order, using the representation expected by the filter. | Filter queries receive their replies; split/coalesced delivery is tested against the filter parser. |
| FR-08 | Must | Implement the CUPS side-channel operations required by the filter, including output drain. Define drain as host-side pending output accepted through the transport, distinct from physical printing. | Drain completes only after prior buffered writes are acknowledged; faults return appropriate responses without indefinite waits. |
| FR-09 | Must | Serialize access per printer so concurrent jobs or queues cannot interleave print streams; hold the lock through verified connection teardown. An already-connected exact configured device may be adopted when it is not advertising. | Two simultaneous job attempts result in serialized delivery or an explicit busy outcome, and the next attempt starts only after the prior job's connection is closed. |
| FR-10 | Must | Maintain bounded memory and bounded waits while handling large pages and status traffic. | Full-page and fault tests show controlled buffering and no deadlock. |
| FR-11 | Must | Handle cancellation promptly and stop submitting additional print data; report that already accepted data may still print. | Mid-job cancellation test confirms transmission stops and records partial-job uncertainty. |
| FR-12 | Must | Distinguish no-data-sent failures from failures after data may have reached the printer, including unconfirmed disconnect cleanup. Apply retry policy accordingly. | Injected failures before, during, and after upload, plus teardown failures, produce the specified queue behavior. |
| FR-13 | Must | Report job outcome consistently with CUPS semantics and supported printer evidence. A fixed delay or ATT acknowledgment alone must not be presented as confirmed physical completion. | Completion policy is documented and validated against the filter and observed printer behavior. |
| FR-14 | Must | Provide installation, pairing, queue creation, diagnostics, upgrade, and removal instructions. Preserve the USB queue. | Setup and rollback are demonstrated on the target host. |
| FR-15 | Should | Provide a diagnostic command that checks device availability, bond/access, services, and transport configuration without printing. | Command distinguishes common setup faults and does not send a raster job. |

## 8. Status, completion, and recovery policy

Implementation must explicitly track at least: waiting for printer, connecting, authentication required, ready, transmitting, awaiting printer/filter outcome, failed before transmission, uncertain partial print, and cancelled. Mapping these states to supported CUPS status and exit behavior is an implementation task.

Notifications such as `01 01`, `02 b6 00`, `1a 0f 0c`, `1a 3e 00 00`, and `1a 3b 04 19 00 01 00` were observed. Their meanings must be established from source and controlled tests before using them as authoritative state signals. The vendor filter's existing interpretation should be reused where applicable, rather than inventing a competing parser.

Retries may be automatic only when the backend can establish that no print data was submitted. After partial transmission, loss of connectivity, or uncertain completion, the default must require an explicit retry decision through the documented queue workflow. CUPS queue error policy must be configured to preserve this behavior; backend logic alone is insufficient.

Successful CUPS delivery and confirmed physical print completion must be distinguished in documentation. If the available protocol cannot reliably establish physical completion, this limitation must be explicit and accepted before release. No additional fixed 30-second sleep should be treated as a completion protocol simply because it worked in the standalone test.

## 9. Nonfunctional requirements

- **Reliability:** no interleaving, silent byte loss, unlimited retry loops, or indefinite side-channel waits.
- **Performance:** baseline the tested full-page workload and record rendering, connection, upload, and completion-observation times separately. Numeric service targets will be agreed after this baseline; current small-image timings do not establish full-page performance.
- **Security:** restrict scanning, pairing-agent callbacks, bearer preference, trust changes, and connections to the configured device and LE bearer. Automatic Just Works enrollment has no human confirmation or meaningful MITM protection, so administrators must verify the complete address before queue creation. Do not log keys, passkeys, document contents, or raw raster payloads by default. Use the minimum permissions required by the CUPS execution context.
- **Maintainability:** separate CUPS adaptation, BLE transport, and status policy; document version assumptions and protocol evidence. Runtime changes must have a clear rollback path.
- **Observability:** log job identifier, stage, bytes submitted/acknowledged, transport configuration, elapsed time, and actionable errors. Detailed notification logging is opt-in or appropriately bounded.
- **Compatibility:** document tested Linux, BlueZ, CUPS, Python, and Bleak versions. Support the legacy Bleak device-construction API used by Raspbian Trixie, while preferring experimental BlueZ bearer-selection APIs when available. Reuse a fresh pairing connection or unambiguous random-address LE device when those APIs are absent, and provide clear errors for ambiguous public-address devices.
- **Resource management:** close connections and descriptors, release locks, and handle broken pipes and process termination without leaving the printer permanently unavailable.

## 10. Integration constraints and design boundaries

Proposed pipeline:

Linux application → CUPS document conversion → rastertom832d + M832D PPD → USB or BLE backend → M832D

The CUPS filter requests 8-bit grayscale input and renders it to the printer's
monochrome raster. Atkinson is the default renderer, with Floyd–Steinberg and
legacy threshold rendering available as explicit `M832DRendering` choices.
Both error-diffusion modes use a fixed midpoint of 128; threshold rendering
uses the configurable `M832DThreshold` cutoff. This rendering choice does not
change the byte-preserving USB/BLE transport contract.

Return path:

M832D notifications → BLE backend → CUPS back channel

The backend must also service CUPS side-channel requests while transmitting and receiving notifications. Its service execution identity may have different D-Bus/Bluetooth permissions from the interactive user; this must be tested rather than inferred from the working CLI.

Initial transport settings are acknowledged writes, no artificial inter-write delay, and a maximum requested chunk size of 182 bytes. These settings are a tested starting point, not universal printer limits. The vendor output must not pass through the standalone sender's fixed SETUP/FOOTER validator or have the mobile-app setup prepended automatically.

The historical manufacturer PPD specified an A4 default; the project-generated PPD defaults to `w53h70`. Successful CUPS testing covers `w53h70`, `w110h146`, and a custom 2.25 in (57.15 mm) width over USB and BLE. Named labels and custom media are declared full-page imageable; A4 and Letter retain their hardware margins. This declares the CUPS imageable area only and does not establish physical full bleed, maximum printable width, or arbitrary custom-media behavior. The standalone encoder's 576-pixel canvas must not limit CUPS output; the vendor filter emits dimensions derived from the selected CUPS raster. A4 pages are substantially larger and require independent validation. Page boundaries, media settings, copies, and feed behavior remain owned by the existing CUPS/filter pipeline.

## 11. Delivery phases and gates

| Phase | Deliverable | Exit gate |
|---|---|---|
| 1. Compatibility investigation | Map M832 commands, options, status parsing, cancellation, and USB/BLE assumptions. | Documented integration contract and representative full-page workload. |
| 2. Filter/driver implementation | Project filter, `.drv`, generated PPD, deterministic raster tests, and standard USB staging. | Offline protocol/filter/PPD tests pass. |
| 3. Hardware pilot | Separate standard-USB test queue, then separately configured M832D-BLE queue. | One-page and multiple-page jobs print correctly with expected settings. |
| 4. Reliability validation | Power-cycle, contention, paper/cover faults, cancellation, interrupted transfer, service-context tests. | Acceptance matrix passes or unresolved limitations receive explicit scope approval. |
| 5. Release | Versioned package, dependency list, operator guide, known limits, install/remove procedure. | Project owner approves release based on test evidence. |

Queue creation, privileged installation, and changes to service configuration are deployment actions to be performed under the user's deployment authorization after the package is reviewable.

## 12. Acceptance matrix

| Test | Required result |
|---|---|
| One-page text PDF using `w53h70` | Complete, readable page; media size and positioning agree with the USB reference. |
| Full 53 × 70 mm image/graphics document | Complete output without the earlier short partial-print behavior; no unexplained data loss. |
| Full 110 × 146 mm image/graphics document | Successful physical output over the tested USB and BLE paths; broader long-job and firmware coverage remains pending. |
| Custom 2.25 in (57.15 mm) width | Successful physical output over the tested USB and BLE paths; custom height and edge behavior remain pending. |
| Three-page document | Correct order and count, feed only between pages, no merged or missing pages. |
| Five consecutive jobs | All print once without manual reconnection or repeated pairing prompts. |
| Printer power cycle between jobs | Existing bond works, explicit LE reconnect succeeds, and the next job prints. |
| Printer off at submission | Bounded connection handling and clear recoverable queue state; no busy loop. |
| Paper out / cover open | Supported state is reported and recovery does not silently duplicate a partial page. |
| Bluetooth loss during upload | Job is reported as failed/uncertain; no automatic whole-job replay after partial submission. |
| Cancellation during upload | Backend ceases new submissions and releases resources; already transmitted data is acknowledged as potentially printable. |
| Concurrent jobs | No interleaved printer data; documented serialization or busy handling. |
| CUPS service execution | Backend accesses the bonded printer without a logged-in terminal agent for routine jobs. |
| First print to an unpaired printer | One bounded exact-device Just Works pairing attempt completes before any FF02 write, or the job is held with zero submitted bytes and an actionable setup error. |
| Side/back-channel behavior | Vendor filter completes required queries and drain requests without deadlock or fabricated status. |
| Remove BLE integration | USB queue and unrelated Bluetooth devices remain operational. |

Record software versions, printer firmware if obtainable, document identity, options, physical results, logs, and any retries for hardware tests. A queued job marked successful without inspection is not sufficient evidence for physical-output acceptance.

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Vendor filter assumes USB-specific timing or status behavior | Hangs or incorrect state over BLE | Map requests, capture actual exchanges, and validate side/back channels before unattended use. |
| BLE notification format differs from USB replies | Filter misinterprets state | Compare payloads and parser expectations; add a documented translation only if evidence requires it. |
| Full-size uncompressed pages stress buffering or timing | Partial prints or long job times | Bounded streaming, acknowledged transport, realistic page tests, and measured performance. |
| BlueZ experimental API or service permission differences | Works interactively but fails in CUPS | Explicit dependency/version checks and service-context testing. |
| Existing public-address bond with no writable explicit bearer API | Generic connection could select Classic | Set and verify `PreferredBearer=le` for the exact device or fail closed; the guarded generic fallback is limited to a verified preference, fresh sole LE bond, or random-address LE device. |
| Unknown completion semantics | False success or duplicate retries | Separate delivery from physical completion; conservative retry policy and explicit release limitation if needed. |
| Filter licensing/build dependencies | Distribution or installation blocked | GPLv3 project licensing, upstream attribution, and no manufacturer artifacts. |
| Multiple clients, including phone app | Connection contention | Per-printer lock, clear busy reporting, and documented exclusive-use expectations. |
| Silent Just Works enrollment authenticates no human-visible identity | A nearby impersonating device using the configured address could be bonded | Require verification of the complete address and adapter before queue creation; never select by name or accept callbacks for another object path. |
| CUPS identity lacks pairing-agent permission | First print is held before transmission | Report setup-required, avoid repeated pairing attempts, and require a separately approved minimum-permission deployment change. |

## 14. Open decisions

1. The initial validation environment is CUPS 2.4.19, BlueZ 5.87, Python 3.14, and Bleak 3.0.2. Offline compatibility coverage now includes the older Bleak device API used by Raspbian Trixie; the portable installer must check and report actual versions, and hardware validation on that platform remains to be established.
2. Installation builds the project-owned GPLv3 filter and PPD. The manufacturer queue and local artifacts under `research/artifacts/local/` remain separate reference material.
3. What status evidence can establish readiness and completion for this printer firmware?
4. Which CUPS error policy best exposes partial-job uncertainty without automatic reprinting?
5. Which additional media sizes, including 80 mm and A4, should be added after the validated `w53h70` and `w110h146` configurations?
6. What full-page throughput is acceptable once measured on the current adapter?
7. Does the filter parser tolerate notification fragmentation/coalescing as delivered by the back channel?
8. Does the USB connection expose a repeatable status or notification that can be validated as actual page completion, allowing the empirical feed-rate allowance to be removed?

These questions do not block offline implementation. They must be resolved or recorded as accepted limits at the relevant delivery gate.

### 14.1 Verified filter/backend contract

Source inspection established these requirements for the M832 branch:

- The filter writes firmware (`1f 11 07`), idle (`1f 11 43`), cover (`1f 11 12`), and paper (`1f 11 11`) queries and expects binary replies through CUPS back-channel fd 3.
- The backend must forward each FF03 value as raw bytes, without ATT framing, hexadecimal encoding, or delimiters.
- The filter uses CUPS side-channel fd 4 and requests output drains after status queries, setup, raster headers, and raster blocks. Raster-path drain requests use an approximately 100 ms timeout.
- A successful drain means all filter bytes preceding the request have completed acknowledged transport writes. It is not evidence that the printer has physically completed a page.

The shared filter exposes an optional bounded `M832DPagePause` setting
(`Off`, 5, 10, 20, or 30 seconds) for manual tear-off. It is disabled by
default and applies only between pages on BLE and USB paths. For a paused job,
the filter terminates each page with the captured footer instead of also adding
the normal inter-page feed, and waits for a bounded host-side output drain
before starting the timer. The drain and pause do not establish physical page
completion; with the option disabled, the original single-footer stream
remains unchanged.

The USB path continues to use the standard CUPS `usb://` backend. Offline
integration coverage exercises the project filter with real libcups
side-channel framing and a simulated USB drain response; Linux/libusb CUPS
2.4.19 is the checked backend implementation. Other platform or CUPS backend
versions remain compatibility-validation items. Since USB drain can precede
the end of physical printing, the USB path adds a bounded page-height settling
allowance before the selected tear-off interval. The allowance assumes 8 mm/s
at 300 dpi, is capped at 60 seconds, and must not be described as confirmed
physical completion.
- The filter's status parser assumes complete records and has competing monitor and synchronous readers. Fragmented/coalesced notification behavior and the possible reader race require harness and hardware validation.
- The M832 output is an uncompressed `GS v 0` raster stream. The BLE backend must not LZO-compress, validate as a mobile-image envelope, or otherwise modify it.
- The project filter exposes Darkness as its density control. Heat and Feed are not exposed because the retained factory evidence does not establish independent mappings; fixed protocol defaults remain part of the stream contract.

The implementation is a Python backend using Bleak and `dbus-fast`, with typed libcups bindings for back- and side-channel operations and a portable installer that detects CUPS paths.

## 15. Release definition

The project is complete when the user can print representative documents through a dedicated CUPS BLE queue using the existing model driver, the acceptance matrix has recorded results, fault and retry behavior is documented and tested, and installation/removal preserves the USB workflow. The release includes source, installation materials, tests, compatibility notes, and known limitations.
