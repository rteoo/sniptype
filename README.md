# Sniptype

<p align="center">
  <img src="source/sniptype-icon.png" width="128" alt="Sniptype app icon">
</p>

<p align="center">
  A local-first text expander for Windows, with a tray app, visual snippet manager,
  dynamic data, rich text, forms, and optional offline voice input.
</p>

<p align="center">
  <a href="https://github.com/rteoo/sniptype/actions/workflows/ci.yml"><img src="https://github.com/rteoo/sniptype/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="https://github.com/rteoo/sniptype/tags"><img src="https://img.shields.io/github/v/tag/rteoo/sniptype?label=stable" alt="Stable tag"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
</p>

Type a short trigger such as `xmail`; Sniptype erases it and inserts the full
value. Expansion normally fires as soon as the last trigger character is typed.
An optional terminator mode waits for a following space or punctuation mark.

## Highlights

- Static plain-text and rich-text snippets.
- Variables for snippet references, clipboard content, and fill-in forms.
- Built-in date/time, Brazilian Central Bank, market-data, and WhatsApp actions.
- One manager for static snippets, dynamic mappings, built-in actions, backups,
  and optional voice controls.
- Dynamic actions can be enabled, disabled, and renamed without editing the
  bundled registry.
- Automatic rotating backups, corrupt-file quarantine, library import/export,
  and an optional deterministic mobile sync bundle.
- Per-user installation with no administrator rights required.
- Optional local voice dictation and spoken-trigger mode, disabled by default.
- No telemetry or keystroke logging.

## Quick start

Sniptype currently runs from source or from a locally built package. On Windows
with Python installed:

```powershell
git clone https://github.com/rteoo/sniptype.git
cd sniptype\source
python -m pip install -r requirements.txt
python sniptype.pyw
```

Use `pythonw sniptype.pyw` after setup when you do not need console output.
Ordinary text expansion does not require the optional voice dependencies.

### Releases and installer

The current stable source tag is
[`v3.4.0`](https://github.com/rteoo/sniptype/tree/v3.4.0). Public binary releases
have not yet been published from this repository. The default branch contains
post-`v3.4.0` maintenance work; use the tag when you need the exact stable source.
See the [development guide](source/docs/development.md) to build the Windows
package and installer or the macOS app locally.

The installer is currently unsigned, so Windows SmartScreen may show
**More info → Run anyway** on first launch. It installs for the current user in
`%LOCALAPPDATA%\Programs\Sniptype` and keeps application data separately in
`%USERPROFILE%\.sniptype`.

## First use

1. Start Sniptype and find its icon in the system tray or macOS menu bar.
2. Open **Gerenciar Snippets** from the tray menu.
3. Add a trigger and its replacement text, then save.
4. Type the trigger in another application.

The bundled sample library includes examples such as:

| Trigger | Result |
| --- | --- |
| `xname` | A sample name |
| `xmail` | A sample email address |
| `xhj` | Today's date |
| `xselic` | Current Selic target |
| `xwapp` | A WhatsApp link generated from a phone number |

The tray menu also exposes reload, autostart, enable/disable, voice, backup, and
data-folder actions when those features are available.

The manager is organized around the work being done:

| Tab | Purpose |
| --- | --- |
| **Snippets Estáticos** | Create and edit plain or rich-text expansions |
| **Mapeamentos Dinâmicos** | Maintain prefixed collections such as CPF/CNPJ mappings |
| **Snippets Dinâmicos** | Enable, disable, rename, and inspect built-in actions |
| **Backups** | Restore, import, or export the snippet library |
| **Entrada por voz** | Enable voice, choose a profile/language, and configure hotkeys |

## Variables

Snippet payloads can compose other values at expansion time:

- `%%other-trigger%%` inserts another snippet.
- `%%clipboard-paste%%` inserts the current clipboard text.
- `%%field-name%%` opens a form before insertion.

For example, `Hello, %%name%%` asks for `name` and inserts the completed text.
Variables also work in rich-text snippets; style spans are normalized after
substitution.

## Configuration

Optional settings live in `%USERPROFILE%\.sniptype\settings.json` by default,
or under the directory selected by `SNIPTYPE_HOME`. Most voice settings are
managed from **Gerenciar Snippets → Entrada por voz**.

| Setting | Behavior |
| --- | --- |
| `terminator_mode` | Wait for space or punctuation before expanding; Enter is not a terminator |
| `mirror_dir` | Copy `snippets.json` after each successful save |
| `sync_export_dir` | Write the compiled `sniptype_bundle.json` for mobile consumers |
| `bcb_timeout`, `bcb_cache_seconds` | Tune Central Bank request timeout and cache duration |
| `stock_cache_seconds` | Tune market-data cache duration |

`sync_export_dir` must already exist; Sniptype deliberately does not create it.
Both mirror and sync output contain plaintext user data.

## Data safety and privacy

Sniptype stores its live library, settings, rotating backups, and logs under
`%USERPROFILE%\.sniptype` by default. Set `SNIPTYPE_HOME` to use another local
directory. Every successful save backs up the previous library; a corrupt file
is quarantined and restored from the newest valid backup when possible.

The keyboard listener does not store, transmit, or log observed keystrokes.
Network access happens only for features that need it:

- Central Bank and stock snippets fetch current values.
- WhatsApp actions open a `wa.me` URL containing user-supplied data.
- Optional voice models download from their catalogued, SHA256-pinned URLs.

The optional `mirror_dir` and `sync_export_dir` settings copy plaintext snippet
data to a directory selected by the user. A cloud-synchronized destination can
therefore expose sensitive library content to that provider.

## Platform status and limitations

Sniptype is Windows-first. CI runs the unit suite on Windows, macOS, and Linux,
with Python 3.12 and 3.14, but packaged desktop behavior is verified most deeply
on Windows.

- **Windows password fields:** Sniptype does not currently detect password or
  other protected fields. Disable expansion from the tray before entering a
  password or other sensitive value. Native and browser password controls do
  not expose one dependable, non-blocking detection path to the keyboard hook.
- **macOS:** Input Monitoring and Accessibility permissions are required.
  Secure Keyboard Entry is detected before a trigger is erased. The current
  Apple Silicon build is ARM64-only.
- **Linux:** plain-text clipboard insertion is supported through Wayland/X11
  clipboard tools; rich text is downgraded to plain text. Wayland may restrict
  global keyboard hooks.
- **Desktop smoke tests:** tray behavior, actual cross-application paste, and
  macOS permission flows still require physical-host verification before a beta
  is promoted to stable.

## Optional voice input

Voice input is disabled by default and isolated from normal expansion. Balanced
uses Parakeet; Accuracy uses Qwen with automatic language detection. Live
streaming is not available. Missing voice dependencies leave ordinary snippet
expansion unchanged.

From the repository root, install the pinned optional runtime, restart Sniptype,
then configure voice from **Gerenciar Snippets → Entrada por voz**:

```powershell
python -m pip install -r source\requirements-voice.txt
```

The manager and tray stay synchronized for enable/disable state, model status,
profile, language, and dictation/command hotkeys. Dictation is literal; the
separate voice-command hotkey expands only an exact spoken trigger. Failed
insertion reports whether the transcript was actually preserved on the
clipboard instead of claiming recovery unconditionally.

Model downloads require HTTPS, follow only verified redirects, validate SHA256,
and resume only when the server confirms the requested byte range. See the
[voice input plan](source/docs/voice-input-plan.md) for the current verification
status and remaining adoption gates.

## Develop and build

Editable Python source and tests live under [`source/`](source). See
[Development and release builds](source/docs/development.md) for source setup,
test commands, Windows/macOS packaging, installer creation, release channels,
and known verification limits.

The deeper architecture and completed audit roadmap are documented in
[`source/docs/`](source/docs). Release history lives only in
[CHANGELOG.md](CHANGELOG.md).

## License

Sniptype is released under the [MIT License](LICENSE). Packaged builds include
the applicable dependency attribution index in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
