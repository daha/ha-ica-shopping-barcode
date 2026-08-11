# ICA Shopping List (Home Assistant)

A custom Home Assistant integration that looks up scanned barcodes (EAN/GTIN)
against ICA and adds products to your ICA shopping list. Designed to be driven by
an ESP32 + barcode scanner running ESPHome.

## Status
Phase 1: services `ica.lookup_product`, `ica.add_item`, `ica.scan_barcode`.

## Requirements
- An ICA account with password login (not BankID-only).
- Home Assistant reachable from a Swedish IP (ICA's API blocks non-Swedish IPs).

## Credits
Auth and API approach ported from [kanylbullen/ica-mcp](https://github.com/kanylbullen/ica-mcp)
and [LazyTarget/ha-ica-todo](https://github.com/LazyTarget/ha-ica-todo) (both MIT). See `NOTICE`.
