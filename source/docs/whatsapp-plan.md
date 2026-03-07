# WhatsApp Shortcut (`xwapp`)

## Summary
- Add a built-in dynamic snippet `xwapp` that removes the typed trigger, reads a phone number from the clipboard, generates a valid `wa.me` link, copies that link to the clipboard, and opens it in the default browser.
- If the clipboard does not contain a usable number, open a small modal popup to collect the phone and an optional message, then generate/open the link from that input.
- Keep this feature code-driven like the existing dynamic snippets; do not change the `snippets.json` schema.

## Implementation Changes
- Add a small pure helper module for WhatsApp logic:
  - extract a phone candidate from raw clipboard text or an existing WhatsApp URL
  - normalize to digits-only international format
  - rules: strip punctuation; if the raw input starts with `+` or `00`, treat it as explicit international and remove the prefix marker; otherwise, treat 10/11-digit inputs as Brazilian local numbers and prefix `55`; if the local input starts with one trunk `0`, drop that `0` before applying `55`; accept already-international 12-15 digit numbers as-is; reject everything else
  - build `https://wa.me/<number>` and append `?text=<urlencoded>` only when the message is non-empty, using UTF-8 percent-encoding
- Register `xwapp` in the built-in dynamic snippet map and include it in the slow/action snippet set so the trigger is erased before the side effect runs.
- Implement the `xwapp` handler as a self-contained action snippet:
  - read the clipboard with `WindowsClipboard.get_text()`
  - if the clipboard yields a valid phone, generate a link with empty message
  - if the clipboard is empty/invalid, open a modal Tk dialog with:
    - phone `Entry`, prefilled from the clipboard text when useful
    - message `Text`, initialized empty
    - `Abrir WhatsApp` and `Cancelar`
    - submit validation using the same normalizer; invalid input keeps the dialog open and shows a warning
  - on success, write the final URL with `WindowsClipboard.set_content(url)`, open it with `webbrowser.open(url)`, and fall back to `os.startfile(url)` only if `webbrowser.open` fails
  - on cancel, exit silently and leave the clipboard untouched
  - on clipboard/browser errors, call `notify_error`; if the URL was already generated, keep it in the clipboard
- Do not route `xwapp` through `TextInserter`, because that path restores the previous clipboard content and conflicts with the requested behavior.
- Update the manager reference UI with a dedicated WhatsApp tab or section that documents `xwapp` and its clipboard/popup behavior.

## Public Interfaces
- New built-in trigger: `xwapp`
- New pure helper functions for WhatsApp phone normalization and URL generation
- No persisted config or JSON format changes

## Test Plan
- Add unit tests for the helper logic covering:
  - `11999999999` -> `5511999999999`
  - `011999999999` -> `5511999999999`
  - `+1 (212) 555-1234` -> `12125551234`
  - `005511999999999` -> `5511999999999`
  - rejection of non-numeric, too-short, too-long, and 8/9-digit local numbers without DDD
  - URL generation with and without message, including accents, spaces, symbols, and line breaks
  - extraction from existing WhatsApp links already in the clipboard
- Extend GUI/reference tests so the WhatsApp reference list is covered.
- Manual Windows smoke test:
  - valid clipboard number: no popup, trigger disappears, browser opens, generated link remains in clipboard
  - invalid/missing clipboard: popup appears, manual phone + optional message works, nothing is inserted back into the original field
  - cancel: no browser launch and clipboard unchanged
  - forced browser-open failure: tray error appears and the generated link is still left in the clipboard

## Assumptions
- `xwapp` only removes the trigger; it does not paste the generated link into the active app.
- The default message is empty.
- When the country code is not explicit, the default country code is `55`.
- Leaving the generated WhatsApp link in the clipboard is intentional and should bypass the app’s normal clipboard-restore behavior for this trigger only.
