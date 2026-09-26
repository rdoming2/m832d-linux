# M832D protocol contract

The CUPS path emits the uncompressed raster form currently established by the
local M832D captures and offline encoder:

1. `1f 11 08`, setup and density/heat/media commands, and raw mode
   `1f 11 35 00`.
2. One or more `GS v 0` blocks. Width is bytes per row and both width and
   height are little-endian 16-bit values.
3. A bounded `ESC d n` feed and the existing two-command footer.

The filter resolves CUPS options before constructing this stream and never
performs USB or BLE I/O. The BLE backend therefore remains byte-transparent.

The M832D's final printable width, vendor status semantics, media tracking,
and physical completion indication remain hardware-validation items. Numeric
ATT handles are never part of this contract; BLE characteristics are resolved
by UUID.
