# ICA Shopping List & Barcode (Home Assistant)

A Home Assistant integration for [ICA](https://www.ica.se) shopping lists, built
around a barcode scanner.

Scan an EAN with an ESP32 + barcode scanner running ESPHome, and the item lands
on your ICA shopping list **in the right aisle** — the integration looks the
barcode up in ICA's product database and passes the product's article data
through, so ICA files it under Mejeri, Djupfryst, Frukt & Grönt and so on rather
than dumping it in "Ospecificerad".

The list is also exposed as a native Home Assistant **to-do list**, so you can
add, tick off, rename and delete items from the Lovelace card or by voice.

> **Status:** works against the live ICA API and is in daily use by the author,
> but it is young and the ICA API is undocumented and unofficial. Expect rough
> edges.

## What makes this different

Other ICA integrations sync the list. This one does that **and** gives you the
scanner half: barcode → product lookup → correctly categorised list item, driven
by actions you can call from ESPHome, an automation, or a script.

## Requirements

- An ICA account that supports **password login** (not BankID-only).
- Home Assistant must reach the internet from a **Swedish IP** — ICA's API
  gateway rejects requests from outside Sweden. If it does, the integration
  raises a repair issue telling you so.
- Home Assistant 2025.1 or newer.

## Installation

1. In HACS → **Custom repositories**, add `https://github.com/daha/ha-ica-shopping-barcode` as an **Integration**.
2. Install **ICA Shopping List & Barcode**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → ICA**, sign in with your
   personnummer (12 digits) and password, and pick the shopping list to use.

Only one ICA list is configured per install; the actions below can still target
your other lists by name.

## The to-do list

A `todo.ica_<list>` entity appears for the configured list. It supports adding,
deleting, ticking off and renaming items, works with the standard **To-do list**
card, and is available to Assist ("add bröd to ICA Inköpslista").

Adding from the card or by voice always adds, even if the item is already
there — you can see the list, so a silent no-op would just be confusing. The
scanner actions below behave differently, on purpose.

## Actions

| Action | Input | Returns |
| --- | --- | --- |
| `ica.lookup_product` | `barcode` | `found`, `name`, `ean`, `category` |
| `ica.add_item` | `name`, `list` *(optional)* | `added`, `name` |
| `ica.scan_barcode` | `barcode`, `list` *(optional)* | `found`, `added`, `name`, `ean`, `category` |
| `ica.refresh_list` | – | `list`, `items`, `unchecked` |

`ica.scan_barcode` is the one a scanner calls — it looks the barcode up and adds
the product in a single step.

- **Unknown barcode?** Nothing is lost: the item is added as
  `Okänd vara <ean>` and the response reports `found: false`, so your device can
  warn you and you can rename it later.
- **Already on the list?** The scanner actions skip it (`added: false`) rather
  than creating duplicates — a scanner has no display, so silently deduping is
  the useful behaviour. An item you have already ticked off does *not* block a
  re-add, so you can buy it again next week.
- **`ica.refresh_list`** forces an immediate re-sync when you can see the local
  copy is stale, and tells you what it found.

Example:

```yaml
action: ica.scan_barcode
data:
  barcode: "7318690136149"
response_variable: result
```

```yaml
# result
found: true
added: true
name: Mellanmjölk Lite längre hållbarhet ICA
ean: "7318690136149"
category: Mejeri
```

The device firmware is out of scope for this repository — it only needs to call
`ica.scan_barcode` with the scanned code. See
[SmartHome-yourself/barcode-scanner-for-esphome](https://github.com/SmartHome-yourself/barcode-scanner-for-esphome)
and [MattFryer/HA-Mealie-Barcode-Scanner](https://github.com/MattFryer/HA-Mealie-Barcode-Scanner)
for ESPHome configurations to start from.

## Language

The interface is available in English and Swedish. Item text stays in Swedish,
as ICA returns it.

## Credits

Authentication and API groundwork ported from
[kanylbullen/ica-mcp](https://github.com/kanylbullen/ica-mcp) and
[LazyTarget/ha-ica-todo](https://github.com/LazyTarget/ha-ica-todo), both MIT.
See `NOTICE`.

This project is not affiliated with, endorsed by, or supported by ICA. It uses
an undocumented API that may change without warning.
