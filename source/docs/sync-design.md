# Desktop → Mobile Sync: Interchange Format and Transport

Date: 2026-07-21
Status: decided (v1). Implemented by #31 (desktop export), consumed by #32/#34 (iOS).

## Summary

- **Format**: a versioned, *compiled* bundle — `txt_xpander_bundle.json` — not a copy of `snippets.json`. Mapping containers are expanded to concrete triggers, static snippet references are resolved, rich text is flattened to plain text plus optional HTML, and the dynamic registry ships as metadata only.
- **Transport**: the desktop writes the bundle into a **user-owned cloud folder** (iCloud Drive for Windows, Google Drive, Dropbox, Syncthing — any local path). iOS reads it through the document picker and a security-scoped bookmark. No server, no new dependency, no account.
- **Conflicts**: none by construction. Desktop is the source of truth; the bundle is a full snapshot; mobile is read-only and replaces wholesale. Two-way sync is explicitly v2.
- **Privacy**: the bundle is plaintext personal data (CPFs, CNPJs, addresses, phones) sitting in a folder a cloud provider can read. That exposure is real and is documented, not waved away. Encryption at rest is a named v2 door.

Everything below is the detail those four decisions need in order to be implemented without a second design pass.

---

## 1. Interchange format

### 1.1 Why compiled, not raw

`snippets.json` is a desktop *runtime* structure. Handing it to iOS would force the phone to reimplement, and keep in step with, four pieces of desktop semantics:

| Desktop semantics | Lives in | If iOS reimplemented it |
| --- | --- | --- |
| Mapping containers → composed triggers (`_cpf_numbers` + `fulano` → `cpffulano`) | `snippet_utils.get_dynamic_prefixes`, `check_dynamic_pattern` | Two implementations of the `__prefix__` / `_*_numbers` / `_*_codes` naming rules, including their collision quirks |
| Static ∪ dynamic merge and precedence | `snippet_utils.merge_snippets` | Silent divergence when precedence changes |
| Rich-text payload shape | `rich_text_support` (`__kind__`, `spans`, `html`, `rtf`) | A Swift span/RTF renderer for no user-visible gain |
| `%%variable%%` resolution | `variable_support` | A Swift resolver with no clipboard and no dialogs to resolve *with* |

Compiling on the desktop keeps all of it in one language, in the code that already owns it. The phone's job shrinks to "decode a list and insert a string".

### 1.2 What the bundle is *not*

The bundle carries the trigger **vocabulary** — every snippet the desktop can expand, keyed by the text the user would type. It deliberately does **not** model the desktop's *matching* behaviour:

`trigger_index.find_direct_trigger` matches the **longest direct trigger that is a suffix of the typed buffer**, and `find_dynamic_trigger` only runs when no direct trigger matched (`txt_xpander.pyw:1247-1253`). So a desktop trigger can be unreachable by typing, via two distinct mechanisms:

- **Direct vs direct.** X is unreachable when another direct trigger Y is a suffix of a *proper prefix* of X, because Y fires mid-word before X is finished — a static `abc` makes `xabcz` unreachable, since `"xabc".endswith("abc")` matches at the `c` keystroke. (A trigger that is merely a suffix of a longer one is *not* affected: the longest-first bucket sort at `trigger_index.py:56` exists precisely to keep both reachable.)
- **Direct vs mapping-composed.** A composed trigger is unreachable when *any* direct trigger is a suffix of it — including a suffix of the whole string — because `find_direct_trigger` runs at every keystroke and `find_dynamic_trigger` is consulted only on a miss. A static `ano` therefore makes the composed `cpffulano` unreachable.

Unreachable triggers still appear in the bundle.

That is correct, because **the phone is a picker, not a matcher**: v1 is a snippet-picker keyboard (#32), the user taps a row, and no suffix matching happens. Shadowed triggers are a desktop discoverability problem worth its own issue; they are not a sync problem, and modelling them here would couple the export to keyboard internals for no benefit.

### 1.3 File identity

- **Name**: `txt_xpander_bundle.json`, fixed. The version lives *inside* the file, never in the filename — an iOS security-scoped bookmark points at a specific file, and renaming on a schema bump would silently break every phone that already picked the old name.
- **Location**: `<sync_export_dir>/txt_xpander_bundle.json`, where `sync_export_dir` is the new optional `settings.json` key introduced by #31. Absent key = feature off.
- **Encoding**: written with `snippet_utils.write_json_atomic` — UTF-8, `ensure_ascii=False`, `indent=2`, same-directory temp + `os.replace`. The file is user-inspectable by design and its size doesn't justify minification. JSON line endings are platform-native (`write_json_atomic` opens in text mode); string contents are unaffected, since `json.dump` escapes embedded newlines.

### 1.4 Top-level shape

```json
{
  "schema_version": 1,
  "exported_at": "2026-07-21T13:45:02Z",
  "generator": {"name": "txt_xpander", "version": "3.2.0", "platform": "win32"},
  "entries": [ ... ],
  "dynamic": [ ... ]
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema_version` | integer | yes | Starts at `1`. Bumped **only** for changes a v1 consumer cannot survive. |
| `exported_at` | string | yes | UTC ISO-8601, `Z` suffix, second resolution. **Content-change time**, not write time — see §1.11's skip-if-unchanged rule. Display only; it is never a sync cursor (§3). |
| `generator.name` | string | yes | Always `"txt_xpander"`. Lets a future importer distinguish sources. |
| `generator.version` | string \| null | yes | Desktop app version, for support and bug reports. See §5.1 — no importable constant exists today, so `null` is legal and #31 is not blocked on introducing one. |
| `generator.platform` | string | yes | `sys.platform`. Diagnostics only. |
| `entries` | array | yes | Insertable snippets. May be empty, never `null`. |
| `dynamic` | array | yes | Registry metadata. May be empty, never `null`. |

**`generator.version` is the only field in this schema that may be JSON `null`.** Every other field is either present with a non-null value or absent entirely. iOS models everything else as non-optional except the fields marked "Required: no".

**Compatibility contract** — both sides honour it, and both #31 and #34 test it:

1. Consumers reject a bundle whose `schema_version` is **greater** than the version they know, with an actionable message, and keep their previous good copy.
2. Consumers **ignore unknown fields**. Swift `Codable` does this by default; do not add strictness that breaks it.
3. Consumers **tolerate unknown enum values**. Every string field with a closed value set here (`kind`, `source`, `provider`, `category`, `render.kind`) decodes to an `unknown` case rather than throwing. Without this, adding one `provider` value to the desktop bricks every phone — a plain `enum: String, Decodable` throws on an unrecognised value and takes the whole bundle down with it.
4. Therefore additive changes — a new optional field, a new enum value — ship **without** a version bump. Removing a field, renaming one, or changing a field's meaning requires one.

**`schema_version` validation, exhaustively** (rule 1 alone covers one of six cases):

| Value | Consumer behaviour | Message class |
| --- | --- | --- |
| `1` | accept | — |
| integer > known | reject, keep previous copy | "update the iOS app" |
| `0` or negative | reject, keep previous copy | "invalid bundle" |
| absent | reject, keep previous copy | "invalid bundle" |
| `null`, string, float, any non-integer | reject, keep previous copy | "invalid bundle" |

The split matters: "update the iOS app" is only truthful for the forward-version case. Everything else is a corrupt or foreign file and must say so.

### 1.5 `entries[]` — the insertable snippets

```json
{
  "trigger": "cpffulano",
  "text": "123.456.789-00",
  "kind": "text",
  "source": "mapping",
  "group": {"container": "_cpf_numbers", "prefix": "cpf", "item": "fulano"}
}
```

```json
{
  "trigger": "xassinatura",
  "text": "Project Contributors\nDiretor",
  "html": "<div>Project Contributors<br><b>Diretor</b></div>",
  "kind": "rich_text",
  "source": "static"
}
```

```json
{
  "trigger": "xproposta",
  "text": "Prezado %%cliente%%, cotação de hoje: %%xdolar%%.",
  "kind": "text",
  "source": "static",
  "input": {"clipboard": false, "fields": ["cliente"], "dynamic_refs": ["xdolar"], "residual": []}
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `trigger` | string | yes | What the user types on the desktop. **Unique across `entries` and `dynamic`** — producer obligation, §1.7. |
| `text` | string | yes | Plain text to insert, after export-time resolution (§1.6). |
| `html` | string | no | Present only when `kind == "rich_text"`, the stored payload has non-empty `html`, **and** the raw value contained no variable tokens (§1.6). |
| `kind` | `"text"` \| `"rich_text"` | yes | Explicit rather than inferred from `html`'s presence, because `html` is now suppressed in a case where the value is still rich text. |
| `source` | `"static"` \| `"mapping"` | yes | Where the trigger came from. Drives grouping in the mobile library browser. |
| `group` | object | no | Present **iff** `source == "mapping"`. `container` is the raw key (`_cpf_numbers`), `prefix` the composed prefix (`cpf`), `item` the item name (`fulano`). Gives mobile a "CPFs" section without parsing key names. A consumer that sees `source == "mapping"` with no `group` treats the entry as `source: "static"` rather than failing. |
| `input` | object | no | Present **iff** the entry needs something the export could not supply (§1.6). Consumers derive *insertable = `input` absent*; there is no separate boolean to fall out of sync. |
| `input.clipboard` | boolean | yes (within `input`) | The raw value contained `%%clipboard-paste%%`. |
| `input.fields` | string[] | yes (within `input`) | Form-field names from the raw value, first-appearance order (`variable_support.find_variable_names` order). May be empty. |
| `input.dynamic_refs` | string[] | yes (within `input`) | Dynamic triggers referenced by the raw value. May be empty. |
| `input.residual` | string[] | yes (within `input`) | Names of tokens still present in the resolved `text` that none of the three lists above accounts for — see §1.6. May be empty. A list rather than a boolean because §1.5's tap-to-explain rule needs something to *say*: with `xa = "%%xb%%"`, `xb = "Olá %%xc%%"` and `xc` a static snippet, all three lists above are empty, and without these names the only honest message is "this snippet can't be used here" — the mystery that rule exists to prevent. (Note the neighbouring case resolves differently: had `xb` injected a *form* token, §1.6's step-3 re-scan would have put it in `fields`, not here.) |

**RTF and style spans are not exported.** The keyboard extension inserts via `textDocumentProxy.insertText`, which is plain text; `html` exists for the container app and a future share-sheet path. Spans and RTF stay desktop-only.

**Mapping values follow exactly the same rules as static values** — variable resolution, rich-text flattening, `kind`. A `source: "mapping"` entry with `kind: "rich_text"` or with an `input` block is legal.

**v1 mobile behaviour for entries with `input`**: show them in the library with a visible marker, allow search to match them, and make the row tappable so that tapping explains *why* it can't be inserted (missing field / needs the desktop). Do not insert. Without Full Access the extension has no clipboard and no dialog surface, so a partial insertion would paste literal `%%cliente%%` into a customer's message. Whether the **container app** later offers to fill the fields and hand the result to the pasteboard is left open — it has both affordances, and nothing here forecloses it.

### 1.6 Export-time resolution: what is baked, what is preserved

`variable_support.classify_variable` returns five kinds. The export treats them differently, and this split is what "compiled" means:

| Kind | Export behaviour | Why |
| --- | --- | --- |
| `snippet_ref` (`%%xname%%`) | **Resolved** | Deterministic and desktop-local: a plain lookup in data the bundle already contains. |
| `mapping_ref` (`%%cpffulano%%`) | **Resolved** | Same. |
| `clipboard` (`%%clipboard-paste%%`) | **Preserved as a token**, flagged in `input.clipboard` | Runtime state of the *desktop at export time*. Baking it would leak whatever was on the clipboard when the user pressed Save. A privacy rule, not a convenience one. |
| `dynamic_ref` (`%%xdolar%%`) | **Preserved as a token**, listed in `input.dynamic_refs` | Time-varying and network-backed. A baked dollar rate is a stale number that looks live — and resolving one would block the save path on a network call or open a ticker dialog. |
| `form_field` (`%%cliente%%`) | **Preserved as a token**, listed in `input.fields` | Needs the user, who is not present at export time. |

**Do not call `variable_support.resolve_inline`.** It cannot produce this behaviour, for two independent reasons, both verified against the code:

- `resolve_inline` line 91 is `value = get_clipboard() or ""`. A clipboard getter returning `None` therefore **deletes** `%%clipboard-paste%%` instead of preserving it — producing an entry with a silent hole and no `input` block, which mobile would then treat as insertable. That is strictly worse than the failure §1.5 exists to prevent.
- `classify_variable` decides `dynamic_ref` **solely** by `callable(snippets[name])` (`variable_support.py:45-51`). Passing a map with callables stripped reclassifies every dynamic reference as `form_field`, so `input.dynamic_refs` could never be populated at all.

#31 implements a dedicated resolver in `sync_export.py` that:

1. Builds a **classification map**: the static snippets, then — overwriting them, matching `merge_snippets`'s `{**static, **dynamic}` order — every registry entry in the **export accept set** (§1.8), keyed by effective trigger and mapped to a sentinel callable. Build it static-last and a name present in both reclassifies from `dynamic_ref` to `snippet_ref` and gets *baked*, silently breaking the rule above. `classify_variable` then returns the right kind for every name with no real callable in reach — so the export provably cannot invoke a provider, fetch from the network, or open a dialog.
2. Walks `find_variable_names(raw_text)` once, substituting **only** `snippet_ref` and `mapping_ref` (via `extract_plain_text`), and collecting the other three kinds into the `input` lists.
3. **Re-scans the resolved text** and classifies any name that was not in the raw list, merging the results into the same three lists.
4. Emits `input` when `clipboard` is true or any of `fields`, `dynamic_refs`, `residual` is non-empty.

Step 3 is not optional, and the reason is a genuine asymmetry in the runtime. Routing is decided from the **raw** value (`trigger_index._compute_form_triggers` classifies `extract_plain_text(value)`), but the form dialog's field list is built from the **resolved** text: `run_slow_snippet` calls `resolve_inline` and only then computes `form_names` (`txt_xpander.pyw:944-955`). So a form token injected by a one-level ref *is* prompted for on the desktop, and a raw-only scan would omit it from `input.fields`.

**`residual`** covers what step 3 cannot fix. Resolution is one level deep and non-recursive — `resolve_inline` computes its name list once and substitutes ref bodies verbatim (`variable_support.py:95-97`) — so a ref whose body contains `%%xc%%` injects that token and never chases it. The export stays one level deep too, faithfully, which means `text` can still contain a token. Formally — and the framing matters — **`residual` is every name in `names(resolved)` not already accounted for by `clipboard`, `fields` or `dynamic_refs`.** Define it by *survival*, not by *provenance*: an earlier draft defined it as `names(resolved) − names(raw)`, which silently excluded a token that was in the raw text and deliberately left unsubstituted (the unexportable-target case below). That entry would then carry no `input` block at all, and the phone would insert `Olá %%xbad%%` verbatim into a customer's message — exactly the outcome §1.5's non-insertable rule exists to prevent. The survival definition covers the injected-ref case, the unexportable-target case, and anything neither of us enumerated, with no enumeration at all.

On the desktop those injected refs are pasted literally (the fast path in `txt_xpander.pyw:889-903` resolves once and inserts). Mobile instead refuses the entry, because a non-empty `residual` forces an `input` block. That is the one place the two platforms deliberately differ, and refusing is the safer half.

**References to unexportable values are not resolved.** A `snippet_ref` or `mapping_ref` whose target is neither a string nor a valid rich-text payload is left as a token — which puts its name in `residual` by the survival rule above — rather than substituted — `extract_plain_text` would otherwise stringify a list or dict and inject a literal `"['a']"` into another entry's text.

**Rich text plus variables.** When a rich-text payload's raw text contains any variable token, `html` is **omitted** and only `text` is exported. Resolving into `text` while copying `html` verbatim would ship `text: "Olá, Example User"` next to `html: "<div>Olá, %%xname%%</div>"`; regenerating the HTML would mean re-deriving spans against a changed string. Dropping the HTML for that (rare) case costs formatting, not content, and never lies.

`html` is otherwise copied from the stored payload as-is. Note that app-generated payloads always have non-empty `html` and non-empty `spans` (`rich_text_support.build_rich_text_payload` returns a plain string when normalisation yields no spans), so the empty-`html` case only arises for hand-edited files.

**Values that are neither a string nor a valid rich-text payload** — `null`, numbers, lists, plain dicts without `__kind__`, all reachable in a hand-edited `snippets.json` — are **skipped with a logged warning**, not coerced. `extract_plain_text` would happily stringify them into `"None"` or `"{'a': 1}"` and ship that as insertable text. Check callables **first** and skip them silently (§1.7): they are also "neither", and warning on each would emit one line per dynamic snippet on every export.

### 1.7 Building the trigger set

**Inputs.** The export is a pure function — `build_bundle(static_snippets, registry, app_version=None, now=None)` — taking the static snippet dict and the raw dynamic registry as explicit arguments. `now` and `app_version` are injectable so tests can assert an exact `exported_at`.

It must **never** read `self.snippets`, for three reasons: `self.snippets` holds bound callables and no registry metadata; `save_snippets` is called from inside `load_snippets` (`txt_xpander.pyw:336`) **before** `self.snippets` is assigned, so touching it raises `AttributeError` on first run and on corrupt-file recovery; and after startup it can be *stale* — `restore_backup` and `import_library` write the file and only then call `reload_snippets_from_disk`, so a reader in between gets the pre-change library, which is a silent wrong-data bug rather than a loud one.

**Where the arguments come from, at every call site: re-read both files.** The thin wrapper `export_sync_bundle()` reads `validate_static_snippets(load_json_file(self.snippets_file))` **and** re-runs `load_registry(self.resolve_resource_path("dynamic_snippets.json"), self.dynamic_registry_file)` rather than reading `self.dynamic_registry`.

Re-reading the registry is not symmetry for its own sake. `_toggle_registry_entry` and `_rename_registry_entry` reassign `self.dynamic_registry` **after** their `write_json_atomic` (`txt_xpander.pyw:2670-2674` and `:2752-2756`), so a wrapper reading the attribute and hooked at or near the write would compile the **pre-toggle / pre-rename** registry — the bundle is written, the state hash advances, and the change never reaches the phone with no error anywhere. That is exactly the failure §1.10 exists to prevent. Re-reading makes the hook's placement within those methods irrelevant.

This is the only argument rule that works at all five sites in §1.10, and it is deliberately uniform:

- `_toggle_registry_entry` and `_rename_registry_entry` have no static dict in scope at all, and `self.snippets` is forbidden.
- `import_library` holds `merged = {**old, **imported}`, whose key order is *not* file order — passing it would violate the ordering rule below and make skip-if-unchanged fire spuriously.
- `save_snippets`'s own argument is `self.snippets` at every GUI call site, i.e. exactly the poisoned merged map; even its stripped `saveable` local has already lost any static key shadowed by a dynamic trigger.

The cost is one small read of a file the process just wrote (warm cache), and the benefit is that the bundle always compiles from the exact bytes on disk. A failed or invalid read logs a warning and skips the export — never raises into the save path.

**Expansion**, mirroring `get_dynamic_prefixes` / `check_dynamic_pattern`:

- Skip every key starting with `_` as a direct trigger (matches `compile_trigger_index`). Note this is *not* the same as "every `_` key is a container": a key like `_notes` is neither a container nor a trigger — `get_dynamic_prefixes` ignores it and `compile_trigger_index` skips it. It is unreachable data and the bundle drops it silently.
- **Iterate `get_dynamic_prefixes(static_snippets).items()`, not the snippet dict.** That map is keyed by *prefix*, so when two containers derive the same prefix the last one wins and the earlier container is genuinely unreachable at runtime — `check_dynamic_pattern` only ever consults this map. Iterating containers instead would emit triggers the desktop cannot fire, and could emit the same trigger twice. #31 reuses `get_dynamic_prefixes` rather than reimplementing the naming rules (`__prefix__`, else `key[1:]` with **every** occurrence of `_numbers`/`_codes` removed via `str.replace`; builtins `_cpf_numbers` → `cpf`, `_cnpj_numbers` → `cnpj`).
- For each resolved prefix, emit `prefix + item` for every item except `__prefix__`. An empty `__prefix__` is legal and yields the bare item name; the collision rule below handles the fallout.
- Skip callables defensively (`build_saveable_snippets` semantics) — runtime dynamic snippets never become `entries`.

**Precedence and collisions.** Precedence is evaluated over the **export accept set** — the registry entries `build_dynamic_snippets` would actually bind (§1.8), not merely the enabled ones. The reasoning generalises: an entry with `provider: "typo"` is enabled but binds no callable, so the desktop fires the static snippet of that name, and filtering on `enabled` alone would drop that static snippet from the bundle in favour of a trigger that does not exist. **One predicate, used in three places**: `dynamic[]`, this precedence contest, and §1.6's sentinel classification map. Order: accepted dynamic > static > mapping-composed. The bundle must never contain two entries with the same `trigger`; the loser is dropped with a logged warning.

The static-vs-dynamic case used to be nearly unreachable, for a reason worth recording: `merge_snippets` is `{**static, **dynamic}`, so a static snippet sharing a name with a dynamic trigger was overwritten in memory, and the next `save_snippets` — which writes `build_saveable_snippets(self.snippets)` — **deleted it from `snippets.json`**. That data-loss bug was fixed in #43: `find_shadowed_statics` records the shadowed values at load and `build_saveable_snippets(snippets, preserved)` writes them back, so the colliding static now survives on disk indefinitely. The export's dedupe is therefore **not** defensive — it is the normal path whenever a user has such a collision, and #31 reads the static dict directly from the file where both keys now live.

**Consumer rule for a duplicate `trigger`** — the producer obligation above is not a guarantee the phone can rely on: **first occurrence wins, later duplicates are dropped, and the bundle is still accepted.** The idiomatic Swift lookup (`Dictionary(uniqueKeysWithValues:)`) calls `fatalError` on a duplicate key, and if that lookup lives in the shared model target from #32 it takes down the *keyboard extension*, not just the app. A malformed bundle must never crash the keyboard.

**Ordering** is fully determined, so that identical data always produces an identical file: `entries` are static snippets in `snippets.json` key order, then mapping entries grouped by container in `get_dynamic_prefixes` iteration order with items in container order; `dynamic` follows registry order. Undefined ordering would rewrite the whole file on every save and make every test sort defensively.

### 1.8 `dynamic[]` — registry metadata

```json
{
  "id": "xhj",
  "trigger": "xhj",
  "provider": "datetime",
  "category": "datetime",
  "description": "Data de hoje (DD/MM/AAAA)",
  "enabled": true,
  "local": true,
  "render": {"kind": "date_format", "unicode_pattern": "dd/MM/yyyy", "locale": "pt-BR"}
}
```

```json
{
  "id": "xdolar",
  "trigger": "xdolar",
  "provider": "bcb",
  "category": "economy",
  "description": "Cotação do dólar (PTAX compra/venda)",
  "enabled": true,
  "local": false
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | The **stable registry key** — what the user override file is keyed by. Never the renamed trigger. |
| `trigger` | string | yes | `dynamic_registry.effective_trigger(key, entry)`. What the user types. |
| `provider` | string | yes | `datetime` \| `bcb` \| `stock` \| `whatsapp`. |
| `category` | string | yes | `entry.get("category", entry.get("provider", "other"))` — the same three-tier fallback as `reference_entries_by_category`, literal `"other"` included. |
| `description` | string | yes | `entry.get("description", "")`. Already PT-BR; not translated. |
| `enabled` | boolean | yes | Always `true` in v1 — see below. |
| `local` | boolean | yes | `true` iff mobile can produce the value offline, by itself. |
| `render` | object | no | Present iff `local == true`. Instructions for producing the value. |

**Which entries survive — the "export accept set".** `dynamic[]` mirrors `build_dynamic_snippets`'s accept/skip logic exactly, so the bundle can never advertise a trigger the desktop does not bind. Skipped: non-dict entries, disabled entries, unknown `provider`, unknown `method`/`mode` for the provider, and any entry whose effective trigger duplicates an earlier one (first wins). Each skip logs, none is fatal.

This set is computed **once per export** and is the single predicate behind three decisions: which rows appear in `dynamic[]`, which triggers win the precedence contest in §1.7, and which names get a sentinel callable in §1.6's classification map. Implement it as one function; three separate filters will drift.

**Disabled entries are excluded, and `enabled` is still emitted.** #30 asks for the field; #31 excludes disabled entries. Both: the bundle carries only enabled entries — a disabled trigger does not exist as far as the phone is concerned — and the field is written explicitly so the file is self-describing and a v2 that ships disabled entries needs no schema bump. Consumers must read the field, not assume it. *Consequence for #34*: its task-4 requirement to "hide disabled dynamic entries" is a no-op under this design — there are none in the bundle to hide.

**`local` and `render`.** Only `provider == "datetime"` is local in v1; `bcb`, `stock` and `whatsapp` need network, dialogs, a browser, or the desktop clipboard, none of which the extension has. Mobile lists non-local entries greyed with a "desktop only" hint — the issue's "knows what else exists".

There is exactly **one** `render.kind`: `date_format`. An earlier draft had a second `long_date` kind for `method == "extenso"`, which was wrong — `data_extenso` (`txt_xpander.pyw:567-580`) is hand-rolled with hardcoded PT-BR arrays and a **zero-padded** day (`{dia:02d}` → `segunda-feira, 02 de março de 2026`), and no `DateFormatter` style reproduces that (`.full` gives `2 de março`, unpadded). A second render kind would have guaranteed a desktop/phone mismatch. Both datetime paths therefore compile to a TR35 pattern:

| Registry entry | `unicode_pattern` |
| --- | --- |
| `method == "extenso"` | `EEEE, dd' de 'MMMM' de 'yyyy` (fixed) |
| otherwise | converted from `entry.get("format", "%d/%m/%Y")` — the provider's own default, so a thin user override with no `format` still exports |

`method == "extenso"` wins over any `format` key, matching `_datetime_provider`.

That pattern reproduces `data_extenso` component by component — weekday, comma, zero-padded day, both `de` literals, lowercase month — **verified against CLDR pt-BR as shipped with iOS 18, 2026-07-21**. Date the claim, because the two sides age differently: the desktop's arrays are a frozen Python literal (`txt_xpander.pyw:569-572`) while the phone's month and weekday names come from a locale database Apple revises. §5.2's test asserts the *pattern string* and can never catch a rendering drift, so #34 carries a **snapshot test** rendering a fixed date and comparing it to the desktop's expected output. Without it, this equivalence is a claim no test in either repo covers.

**strftime → Unicode TR35 conversion is a desktop responsibility.** The registry stores C `strftime`; iOS `DateFormatter` speaks TR35. Converting on the phone would put a second parser in a second language.

| strftime | TR35 | Notes |
| --- | --- | --- |
| `%Y` | `yyyy` | |
| `%y` | `yy` | |
| `%m` | `MM` | |
| `%d` | `dd` | |
| `%H` | `HH` | |
| `%I` | `hh` | |
| `%M` | `mm` | |
| `%S` | `ss` | |
| `%j` | `DDD` | |
| `%A` / `%a` | `EEEE` / `EEE` | locale-sensitive |
| `%B` / `%b` | `MMMM` / `MMM` | locale-sensitive |
| `%p` | `a` | locale-sensitive |
| `%%` | literal `%` | |

The name-based directives are supported because `load_registry` merges the user override **per field**, so a user can set `"format": "%A, %d de %B"` and would otherwise see a perfectly good date greyed out as "desktop only" on the phone.

**Literal-quoting rule, load-bearing and byte-exact**: split the format into directive tokens and literal runs; wrap **each entire literal run** — spaces included — in single quotes if it contains any ASCII letter, and double any literal `'` to `''`. TR35 reserves `A-Z a-z` as pattern letters, so the registry's `"%d/%m/%Y às %H:%M"` compiles to `dd/MM/yyyy' às 'HH:mm`. Leave `às` unquoted and the `s` renders as seconds. Wrapping the whole run (rather than only the letters) is the rule because it is unambiguous and gives one exact expected string per input, which is what §5.2's test asserts.

**Unknown directive**, non-string `format`, or a trailing lone `%`: fail loudly — omit `render`, set `local: false`, log a warning naming the entry and the offending directive. Never emit a half-converted pattern; a silently wrong date is worse than a missing one.

**Locale and timezone.** `render.locale` is always `"pt-BR"`, matching the app's UI language, and mobile must apply it — `MMMM` without a pinned locale renders in the phone's language. Mobile renders in the **phone's** local timezone, which is the analogue of the desktop's `time.localtime`; a phone in another timezone will legitimately show a different value. *Known limit*: for `%A`/`%B`/`%a`/`%b`/`%p` the desktop's own output depends on the process `LC_TIME` (Python's default is the C locale, i.e. English), so a user override using those directives can render English on the desktop and Portuguese on the phone. Not worth fixing until someone uses one — the upgrade trigger is the first bug report, and the fix is to set `LC_TIME` desktop-side rather than to change this schema.

### 1.9 Worked example

Given `snippets.json`:

```json
{
  "xname": "Project Contributors",
  "xsaudacao": "Olá, aqui é %%xname%%.",
  "_cpf_numbers": {"fulano": "123.456.789-00"},
  "_custom_codes": {"__prefix__": "cod", "nf": "NF-4471"}
}
```

and a registry containing only `xhj` (enabled) and `xdolar` (disabled by the user) — the real default registry has ~30 entries, which would all appear in `dynamic[]`:

```json
{
  "schema_version": 1,
  "exported_at": "2026-07-21T13:45:02Z",
  "generator": {"name": "txt_xpander", "version": "3.2.0", "platform": "win32"},
  "entries": [
    {"trigger": "xname", "text": "Project Contributors", "kind": "text", "source": "static"},
    {"trigger": "xsaudacao", "text": "Olá, aqui é Project Contributors.", "kind": "text", "source": "static"},
    {"trigger": "cpffulano", "text": "123.456.789-00", "kind": "text", "source": "mapping",
     "group": {"container": "_cpf_numbers", "prefix": "cpf", "item": "fulano"}},
    {"trigger": "codnf", "text": "NF-4471", "kind": "text", "source": "mapping",
     "group": {"container": "_custom_codes", "prefix": "cod", "item": "nf"}}
  ],
  "dynamic": [
    {"id": "xhj", "trigger": "xhj", "provider": "datetime", "category": "datetime",
     "description": "Data de hoje (DD/MM/AAAA)", "enabled": true, "local": true,
     "render": {"kind": "date_format", "unicode_pattern": "dd/MM/yyyy", "locale": "pt-BR"}}
  ]
}
```

`%%xname%%` was resolved, both containers expanded, `__prefix__` did not become a trigger, and the disabled `xdolar` is simply absent.

### 1.10 Where the export is triggered

**Five call sites, not two.** Every path that changes the live library must export, or the phone silently keeps stale data with no error anywhere:

| `txt_xpander.pyw` | Path | Currently mirrors? |
| --- | --- | --- |
| `save_snippets` (~:443) | manager edits | yes |
| `restore_backup` (~:512) | restore from backup | yes |
| `import_library` (~:548) | import / merge a library | yes |
| `_toggle_registry_entry` (write at :2664, registry reloaded :2670-2674) | enable/disable a dynamic entry | no |
| `_rename_registry_entry` (write at :2746, registry reloaded :2752-2756) | rename a dynamic trigger | no |

The rule for #31 is therefore: **every call site of `mirror_snippets_file()`, plus both registry writers.** `restore_backup` and `import_library` write the file directly (`shutil.copyfile`, `write_json_atomic`) and never pass through `save_snippets`. Hooking `reload_snippets_from_disk()` would cover four of the five in one place, but it also fires at startup on every launch, so prefer explicit calls.

Note that `save_snippets` can also fire at startup, from either of two mutually exclusive paths: `load_snippets` on first run (`:336`), or `recover_snippets_file` when the file is corrupt **and no valid backup exists** (`:386` — the recovery loop returns early on the first valid backup it finds). So the export can run before the user has touched anything. That is intended: with the feature on, the phone should receive a bundle without waiting for the first edit. It does mean a brand-new install publishes the seed library to the cloud folder; harmless, since the seed is anonymized, but worth knowing before it looks like a bug.

### 1.11 Write discipline

- **Skip-if-unchanged, via a local state file — never by reading the bundle back.** After each successful export, write `{"path": <absolute destination>, "sha256": <digest>}` to `~/.txt_xpander/sync_export.state`. The digest is over the serialised bundle with **`exported_at` and `generator` both excluded** — i.e. over `entries`, `dynamic` and `schema_version` only. Pin the exact bytes so a fixture author can reproduce them: `hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))`, with both keys **popped**, not blanked.
  Excluding `generator` is what keeps `exported_at` honest. Include it and every app upgrade rewrites every user's bundle with a fresh "library last changed" timestamp for a change that is not in the library. Excluded, an upgrade simply leaves the old `generator.version` in the file until the library next changes, which is exactly right: the field is diagnostic, not content.
  The next export skips the write only when **all three** hold: the digest matches, the recorded `path` matches the current destination, and `os.path.exists(<dest>/txt_xpander_bundle.json)`. All three are load-bearing. Without the existence check, deleting the bundle or repointing `sync_export_dir` at a fresh folder means it is **never written again** until the library happens to change — a silent dead end, and it would make §4.3 rule 3's guarantee false. Without the path check, switching the destination A → B → A leaves A holding a stale bundle. The existence check is a local `stat`, which a dehydrated placeholder answers from local metadata, so it does not reintroduce the read hazard this design exists to avoid. The obvious alternative — read the existing bundle and diff it — would read a file **inside the cloud folder on every save**, and OneDrive/Dropbox on-demand storage can dehydrate an infrequently-touched file to a placeholder, turning that read into a blocking network download on the GUI thread (the same hazard §2.3 flags for iOS). The state file lives in the data dir, which is not a sync target by default (`TXT_XPANDER_HOME` can point it anywhere, and `docs/audit-report.md` §1.4 records that it once lived inside OneDrive — the reason the default is now `~/.txt_xpander`). Losing the state file costs one unconditional export, nothing more. A missing or unreadable state file simply means "export unconditionally".
  This keeps `exported_at` meaningful — it becomes "when the library last actually changed", which is what §2.3 shows the user — and stops every save from pushing a full new revision through the cloud client. **One accepted limitation**: losing the state file (a cleared data dir, a fresh machine, a `TXT_XPANDER_HOME` change) forces one unconditional rewrite with a fresh `exported_at`, so the phone reports a change that did not happen. There is no prior timestamp left to reuse, and inventing one from the destination file would mean reading it — the exact thing this design exists to avoid. One spurious "library last changed" after a machine migration is the cheaper trade.
- **Do not create `sync_export_dir`.** Unlike `mirror_snippets_file`, which calls `os.makedirs(..., exist_ok=True)`, a missing export directory logs a warning and skips. A typo'd path under `makedirs` semantics silently creates a directory and writes the user's full plaintext CPF/CNPJ library into it — the directory already existing is the user's confirmation that they meant that path. Path handling is deliberately minimal: `os.path.expanduser` only (no environment-variable expansion), **relative paths are rejected with a warning** (the packaged app's cwd is not predictable, and an unpredictable destination is exactly what this rule exists to prevent), and a path that exists but is a file logs a warning and skips.
- **Temp file.** `write_json_atomic` creates its temp in the destination directory, which here is a synced folder — cloud clients will index, upload, and retain that temp file (§4.2). Same-directory is nonetheless required for `os.replace` atomicity, and atomicity for the phone wins. On `PermissionError` (documented in `docs/audit-report.md` §1.4 for OneDrive-style lock contention), retry **once after 0.5 s**, then warn and give up. **No orphan sweep**: `write_json_atomic` removes its own temp in its `except` branch (`snippet_utils.py:55-59`), so the only orphan sources left are that cleanup itself failing, or the process dying outright — a force-quit of the tray app, or power loss. Rare, and not worth the cure: a glob-and-delete loop in the user's cloud folder is unattended deletion of files this app cannot prove it owns.
- **Best-effort, always.** The export runs *after* the save succeeded, and any failure logs a warning and returns. It must never turn a persisted save into a reported failure.
- **Runs inline on the save path**, like `mirror_snippets_file`. `ceiling:` the whole inline sequence — compile, hash, `samefile` stat, temp write, `os.replace`, one 0.5 s retry — runs on the GUI save path, so a `sync_export_dir` on a disconnected UNC path or a stalled cloud client freezes the manager for as long as the filesystem blocks. This is more work than the mirror's single `copyfile`, so it is a real (if bounded) regression in that exposure, accepted because the state-file design keeps the common case to one stat and one hash. Move it to `BackgroundTaskRunner` on the first report of a freeze, or if the compile stops being cheap.
- Log a warning when the bundle exceeds ~5 MB (measured after build, before write): the phone-side ceiling (§5.3) is the first thing a very large library will break.

---

## 2. Transport v1

### 2.1 Options evaluated

| | (a) User-owned cloud folder | (b1) CloudKit from iOS | (b2) iCloud Drive folder | (c) Self-hosted endpoint | (d) One-shot manual import |
| --- | --- | --- | --- | --- | --- |
| Desktop (Windows) writes | a local path; `os.replace` | **impossible** — no Windows SDK; the web-services API needs the **paid** Developer Program | a local path (iCloud for Windows) — i.e. this *is* (a) | HTTP POST + auth + retry | a file the user sends by hand |
| iOS reads | document picker + bookmark | native, genuinely the nicest read path | document picker | URLSession + credentials | share sheet / "Open in" |
| New moving parts | none | Apple container config, key management, paid account | none | LAN-only: a listener + a token. Internet-facing: host, domain, certs, updates, backups | none |
| Works with Drive / Dropbox / Syncthing | yes | no | no | n/a | yes |
| Readable by a third party | **yes** — the cloud provider holds the keys (§4.2) | yes — Apple | yes — Apple | **no** in the LAN-only form; **yes** for a self-hosted VPS | **no** *via USB*; **yes** via email/messaging |
| Background refresh | **n/a in v1** — foreground only (§2.3) | would permit it | n/a in v1 | would permit it | n/a in v1 |
| Failure mode | stale file, placeholder-not-downloaded | auth expiry, container mismatch | same as (a) | listener down / not on the same LAN | user forgets to re-send |

**(d)'s delivery method matters, and only one of them earns that `no`.** The desktop is Windows, so **AirDrop is not available** — the Apple-only path that would be obvious on a Mac does not exist here. What does work Windows→iPhone by hand is **USB, via the Apple Devices app (formerly iTunes) File Sharing**, which touches no third party at all. Email-to-self or a messaging app also works and is far more tempting, and it puts the full plaintext library on a mail or messaging provider — flipping that cell to **yes** and defeating the reason a privacy-sensitive user chose (d). Any UI or documentation offering (d) must name the USB path specifically.

Also considered and not tabled: **SMB from the iOS Files app** (Windows shares natively, Files has had SMB since iOS 13 — same document-picker read path, no cloud, but requires both devices on the same LAN at read time and a share the user must configure); **iOS Shortcuts automation** to fetch the bundle on a schedule (a supplement to, not a replacement for, a chosen transport).

### 2.2 Decision: (a), a user-owned cloud folder

The desktop runs on **Windows**, and the sync is desktop→mobile, so the *writer* is the Windows app. That eliminates (b1): CloudKit gives Windows nothing, and the fallback web-services path requires the paid Developer Program while #32 explicitly scopes the project to "a free personal team is enough". (b2) is not a separate option at all — iCloud Drive for Windows is a synced folder, which is exactly what (a) supports, alongside Google Drive, Dropbox, OneDrive and Syncthing, with zero code difference.

(a) wins on the combination of *continuous* and *cheap*: `sync_export_dir` is a path, and the write is the atomic-replace discipline already in `snippet_utils.write_json_atomic`.

Honest accounting of what (a) costs, since §4 refuses to pretend otherwise: the file is readable by whichever cloud provider the user picked. (c) in its LAN-only form — the desktop serving the bundle on the local network behind a one-time token — and (d) over USB both score *better* on that row. (c) loses on surface area: a listener in the tray app, both devices on the same LAN at fetch time, and a token UX, which is real new machinery in a keyboard-hook app for a file that changes a few times a month.

**(a)'s advantage over (d) is smaller than "continuous vs manual" suggests, and the doc should not oversell it.** Two structural facts compress it. First, the keyboard only ever sees what the container app wrote, so a new desktop snippet reaches the keyboard when the container app runs and at no other time. Second, background refresh would not have closed that gap anyway: `BGAppRefreshTask` is scheduled from iOS usage heuristics, and this container app is opened *rarely* by design — the keyboard is the daily surface — so it might effectively never fire. §2.3 resolves this by dropping it outright, which means **no** iOS-reading option in this table has background refresh in v1. The real difference between (a) and (d) is therefore **"open the app" versus "open the app and tap import"**.

(a) still wins v1 on being cheap and requiring no ritual. But **(d) is a first-class path in #34, not an afterthought** — the share-sheet / "Open in" import is the same import flow with a different source, it sidesteps the placeholder problem in §2.3, and it leaves no file-provider cache on the phone (§4.2). **LAN + QR handoff is the named v2 door** if the cloud-provider exposure turns out to matter more than continuity.

A user who wants end-to-end encryption today can point `sync_export_dir` at a **Syncthing** folder — but be precise about what that buys: "zero code change" is true of the **desktop** only. There is no official Syncthing client for iOS, so receiving the folder on the phone needs a third-party App Store app providing a File Provider extension (Möbius Sync being the usual one), which is paid, independently maintained, and itself handles the plaintext library. It is a real option and a genuine benefit of "it's just a path", but it is not free and it is not first-party.

### 2.3 Mechanics

**Desktop side (#31)** — see §1.10 (call sites) and §1.11 (write discipline).

**iOS side (#34)**

- The user picks the bundle with `UIDocumentPickerViewController`; the app persists a **security-scoped bookmark** so later refreshes can reopen it without re-picking. The share-sheet / "Open in" path (option (d)) feeds the same import flow.
- **Refresh = on app foreground + manual pull-to-refresh. No `BGAppRefreshTask`** — this supersedes #34's task 2. Two reasons, and they reinforce each other: the artifact is written with `.complete` file protection (below), and `BGAppRefreshTask` routinely fires while the device is *locked*, where the app can neither write the artifact nor read the previous copy — the failure would surface through §3.2's catch-all and be reported to the user as a **corrupt bundle**, intermittently, only when the phone happened to be locked. And per §2.2 the task may barely fire anyway for an app opened this rarely, while the keyboard only ever sees what the container app wrote. Dropping it removes a misdiagnosis class and simplifies #34 at almost no cost.
- There is no push; a cloud folder has no callback the app can rely on. `exported_at` is surfaced as "library last changed" so a stale file is visible rather than mysterious.
- On refresh: validate `schema_version` (§1.4 table) → decode → write **atomically** into the App Group container. Reject-and-keep-previous on any failure (§3.2).

**The App Group artifact**, named here so #32 and #34 don't each invent one:

| Decision | Value |
| --- | --- |
| Filename | `bundle.json` in the App Group container root |
| Format | the validated bundle, re-serialised verbatim — v1 is a picker, so no index or split payload is needed |
| Write | to a sibling temp file created with `.completeFileProtection`, then `FileManager.replaceItemAt` — the keyboard must never observe a half-written file, and the temp must not be the weak link the permanent file isn't |
| File protection | `.complete` — safe because refresh now only runs in the foreground (above), the extension only ever runs on an unlocked device, and a seized phone that has merely been unlocked once since boot does not surrender the library |
| Backup | `isExcludedFromBackup = true` — otherwise the plaintext CPF library lands in iCloud Backup, where (outside Advanced Data Protection) Apple holds the keys |
| After every replace | **re-apply both attributes.** `replaceItemAt` swaps file identity, and whether protection class and the backup-exclusion flag survive depends on metadata-preservation behaviour that is not guaranteed. These are not set-once properties. |
| Change detection | the extension compares the file's modification date on `viewWillAppear` and reloads when it moved — it is a separate, short-lived process with no notification channel, and this needs none |

**File provider caveat, worth knowing before it bites**: iCloud Drive and Google Drive may present the bundle as *not materialised* (a placeholder). Reading it can trigger a download — use `NSFileCoordinator` and surface "baixando…" rather than reporting a corrupt bundle. A first-launch read failing because the file is a placeholder is the single most likely false "sync is broken" report.

---

## 3. Conflict policy v1

### 3.1 There are no conflicts

- The desktop is the sole writer. The bundle is a **full snapshot**, never a delta.
- Mobile is **read-only**: it replaces its local copy wholesale on every successful refresh. No merge, no per-entry comparison, no `exported_at` cursor — an older bundle replacing a newer one is impossible because the phone has nothing of its own to lose.
- The keyboard extension never writes to the App Group container. Only the container app does, and only from a validated bundle.

Consequence, stated plainly so nobody implements around it: **a snippet deleted on the desktop disappears from the phone on the next refresh.** That is correct — snapshot semantics — and it is why v1 needs no tombstones.

### 3.2 Failure is not a conflict

If a refresh fails — unreachable file, malformed JSON, rejected `schema_version`, decode error — the app **keeps the previous good copy** and surfaces the error in plain PT-BR. The keyboard is never left with no data. This mirrors the desktop's own rule that a corrupt `snippets.json` is quarantined and restored from the newest *valid* backup rather than overwritten with defaults (AGENTS.md, "Snippets File Safety").

### 3.3 The v2 door, explicitly out of scope

Two-way sync — editing a snippet on the phone and having it reach the desktop — is **not in v1**, and this format does not pretend to support it. Naming what it would require, so nobody mistakes a v1 field for a foothold:

1. **A stable per-snippet id** independent of the trigger. Today the trigger *is* the identity, so renaming a trigger on two devices is indistinguishable from deleting one and creating another.
2. **A per-snippet `updated_at`**, which the desktop does not track — `snippets.json` has one mtime for the whole library.
3. **Tombstones**, or a delete on one device is undone by the next sync from the other.
4. **A writer on the desktop side**: something must watch the cloud folder for mobile-authored changes and merge them into `snippets.json`, under the existing backup/quarantine guarantees.

Per-snippet last-writer-wins is the likely v2 policy, but it is a real design task, not a switch. None of these fields are reserved in v1: the §1.4 additive rule means they can be introduced in a `schema_version: 1` bundle as optional fields, and the version bumps only when v1 consumers can no longer read the file.

---

## 4. Privacy

### 4.1 What the file contains

Everything the user's library contains, in plaintext: CPFs, CNPJs, addresses, phone numbers, client names, email signatures, internal codes. `source/snippets.json` in the repo is an anonymized seed — the real library at `~/.txt_xpander/snippets.json` is not, and the bundle is a faithful compilation of it.

### 4.2 What an interceptor gets

Vantage points: a compromised cloud account, a shared folder the user forgot was shared, a stolen laptop, a backup of the sync folder, **a seized or backed-up phone**, and **the cloud provider itself**.

- **Every static snippet's full text**, including every CPF and CNPJ in the mapping containers, each labelled with the person or company name used as the item key. `_cpf_numbers` is effectively a name→CPF table, and the bundle expands it into exactly that.
- **Snippet references already resolved**, so indirection provides no obscurity.
- **The trigger vocabulary** — which itself leaks client names and business relationships.
- **`html` for rich-text entries** — not covered by "RTF and spans are not exported": HTML can carry `mailto:`/`href` addresses and structure the plain text does not.
- **`input.fields`** — the form-field vocabulary of every template, i.e. a schema of what the user collects about clients.
- **Which dynamic snippets the user enabled**, plus `exported_at` (an edit-activity timestamp) and `generator.{version,platform}` (a device fingerprint). Mild individually; they profile the user.

Two exposures that belong to the *transport* rather than the file:

- **Cloud version history.** Dropbox, Drive and iCloud retain prior revisions and a trash. Deleting a compromised snippet from the library does not unpublish it.
- **The temp file.** `write_json_atomic` creates its temp in the destination directory (§1.11), so a full plaintext copy transits the synced folder on every export and cloud clients routinely upload and retain those. Atomicity for the phone is preserved; confidentiality of the intermediate is not.
- **The file-provider cache on the phone.** Under transport (a) the bundle is read through iCloud Drive / Google Drive / Dropbox, each of which materialises and caches the downloaded file **inside its own app container**, with that app's protection class and backup behaviour, persisting after the import. So the phone holds *two* plaintext copies and §4.3 rule 6 only hardens one; the other is outside this app's control entirely. This is a concrete point in favour of transport (d), whose share-sheet import leaves no provider cache at all.

What it does **not** get: clipboard contents (never baked — §1.6), form-field *values* (never present), live financial data, RTF/style spans, `settings.json`, logs, or backups.

### 4.3 Rules

1. **User-owned storage only.** No Txt Xpander server, no third-party service the user did not already choose, no telemetry, no phone-home. The bundle is written to a local path; whether that path is synced, and by whom, is the user's decision.
2. **Be honest about the cloud provider.** iCloud, Google Drive and Dropbox encrypt in transit and at rest, but they hold the keys and can read the file. This is a real exposure, not a resolved one — §2.1 scores it as such, and two transports in §2.2 avoid it: **(c) in its LAN-only form** and **(d) delivered over USB**. Syncthing is discussed there too but is not a third candidate for this rule: on iOS it needs a paid, third-party File Provider app that handles the plaintext library itself.
3. **The export dir is a deliberate act.** No default value, ever; absent key = no bundle is written; a missing directory is not created (§1.11). **Turning the feature off does not turn the exposure off**: clearing `sync_export_dir` leaves the last bundle — and the cloud provider's version history of it — in place. The settings UI must say so, and must give the steps **in order**: clear the key *first*, then delete the file. Delete first and the next save recreates it, guaranteed — skip-if-unchanged always treats a missing file as changed.
4. **Warn on shared folders.** #31 should not attempt to *detect* sharing (unreliable across providers), but the settings UI and documentation must state that anyone with access to that folder gets the full library.
5. **Do not mirror and export into the same directory.** `mirror_dir` writes raw `snippets.json`; `sync_export_dir` writes the compiled bundle. Pointing both at one cloud folder doubles the exposure for no benefit. Unlike rule 4 this *is* checkable, so #31 checks it rather than leaving it to documentation: when both keys are set, compare with `os.path.samefile` inside a `try/except OSError` (it raises when either path is missing, and §1.11 explicitly tolerates a missing export dir while `mirror_dir` is only created lazily on the first mirror) and log a warning. **Advisory only** — it never blocks the export. The user may have meant it; they just need to know what it costs. Note the check is deliberately narrow: it catches the identical directory, not two sibling folders under the same synced root, which expose to the same provider and compare unequal. Detecting *that* is the unreliable cross-provider problem rule 4 declines.
6. **On the phone**: `.complete` file protection and `isExcludedFromBackup` on the App Group artifact (§2.3). Adopting a second device doubles the places this data can leak from, and neither of those is exotic.

### 4.4 Encryption: the named v2 door

Encrypting the bundle at rest (passphrase-derived key, symmetric, entered once per device) is **out of scope for v1** and is the mitigation for §4.2 when the cloud provider is the threat. Deferred on cost, not on threat model: it needs a key-management UX on both platforms and a passphrase-recovery story, and it removes the user's ability to inspect their own sync file. If it lands, it changes the *file*, not the schema — an encrypted envelope wrapping the same JSON, distinguishable by extension or magic header, so §1 survives unchanged. Until then, the two transports named in §4.3 rule 2 — (c) LAN-only and (d) over USB — are the real mitigation.

---

## 5. Notes the implementation issues inherit

### 5.1 App version constant (#31)

`generator.version` needs the app version. It exists today in exactly two hand-maintained, non-importable places — the `txt_xpander.pyw` module docstring (`Version: 3.2.0`) and `installer/txt_xpander.iss` (`MyAppVersion`). `generator.version` is therefore nullable and #31 is not blocked. Introducing a single importable constant would make it a *third* place unless the docstring is derived from it; that is a scope call for #31, not a requirement of this design.

### 5.2 Test surface implied by this document (#31)

Beyond #31's own acceptance criteria:

- Mapping expansion iterates `get_dynamic_prefixes`, so two containers claiming the same prefix export only the winner; `__prefix__` never becomes a trigger; an empty `__prefix__` yields bare item names; `_notes`-style non-container `_` keys are dropped.
- Collision precedence over the **export accept set** (not merely `enabled`): a registry entry with an unknown `provider` loses to the static snippet of the same name. Dynamic > static > mapping, loser dropped with a warning, no duplicate `trigger` in the bundle.
- Resolution: `snippet_ref`/`mapping_ref` resolved; `clipboard`/`dynamic_ref`/`form_field` preserved as tokens with a correct `input` block; `input` absent for a clean value; a form token injected by a one-level ref appears in `input.fields` via the step-3 re-scan; an injected *ref* lands in `input.residual` by name; a raw name already consumed into `fields`, `dynamic_refs` or `clipboard` is **not** also residual, but a name that survives into the resolved text **is** — including one re-injected under a label that was in the raw list (`"%%xname%% e %%xb%%"` with `xb = "cc %%xname%%"` yields `residual: ["xname"]`, because the second copy is never chased); a ref to a non-string/non-payload value is left as a token and appears in `residual`.
- The export never invokes a callable (sentinel-callable classification map, built dynamic-last), never touches the network, never opens a dialog, and never reads `self.snippets` — it re-reads `snippets.json` (§1.7).
- Rich text: `html` copied when clean, **omitted** when the raw value had variables; non-string/non-payload values skipped with a warning; callables skipped **silently**.
- strftime→TR35: every directive in the table; the exact string `dd/MM/yyyy' às 'HH:mm` for `"%d/%m/%Y às %H:%M"`; `EEEE, dd' de 'MMMM' de 'yyyy` for `method: "extenso"`; the `format`-absent default; an unknown directive producing `local: false` with no `render`.
- `dynamic[]` mirrors `build_dynamic_snippets`'s skips (unknown provider, invalid method/mode, non-dict, disabled, duplicate effective trigger); `enabled: true` present on survivors; rename reaches `trigger` while `id` stays the stable key.
- Write discipline: deterministic ordering (byte-identical bundle for identical input); skip-if-unchanged driven by `~/.txt_xpander/sync_export.state`, requiring all three of matching digest, matching recorded `path`, and an existing destination file — a deleted bundle, a repointed `sync_export_dir`, and an A→B→A round trip each force a rewrite, while a missing or unreadable state file forces one and an `app_version` change alone forces **none** (the digest excludes `generator`); missing export dir warns without creating it; relative `sync_export_dir` rejected; atomic replace with a single 0.5 s `PermissionError` retry and **no** temp sweep; unwritable-dir warning path; `mirror_dir`-equals-`sync_export_dir` warning that never blocks the export.
- All five call sites in §1.10 export, including the two registry writers and the two that bypass `save_snippets`. A toggle and a rename each reach the bundle — the regression test for the wrapper re-reading the registry file instead of `self.dynamic_registry`.
- `generator.version`: the test asserts the **injected value round-trips**, not a literal — §5.1 leaves the constant itself undecided, and `null` is legal.

### 5.3 Constraints for the iOS side (#32/#34)

- Decode with `Codable`, **tolerating unknown fields and unknown enum values** (§1.4 rules 2–3) — a strict decoder turns an additive desktop change into a broken phone.
- Implement the full `schema_version` table (§1.4), including the message split between "update the iOS app" and "invalid bundle".
- **Never crash on a duplicate `trigger`** — first wins (§1.7). A `Dictionary(uniqueKeysWithValues:)` in the shared model target would take down the keyboard extension.
- Keyboard extensions run under a hard memory ceiling well below a normal app's (commonly reported around 48–60 MB, undocumented and device-dependent). v1 is a picker, so there is no per-keypress parse to avoid; the constraint is on *holding* the decoded library, which is why the desktop warns above ~5 MB (§1.11) and why the container app, not the extension, does the validation and rewrite.
- Entries with `input` are displayed and searchable but not insertable; tapping explains why, naming `fields`, `dynamic_refs` or `residual` (§1.5).
- `dynamic` entries with `local: false` are displayed greyed as "desktop only"; `local: true` entries render locally from `render` (§1.8), honouring `render.locale` and the phone's timezone.
- Apply `.complete` file protection and `isExcludedFromBackup` to the App Group artifact, to its write temp, and **re-apply both after every `replaceItemAt`** (§2.3, §4.3 rule 6).
- **No `BGAppRefreshTask`** — refresh on foreground and pull-to-refresh only. This supersedes #34 task 2, and is what makes `.complete` safe (§2.3).
- Build the **share-sheet / "Open in" import as a first-class path**, not only the document picker (§2.2). It is the same import flow, and it is the only route that leaves no file-provider cache on the phone (§4.2).
- Carry a **snapshot test** for `method: "extenso"`: render a fixed date through the exported pattern and compare against the desktop's expected string (§1.8). The desktop side can only test the pattern, not the rendering.
