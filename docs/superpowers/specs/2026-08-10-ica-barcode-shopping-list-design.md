# ICA Barcode Shopping List — Home Assistant Integration

**Design document** · 2026-08-10 · Status: approved for planning

## 1. Overview

A Home Assistant **custom integration** (installable via HACS) that connects Home
Assistant to a user's ICA account so that:

1. **Phase 1 (primary deliverable):** A barcode (EAN/GTIN) scanned by an ESP32 +
   scanner (running ESPHome) can be looked up against ICA's product database and
   added to the household's default ICA shopping list, via Home Assistant
   **services**.
2. **Phase 2 (follow-up):** The ICA shopping list is exposed in Home Assistant as
   a native **to-do list entity**, giving a Lovelace add/remove/check-off UI,
   automatic voice control through Assist, and regular background sync.

The ESP32/ESPHome device firmware is **out of scope** for this repository — it
only needs to call the Home Assistant service we expose. This repo is the
integration.

### Goals

- Own, cleanly-structured, shareable HACS integration under this repo.
- Reuse the proven ICA auth (OAuth2 / dynamic client registration / PKCE +
  personnummer/password) and API knowledge from `ica-mcp` and `ha-ica-todo`, but
  ported into our own code that we fully understand (MIT upstream; credit given).
- Never lose a scan: every scanned barcode results in a list item or an explicit,
  device-visible "not found" signal.
- Fully typed, tested, linted, formatted code with pre-commit + CI.

### Non-goals

- ESP32/ESPHome firmware (separate concern; consumes our service).
- Recipes, offers, bonus/loyalty, store lookup, dinner planning (present in
  `ica-mcp` but not needed here — YAGNI).
- Publishing a standalone PyPI client package (kept internal; structured so it
  *could* be extracted later, but not a deliverable).

## 2. Context & references

- `kanylbullen/ica-mcp` — Python MCP server; has `get_product` (EAN lookup),
  `add_product_to_shopping_list`, list add/check/uncheck/remove. Source of the
  product-lookup approach. Auth itself was ported from `ha-ica-todo`.
- `LazyTarget/ha-ica-todo` — early-stage HA integration with the same
  personnummer/password auth and a shopping-list concept. Source of the HA auth /
  config-flow / todo approach.
- `mellamomax/ica_shopping`, `Jrubensson/ica_shopping` — other HA ICA list
  integrations (one fork adds voice control). Reference only.
- ESPHome references: SmartHome-yourself `barcode.yaml`,
  `MattFryer/HA-Mealie-Barcode-Scanner` — how the device calls a HA service with
  the scanned code. Reference only (device side, out of scope).

## 3. Constraints

- **Swedish egress IP required** — ICA's API gateway (`apimgw-pub.ica.se`) blocks
  non-Swedish IPs. The user's Home Assistant runs from a Swedish IP (confirmed OK).
- **Account type** — must be an ICA account that supports password login (not
  BankID-only).
- **HACS packaging model** — only `custom_components/ica/` is shipped to users;
  dev tooling (uv/ruff/mypy/pytest/pre-commit) is repo-local. Runtime deps, if
  any, are declared in `manifest.json` → `requirements`; target is **zero**
  external runtime deps (use HA-provided `aiohttp` + stdlib `hashlib`, `secrets`,
  `base64`, `json`).
- Access tokens are short-lived (~15 min) with a long-lived refresh token; must be
  auto-refreshed and cached in HA storage (not plaintext config).

## 4. Architecture

Single integration, **domain: `ica`** (short; yields entity IDs like
`todo.ica_inkopslista`). Layered so each unit has one purpose and is testable in
isolation.

| Layer | File(s) | Responsibility | Depends on HA? |
|---|---|---|---|
| **API client** | `custom_components/ica/api/` | ICA auth (DCR + PKCE + personnummer/password), token cache/refresh, typed endpoint methods | **No** (pure Python + aiohttp) |
| **Coordinator** | `coordinator.py` | Poll configured list on interval, hold current list state in memory, refresh on demand after writes | Yes |
| **Config flow** | `config_flow.py` | Setup (credentials → authenticate → pick default list), reauth on 401, options (poll interval) | Yes |
| **Services** | `services.py`, `services.yaml` | Phase 1 deliverable (three services) | Yes |
| **Todo platform** | `todo.py` | Phase 2 — `TodoListEntity` per ICA list | Yes |
| **Wiring** | `__init__.py`, `manifest.json`, `const.py` | Setup/unload, config-entry lifecycle, constants | Yes |

**Why the API client has no HA imports:** it lets us unit-test the entire ICA
protocol with mocked HTTP and no running Home Assistant, keeps auth logic in one
focused place, and leaves the door open to extracting a PyPI package later without
committing to that overhead now.

### 4.1 API client (`api/`)

Public surface (all `async`):

- `async login(personnummer, password) -> Session` — full DCR + PKCE + credential
  flow; returns/persists tokens.
- `async ensure_token()` — refresh if expired.
- `get_product(ean) -> Product | None` — EAN/GTIN lookup; `None` if unknown.
- `get_lists() -> list[ShoppingList]`
- `get_list(list_id) -> ShoppingList` (items included)
- `add_item(list_id, text) -> Item`
- `remove_item(list_id, item_id) -> None`
- `set_checked(list_id, item_id, checked: bool) -> None`

Typed models (`dataclass`/`TypedDict`): `Product`, `ShoppingList`, `Item`. Custom
exception types: `IcaAuthError`, `IcaConnectionError`, `IcaGatewayBlockedError`
(non-Swedish IP), `IcaError` (base). Token cache injected via a small storage
callback so the client stays HA-free but HA can persist via its Store helper.

### 4.2 Coordinator

`DataUpdateCoordinator[ShoppingListState]` polling the configured default list
every N minutes (default 5, configurable). Holds the current list in memory so:

- the "merge, no count" dedupe check reads from memory, not a fresh HTTP call per
  scan;
- the todo entity and services share one source of truth;
- after any write (service or todo edit) we call `async_request_refresh()` for an
  immediate UI update instead of waiting for the next poll.

## 5. Phase 1 — Services (primary deliverable)

Three services, all declared with **`SupportsResponse.OPTIONAL`** so the ESP32 can
receive structured feedback to drive its display/buzzer.

### `ica.lookup_product`
- **In:** `barcode` (string, EAN/GTIN).
- **Does:** product lookup only; no list mutation.
- **Returns:** `{ found: bool, name: str | None, ean: str, brand: str | None }`.

### `ica.add_item`
- **In:** `name` (string, Swedish item text), `list` (optional; default list if omitted).
- **Does:** dedupe against current list (merge, no count); add only if not present.
- **Returns:** `{ added: bool, name: str }` (`added=false` when it was a duplicate).

### `ica.scan_barcode` (combined — the path the scanner uses)
- **In:** `barcode` (string), `list` (optional).
- **Does:** `lookup_product` → if found, add product name (deduped); if **not
  found**, add the raw EAN flagged, e.g. `"Okänd vara <ean>"`.
- **Returns:** `{ found: bool, added: bool, name: str, ean: str }` so the device
  shows the product name + ✓, or a "not found" warning for a miss.

### Scanner data flow

```
ESP32 reads EAN
  -> ESPHome fires HA service `ica.scan_barcode` (direct call or via automation)
    -> API client get_product(ean)
      -> coordinator in-memory list -> dedupe check (merge, no count)
        -> add_item if new (found name, or raw "Okänd vara <ean>" if miss)
          -> service returns response {found, added, name, ean}
            -> device shows name + ✓ or "not found" warning
    -> coordinator.async_request_refresh() so HA reflects the change immediately
```

## 6. Phase 2 — Shopping list in Home Assistant

Implement `TodoListEntity` for the configured ICA list (at least the default;
optionally one entity per list). This single choice provides:

- Native HA **To-do / Shopping List** Lovelace card: add / remove / check-off
  (bidirectional editing).
- **Voice control for free** via Assist's built-in to-do intents (satisfies the
  future voice-control use-case with no extra code).
- Consistent **"merge, no count"** behavior for UI/voice adds (reuses service logic).

**Sync:** coordinator polling (default 5 min, configurable via options) since ICA
provides no push/webhook; plus immediate `async_request_refresh()` after any
HA-side write for a snappy UI.

## 7. Behavior decisions (resolved)

- **Lookup miss:** never dropped — add raw EAN flagged (`Okänd vara <ean>`) and set
  `found=false` in the response so the device can warn. *(not an error)*
- **Duplicate scans:** merge, no count — dedupe by product name; add once if new.
- **Device feedback:** services return structured response data
  (`SupportsResponse.OPTIONAL`).
- **Language:** code, comments, and UI/service descriptions in **English**; shopping
  list item text kept in **Swedish** (as returned by ICA / raw EAN label).

## 8. Configuration & options

- **Config flow (setup):** personnummer + password → authenticate → select default
  shopping list from fetched lists. Tokens stored via HA `Store` (not plaintext).
- **Reauth flow:** triggered on hard 401 → prompt for password again.
- **Options flow:** poll interval (default 5 min); optionally which list(s) are
  exposed as todo entities.
- **Repair issue** raised (with clear text) if the gateway blocks the request
  (likely non-Swedish IP) so failures are diagnosable.

## 9. Error handling

- **Auth:** silent refresh via refresh token; hard 401 → HA reauth flow.
- **Gateway block / non-Swedish IP:** `IcaGatewayBlockedError` → HA repair issue.
- **Lookup miss:** handled as a normal outcome (raw-EAN path), not an exception.
- **Network / API errors:** services raise `HomeAssistantError` with actionable
  messages; coordinator marks entities unavailable and retries on the next poll.

## 10. Project layout & tooling

Repo is dual-natured: a `uv`-managed Python dev project at the root wrapping a
HA-conventional integration package.

```
barcode-ica-shopping-list/
├── custom_components/
│   └── ica/
│       ├── __init__.py
│       ├── manifest.json          # domain, version, requirements (target: [])
│       ├── const.py
│       ├── config_flow.py
│       ├── coordinator.py
│       ├── services.py
│       ├── services.yaml
│       ├── todo.py                # phase 2
│       ├── strings.json           # + translations/en.json
│       └── api/                   # HA-free ICA client
│           ├── __init__.py
│           ├── auth.py
│           ├── client.py
│           └── models.py
├── tests/                         # pytest, mirrors package layout
├── docs/superpowers/specs/        # this document
├── hacs.json                      # HACS repo metadata
├── pyproject.toml                 # uv-managed dev deps, ruff & mypy config
├── uv.lock
├── .pre-commit-config.yaml
├── .github/workflows/             # CI: ruff, mypy, pytest, hassfest/HACS validate
└── README.md
```

**Tooling stack:**

- **uv** — dev dependency management + virtualenv (`pyproject.toml` + `uv.lock`).
  Dev-only; not shipped to users.
- **ruff** — lint **and** format (replaces black/flake8/isort).
- **mypy** — static typing; aim for strict on `custom_components/ica` (relaxing
  only where HA typing forces it).
- **pytest** — unit tests, with **`pytest-homeassistant-custom-component`** for
  the HA-aware tests (config flow, services, coordinator, todo entity).
- **pre-commit** (pre-commit.com) — runs ruff (lint + format), mypy, and
  fast checks on commit; the same checks plus pytest run in CI.
- **CI (GitHub Actions):** ruff, mypy, pytest, and HA's `hassfest` + HACS
  validation actions to keep the integration installable/valid.

## 11. Testing strategy

- **API client:** unit-tested in isolation with mocked HTTP (`aioresponses` or
  `respx`) — no real credentials, runnable in CI. Cover the auth flow steps, token
  refresh, product found/not-found, and each list operation.
- **Config flow / services / coordinator / todo:** tested via
  `pytest-homeassistant-custom-component` against a mocked API client — assert the
  three service contracts (incl. dedupe and raw-EAN miss path), reauth, and todo
  add/remove/check.
- **Coverage goal:** all non-trivial logic unit-tested (user requirement:
  "unit tests of all code").
- **Manual smoke test:** one real end-to-end run from the user's Swedish IP with a
  real ICA account (cannot be automated in CI).

## 12. Scope & phasing

- This spec covers the **whole architecture** so phase 1 does not box in phase 2.
- **Implementation plan #1 → Phase 1:** repo/tooling scaffold (uv, ruff, mypy,
  pytest, pre-commit, CI, HACS metadata) + API client (auth + `get_product` +
  list add/read) + config flow + the three services + tests.
- **Implementation plan #2 → Phase 2:** `TodoListEntity` + full list operations
  (remove/check) + options for exposed lists + tests.

## 13. To confirm during review

1. **Domain name** — `ica` (proposed) vs `ica_shopping`. Easily changed now,
   costly later. *(no strong objection raised; defaulting to `ica`.)*
2. Whether phase 2 exposes **only the default list** or **one todo entity per
   list** (defaulting to: default list first, multi-list as an option).
