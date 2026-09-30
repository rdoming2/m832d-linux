# M832D protocol contract

The CUPS path emits the uncompressed raster form currently established by the
local M832D captures and offline encoder:

1. `1f 11 08`, setup and density/heat/media commands, and raw mode
   `1f 11 35 00`.
2. One or more `GS v 0` blocks. Width is bytes per row and both width and
   height are little-endian 16-bit values.
3. A bounded `ESC d n` feed between pages, followed by the existing
   two-command footer. The final page is not followed by the inter-page feed.

The filter may optionally pause for 5, 10, 20, or 30 seconds after the
page. For a paused job, it terminates each page with the complete captured
footer instead of also adding the normal inter-page feed, waits for a bounded
host-side output drain, and then starts the timer. The drain does not establish
physical print completion. With the pause disabled, the original single-footer
stream remains unchanged.

The filter resolves CUPS options before constructing this stream and never
performs USB or BLE I/O. The BLE backend therefore remains byte-transparent.

Successful physical output has been tested over USB and BLE at 53 mm, 110 mm,
and a custom 57.15 mm width. The M832D's maximum physical printable width,
edge behavior, custom-media feed behavior, vendor status semantics, media
tracking, and physical completion indication remain hardware-validation items.
Numeric ATT handles are never part of this contract; BLE characteristics are
resolved by UUID.
