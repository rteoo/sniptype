# SnipType

<p align="center">
  <img src="source/sniptype-app-icon.png" width="128" alt="SnipType app icon">
</p>

<p align="center">
  A local-first text expander for Windows, with a tray app, visual snippet manager,
  dynamic data, rich text, and forms.
</p>

<p align="center">
  <a href="https://github.com/rteoo/sniptype/actions/workflows/ci.yml"><img src="https://github.com/rteoo/sniptype/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="https://github.com/rteoo/sniptype/tags"><img src="https://img.shields.io/github/v/tag/rteoo/sniptype?label=stable" alt="Stable tag"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
</p>

Type a short trigger such as `xmail`; SnipType erases it and inserts the full
value. Expansion normally fires as soon as the last trigger character is typed.
An optional terminator mode waits for a following space or punctuation mark.

## Highlights

- Static plain-text and rich-text snippets.
- Variables for snippet references, clipboard content, and fill-in forms.
- Built-in date/time, Brazilian Central Bank, market-data, and WhatsApp actions.
- One manager for static snippets, dynamic mappings, built-in actions, and backups.
- Dynamic actions can be enabled, disabled, and renamed without editing the
  bundled registry.
- Automatic rotating backups, corrupt-file quarantine, library import/export,
  and an optional deterministic mobile sync bundle.
- Schema-v1 metadata for groups, structured forms, favorites, and workflow
  navigation, kept inside the same backed-up library document.
- Interface in English or Brazilian Portuguese: it follows the Windows display
  language until you choose one in Settings > General.
- Per-user installation with no administrator rights required.
- No telemetry or keystroke logging.

## Quick start

Download the Windows installer from the [latest stable release](https://github.com/rteoo/sniptype/releases/latest).
To run from source with Python installed:

```powershell
git clone https://github.com/rteoo/sniptype.git
cd sniptype\source
python -m pip install --require-hashes -r ../requirements-release.lock
python sniptype.pyw
```

Use `pythonw sniptype.pyw` after setup when you do not need console output.

### Releases and installer

The current stable release is
[`v1.1.0`](https://github.com/rteoo/sniptype/releases/tag/v1.1.0) for Windows;
SnipType is also available from the Microsoft Store. v1.1.0 moves the manager's
navigation into a left sidebar so every page gets the window's full height. It
builds on v1.0.0's SnipType display name, English interface option and Windows
Design System manager refresh, and on v0.15.0's dark
theme and Configurações tab and v0.14.x's more reliable typing and pasting;
voice transcription now lives in the independent Snipvoice project. For macOS,
the ARM64 build is available as the
[`v0.14.4-beta.1` preview](https://github.com/rteoo/sniptype/releases/tag/v0.14.4-beta.1),
at feature parity with v0.14.3. Versions before 1.0.0 were renumbered into
`0.x`; the [changelog](CHANGELOG.md) maps the old numbers.

The installer and the Store version use the same snippet library in
`%USERPROFILE%\.sniptype` and only one of them runs at a time; uninstall the
installer version after switching to the Store.

See the [development guide](source/docs/development.md) to build
the Windows package and installer or the macOS app locally.

The installer is currently unsigned, so Windows SmartScreen may show
**More info → Run anyway** on first launch. It installs for the current user in
`%LOCALAPPDATA%\Programs\Sniptype` and keeps application data separately in
`%USERPROFILE%\.sniptype`.

## First use

1. Start SnipType and find its icon in the system tray or macOS menu bar.
2. Open **Gerenciar Snippets** from the tray menu.
3. Add a trigger and its replacement text, then save.
4. Type the trigger in another application.

The interface starts in English when Windows is in English and in Brazilian
Portuguese otherwise. To change it, open **Settings > General** (**Configurações
> Geral**), choose a language under **Language** (**Idioma**) and apply it; the
choice is remembered from then on. The tray menu item above reads **Manage
Snippets** in English.

The bundled sample library includes examples such as:

| Trigger | Result |
| --- | --- |
| `xname` | A sample name |
| `xmail` | A sample email address |
| `xhj` | Today's date |
| `xselic` | Current Selic target |
| `xwapp` | A WhatsApp link generated from a phone number |

The tray menu also exposes reload, autostart, enable/disable, backup, and
data-folder actions when those features are available.

The manager is organized around the work being done:

| Tab (Portuguese / English) | Purpose |
| --- | --- |
| **Textos** / **Snippets** | Create and edit plain or rich-text expansions |
| **Mapeamentos** / **Mappings** | Maintain prefixed collections such as CPF/CNPJ mappings |
| **Ações dinâmicas** / **Dynamic actions** | Enable, disable, rename, and inspect built-in actions |
| **Cópias de segurança** / **Backups** | Restore, import, or export the snippet library |
| **Configurações** / **Settings** | Language, appearance, expansion mode, hotkeys, and data folder |

## Variables

Snippet payloads can compose other values at expansion time:

- `%%other-trigger%%` inserts another snippet.
- `%%clipboard-paste%%` inserts the current clipboard text.
- `%%field-name%%` opens a form before insertion.

For example, `Hello, %%name%%` asks for `name` and inserts the completed text.
Variables also work in rich-text snippets; style spans are normalized after
substitution.

## Metadata and workflow

New manager state is stored under the reserved `__sniptype__` entry in
`snippets.json`; it is not a snippet, trigger, variable, mapping, or sync entry.
Schema-v1 metadata is backed up, restored, imported, mirrored, and joined to
the library atomically. A malformed or newer metadata block is preserved
unchanged and loaded read-only, so valid snippets continue to expand while
groups, forms, and favorites remain unavailable until a compatible version can
edit them. Missing metadata keeps the legacy library behavior.

Groups provide labels, prefixes, enabled state, terminator policy, and optional
Windows executable allow/deny rules. A prefix changes only the effective
trigger (`prefix + stored key`); the stored key and snippet references remain
stable. Executable matching uses a case-folded basename and is an accidental-
expansion control, not an authentication boundary. Allow rules fail closed
when Windows identity cannot be established or the platform is unsupported.

Structured forms support text, multiline, choice, date, and optional fields,
with validated defaults, repeated names, and ISO date input rendered through an
explicit format. Favorites persist for static and mapping items. Recent and
edit-last are session-only identity references (no content history is written).
Preview resolves local references and shows explicit clipboard/dynamic
placeholders; it never reads the clipboard, calls providers, opens a browser,
inserts text, or records usage.

Optional workflow hotkeys are unset by default. The implementation is local and
private by default: no account, hosted sync, telemetry, or keystroke history is
added. If `sync_export_dir` or `mirror_dir` is configured, the selected
destination receives plaintext user data.

## Configuration

Optional settings live in `%USERPROFILE%\.sniptype\settings.json` by default,
or under the directory selected by `SNIPTYPE_HOME`. Edit this optional file
to configure the runtime settings below.

| Setting | Behavior |
| --- | --- |
| `terminator_mode` | Wait for space or punctuation before expanding; Enter is not a terminator |
| `mirror_dir` | Copy `snippets.json` after each successful save |
| `sync_export_dir` | Write the compiled `sniptype_bundle.json` for mobile consumers |
| `bcb_timeout`, `bcb_cache_seconds` | Tune Central Bank request timeout and cache duration |
| `stock_cache_seconds` | Tune market-data cache duration |

`sync_export_dir` must already exist; SnipType deliberately does not create it.
Both mirror and sync output contain plaintext user data.

Dynamic trigger overrides live in `dynamic_snippets.json` in the same user-data
directory. The optional `enabled` field accepts only JSON `true` or `false`
(without quotes); omitting it enables the entry. Invalid values, including
`"false"`, numbers, `null`, lists, and objects, disable that entry and log a
warning. Other fields and neighboring entries are retained. To migrate an older
hand-edited override, replace a previously truthy value with `true`, or use the
dynamic tab's enable toggle to save a valid boolean.

## Data safety and privacy

SnipType stores its live library, settings, rotating backups, and logs under
`%USERPROFILE%\.sniptype` by default. Set `SNIPTYPE_HOME` to use another local
directory. Every successful save backs up the previous library; a corrupt file
is quarantined and restored from the newest valid backup when possible.

The keyboard listener does not store, transmit, or log observed keystrokes.
Network access happens only for features that need it:

- Central Bank and stock snippets fetch current values.
- WhatsApp actions open a `wa.me` URL containing user-supplied data.

The optional `mirror_dir` and `sync_export_dir` settings copy plaintext snippet
data to a directory selected by the user. A cloud-synchronized destination can
therefore expose sensitive library content to that provider.

The full policy, in English and Portuguese, is in [PRIVACY.md](PRIVACY.md).

## Platform status and limitations

SnipType is Windows-first. CI runs the unit suite on Windows with Python 3.12
and 3.14, plus one current-Python lane on macOS and Linux. The Linux lane also
runs focused Ruff checks. Packaged desktop behavior is verified most deeply on
Windows.

- **Windows password fields:** SnipType does not currently detect password or
  other protected fields. Disable expansion from the tray before entering a
  password or other sensitive value. Native and browser password controls do
  not expose one dependable, non-blocking detection path to the keyboard hook.
- **macOS:** Input Monitoring and Accessibility permissions are required.
  Secure Keyboard Entry is detected before a trigger is erased. The available
  `v0.14.4-beta.1` preview is ARM64-only and signed with a self-signed
  certificate, so Gatekeeper asks you to confirm its first launch.
- **Linux:** plain-text clipboard insertion is supported through Wayland/X11
  clipboard tools; rich text is downgraded to plain text. Wayland may restrict
  global keyboard hooks.
- **Desktop smoke tests:** tray behavior, actual cross-application paste, and
  macOS permission flows still require physical-host verification before a beta
  is promoted to stable.

## Looking for voice transcription?

Voice input now lives in [Snipvoice](https://github.com/rteoo/snipvoice), an
independent app for local voice capture and transcription. Snipvoice owns its
model management, corrections, and recording history, while SnipType v0.13.0
and later remain focused on text and keyboard expansion.

SnipType releases before v0.13.0 retain their original voice behavior. Existing
`~/.sniptype/voice-history` data, voice settings, and cached models are left
untouched; Snipvoice uses separate data and cache folders without automatic
migration.

## Develop and build

Editable Python source and tests live under [`source/`](source). See
[Development and release builds](source/docs/development.md) for source setup,
test commands, Windows/macOS packaging, installer creation, release channels,
and known verification limits.

The deeper architecture and completed audit roadmap are documented in
[documentation index](source/docs/README.md). Release history lives only in
[CHANGELOG.md](CHANGELOG.md).

## License

SnipType is released under the [MIT License](LICENSE). Packaged builds include
the applicable dependency attribution index in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
