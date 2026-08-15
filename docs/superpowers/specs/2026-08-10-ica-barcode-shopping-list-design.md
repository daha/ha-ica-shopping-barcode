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

- **Target API (confirmed):** the **ICA.se web** shopping-list service at
  `https://apimgw-pub.ica.se/sverige/digx/shopping-list/v1/api/...` (read endpoint
  `GET .../list/all`). This is a *different service on the same gateway* as
  ica-mcp's mobile service (`.../digx/mobile/shoppinglistservice/v1/...`); it
  returns richer rows with nested `article.group` / `article.extendedGroup`
  category data, which is what we want. Same Bearer token / gateway, so the auth
  flow below is unchanged. Product lookup still uses the product service
  (`.../digx/mobile/productservice/v1/product/{ean}`).
- `kanylbullen/ica-mcp` — Python MCP server; has `get_product` (EAN lookup),
  `add_product_to_shopping_list`, list add/check/uncheck/remove. Source of the
  **auth flow** and the **product-lookup** approach (its *mobile* shopping-list
  endpoints/shape are NOT what we use — see target API above). Auth itself was
  ported from `ha-ica-todo`.
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

Targets the **web shopping-list API** (`.../digx/shopping-list/v1/api/...`) for
list operations and the **product service** for EAN lookup. Public surface (all
`async`):

- `async login(personnummer, password) -> Session` — full DCR + PKCE + credential
  flow; returns/persists tokens.
- `async ensure_token()` — refresh if expired.
- `get_product(ean) -> Product | None` — EAN lookup; `None` if unknown. `Product`
  **retains the full raw payload** (`raw`) plus convenience fields (name, ean,
  article ids, group ids). Nothing is discarded. *(The exact lookup endpoint —
  product-service vs the article search by EAN — is being confirmed against a real
  response; `Product.from_api` accepts either shape.)*
- `get_lists() -> list[ShoppingList]` — `GET .../list/all` (returns lists with rows).
- `add_item(list_id, text, article=None) -> Item` — `POST .../list/{id}/row`. For a
  scanned product, `article = Product.to_row_article()` passes the **entire** lookup
  object through (store-format categories, group names, ids), so ICA sorts the row
  correctly in any store format; free-text adds omit `article` and ICA classifies
  server-side.
- `remove_item(list_id, row_id) -> None` — Phase 2; `DELETE .../row/{id}`.
- `set_checked(list_id, row_id, checked) -> None` — Phase 2; `PUT .../row/{id}` (full row).

**Data model (web dialect, from the real response):** a list is
`{id (GUID), name, comment, sortingStore, rows[], shoppingListId (int),
householdId, secureId}`; a row is `{id (GUID), text, isStriked (bool),
order, quantity: {amount, unit} | null, article: {id, name, ean,
group: {id, name}, extendedGroup: {id, name}}, shoppingListRowId (int)}`.
Category *names* arrive `null` in the list payload; we do **not** resolve them
(see §7 — "correct in the ICA app" only).

Typed models (`dataclass`/`TypedDict`): `Product`, `ShoppingList`, `Item`
(+ nested `Article`/`ArticleGroup`). Custom
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
- **Returns:** `{ found: bool, name: str | None, ean: str }`. *(No `brand` — the
  product response exposes no reliable brand field; see plan executor notes.)*

### `ica.add_item`
- **In:** `name` (string, Swedish item text), `list` (optional; default list if omitted).
- **Does:** dedupe against current list (merge, no count); add only if not present.
- **Returns:** `{ added: bool, name: str }` (`added=false` when it was a duplicate).

### `ica.scan_barcode` (combined — the path the scanner uses)
- **In:** `barcode` (string), `list` (optional).
- **Does:** `lookup_product` → if found, add the product name (deduped) **with its
  article group id(s) attached** so ICA files it in the correct category; if **not
  found**, add the raw EAN flagged, e.g. `"Okänd vara <ean>"` (no article; ICA's
  server-side text matching may still classify it).
- **Returns:** `{ found: bool, added: bool, name: str, ean: str }` so the device
  shows the product name + ✓, or a "not found" warning for a miss.

### Scanner data flow

```
ESP32 reads EAN
  -> ESPHome fires HA service `ica.scan_barcode` (direct call or via automation)
    -> API client get_product(ean)  # -> name + article_id + article_group_id(s)
      -> coordinator in-memory list -> dedupe check (merge, no count)
        -> add_item if new: found -> name + attached article group; miss -> "Okänd vara <ean>"
          -> service returns response {found, added, name, ean}
            -> device shows name + ✓ or "not found" warning
    -> coordinator.async_request_refresh() so HA reflects the change immediately
```

## 6. Phase 2 — Shopping list in Home Assistant

Implement `TodoListEntity` for the configured ICA list. This single choice
provides:

- Native HA **To-do / Shopping List** Lovelace card: add / remove / check-off /
  rename (bidirectional editing).
- **Voice control for free** via Assist's built-in to-do intents (satisfies the
  future voice-control use-case with no extra code).

**Design (settled 2026-08-15, before implementation):**

- **Platform** `custom_components/ica/todo.py`; `PLATFORMS = [Platform.TODO]`.
  One entity for the configured list, named from `CONF_LIST_TITLE`
  (e.g. `todo.ica_att_handla`). Supported features: `CREATE | DELETE | UPDATE`.
  **MOVE is not supported** — reordering would mean managing ICA's `order`
  field across rows, which a mostly-append shopping list does not justify.
- **Full-row preservation (critical).** ICA's update endpoint takes the *entire*
  row back, so `ShoppingListItem` keeps `raw` (exactly as `Product` does) and
  exposes `to_updated_row(*, text=None, is_checked=None)` →
  `{**raw, "text": …, "isStriked": …}`. Overriding only what changed keeps
  `article` (and therefore the item's category), `order`, `quantity`,
  `created`, `shoppingListRowId` intact. Sending only our parsed fields would
  strip them.
- **Client:** `update_item(item, *, text=None, is_checked=None)` →
  `PUT {SHOPPING_LIST_BASE}/row/{id}` (full-row body);
  `remove_item(item_id)` → `DELETE {SHOPPING_LIST_BASE}/row/{id}` (no body).
- **UI/voice adds are NOT deduped** — they always add, like every other HA to-do
  list, because in a card you can see the list and a silent no-op is confusing.
  *This supersedes the earlier "consistent merge, no count for UI adds".* The
  scanner services keep their merge-no-count dedupe: a scanner has no display,
  so silently skipping a duplicate is the desirable behavior there.
- **Errors:** `_map_ica_errors` moves out of `services.py` into a shared module
  so the entity inherits identical handling (auth → reauth, gateway 403 →
  repair issue, otherwise `HomeAssistantError`). No behavior change.

**Sync:** coordinator polling (default 5 min, configurable via options) since ICA
provides no push/webhook; plus immediate `async_request_refresh()` after any
HA-side write for a snappy UI. The card therefore acts on the last poll — a
check-off can race a change made in the ICA app; the write is authoritative and
the follow-up refresh reconciles. (Service *adds* avoid this entirely by reading
the list fresh — see §14 and the dedupe-staleness fix.)

## 7. Behavior decisions (resolved)

- **Lookup miss:** never dropped — add raw EAN flagged (`Okänd vara <ean>`) and set
  `found=false` in the response so the device can warn. *(not an error)*
- **Duplicate scans:** merge, no count — dedupe by product name; add once if new.
- **Article groups / categories:** on a *found* scan, attach the product's article
  group id(s) (`article.group.id` / `article.extendedGroup.id`, from the product
  lookup) to the new row so the item lands in the correct ICA category. Category
  **names are NOT surfaced in Home Assistant** — "correct in the ICA app" is the
  goal; we do not fetch/cache the article-group name reference.
- **Device feedback:** services return structured response data
  (`SupportsResponse.OPTIONAL`).
- **Language / i18n:** code and comments in **English**. The **UI is fully
  translatable** via HA's translation system, shipping **English** (`strings.json`
  + `translations/en.json`, the source of truth) and **Swedish**
  (`translations/sv.json`). Translations cover config/options/reauth steps, error &
  abort messages, repair issues, service names/descriptions/fields, and entity
  names. Shopping-list **item text is data**, kept in **Swedish** as returned by
  ICA (or the raw-EAN label), independent of the chosen UI language. New languages
  are added by dropping in another `translations/<lang>.json`.

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
ha-ica-shopping-barcode/
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
│       ├── strings.json           # English UI source of truth
│       ├── translations/
│       │   ├── en.json            # English (mirrors strings.json)
│       │   └── sv.json            # Swedish
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
  validation actions to keep the integration installable/valid. `hassfest` also
  validates the translation files (missing keys / malformed JSON).

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
  list add/read) + config flow + the three services + `strings.json` and
  `translations/{en,sv}.json` for the phase-1 UI surface + tests.
- **Implementation plan #2 → Phase 2:** `ShoppingListItem.raw` + the row
  update/delete client methods + shared error mapping + `TodoListEntity`
  (create/delete/check/rename) + tests. No new translation keys are expected —
  the entity is named from the list title and reuses the existing `exceptions`
  block. *(No "options for exposed lists": the manifest declares
  `single_config_entry`, so there is exactly one list per install.)*

## 13. Decisions resolved during review

1. **Domain name — `ica`.** Chosen for clean names (`ica.scan_barcode`,
   `todo.ica_<listname>`). Accepted minor risk of colliding with a hypothetical
   future official `ica` core integration.
2. **Phase 2 scope — default list only, first.** Expose a single `TodoListEntity`
   for the configured default list initially; one-entity-per-list remains a
   possible later enhancement, not part of the planned phases.
3. **UI languages — English (source) + Swedish.** Item text stays Swedish (data).

## 14. Addendum — product category in service responses (2026-08-15)

Driver: the ESPHome device displays **EAN, name, and category**, so the category
must come back in clear text from the services.

**Confirmed reference endpoint** (verified against the live account):
`GET {API_BASE}/sverige/digx/mobile/shoppinglistservice/v1/articles/articlegroups?lastsyncdate=2001-01-01`
→ `200 {"articleGroups": [{"id": 3, "name": "Bröd, kex och bageri", "parentId": 1,
"lastSyncDate": "2015-09-18T08:45:55"}, …]}` — note the **lowercase** keys and the
`articleGroups` envelope. It returns **10 coarse groups**, all `parentId: 1`.
Confirmed: 4 = Frukt & Grönt, 5 = Djupfryst, 6 = Färskvaror, 9 = Skafferivaror,
10 = Mejeri, 11 = Hem & Fritid, 12 = Ospecificerad.

**Key finding:** the *expanded* group ids seen on rows and in product lookups
(13, 18, 19, 21, 27, 32) are **not** in this table — it holds only the coarse
taxonomy. Expanded names exist in the article-search payload, but that endpoint
matches fuzzily by name and is deliberately not used here.

**Decisions:**
- `category` resolves from the product's coarse `articleGroupId` only. No
  expanded-id fallback chain, because it could never fire.
- `category` is `null` when the product is not found, the id is unknown, or the
  reference table is unavailable — never the literal `"Ospecificerad"`, which is
  a real group ICA itself assigns and must stay distinguishable.
- The table is static (rows stamped 2015): fetched **once per HA restart**,
  cached on the `IcaClient` instance. A failed fetch degrades to an empty map; a
  category lookup must never fail a scan.
- Responses: `lookup_product → {found, name, ean, category}`,
  `scan_barcode → {found, added, name, ean, category}`. `add_item` is unchanged
  (free text, no product to categorise).

## 15. Addendum — `ica.refresh_list` service (2026-08-15)

Driver: force the locally synced list up to date on demand, without waiting for
the poll interval.

**Why not `homeassistant.update_entity`:** it exists and targets the to-do
entity, but `CoordinatorEntity.async_update` calls `async_request_refresh()`,
which is **debounced** (a burst inside the cooldown collapses) and returns
nothing — so it cannot report whether the refresh actually happened.

**Decisions:**
- New service **`ica.refresh_list`**, no parameters (`single_config_entry`
  means exactly one list), `SupportsResponse.OPTIONAL` like the others.
- Refresh via `coordinator.async_refresh()` — the **immediate** variant, not
  the debounced `async_request_refresh()`. Routing through the coordinator
  reuses `_async_update_data`, so the `gateway_blocked` repair issue is still
  created/cleared and an auth failure still triggers reauth (the latter works
  because the coordinator is constructed with `config_entry=`).
- **`async_refresh()` swallows failures** — it logs and sets
  `last_update_success = False`. A force-refresh that silently does nothing is
  precisely the problem being solved, so the service checks that flag and
  raises a translated `HomeAssistantError` (`refresh_failed`, carrying the
  coordinator's last exception).
- Response: `{list, items, unchecked}` — the list name, its total row count,
  and how many are still unbought — enough to see at a glance whether the local
  copy is current.
