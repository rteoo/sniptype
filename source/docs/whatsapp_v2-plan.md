# Add `xlwapp` and `xpwapp` WhatsApp Snippets

Date: 2026-03-09

## Summary
- Extend the current WhatsApp snippet set with:
  - `xlwapp`: clipboard-first like `xwapp`, popup fallback on invalid/missing phone, inserts the generated URL into the active field, and keeps that URL in the clipboard, but does not open the browser.
  - `xpwapp`: skips clipboard lookup entirely, opens the popup immediately, validates the phone exactly like the other WhatsApp flows, opens the browser, and keeps the URL in the clipboard.
- Keep `xwapp` behavior unchanged.

## Implementation Changes
- Refactor the WhatsApp handling in `txt_xpander.pyw` into one shared internal flow that separates:
  - phone source: `clipboard-first` vs `force-popup`
  - side effects: `copy_url`, `open_browser`, `return_url_for_insertion`
- Register `xlwapp` and `xpwapp` as built-in dynamic snippets and include them in `slow_snippets` so the typed trigger is erased before popup/browser work starts.
- Define the three runtime modes explicitly:
  - `xwapp`: clipboard-first, popup fallback, validate with `normalize_phone_number`, copy URL to clipboard, open browser, return no inserted text
  - `xlwapp`: clipboard-first, popup fallback, validate with `normalize_phone_number`, copy URL to clipboard, do not open browser, return URL text for insertion
  - `xpwapp`: force popup immediately, validate with `normalize_phone_number`, copy URL to clipboard, open browser, return no inserted text
- Keep the popup fields blank by default for all manual-entry paths, including `xpwapp`.
- Reuse the same WhatsApp helper functions in `whatsapp_support.py`; no new normalization rules.
- Update WhatsApp reference data and README so all three triggers are documented with their exact behavior.

## Public Interfaces
- New built-in triggers:
  - `xlwapp`
  - `xpwapp`
- No changes to `snippets.json`, stored snippet format, or existing `xwapp` contract.

## Test Plan
- Extend GUI/reference tests so the WhatsApp reference list contains `xwapp`, `xlwapp`, and `xpwapp`.
- Add runtime-focused unit coverage for the WhatsApp flow modes:
  - `xlwapp` with valid clipboard returns URL text, copies URL to clipboard, and skips browser open
  - `xlwapp` with invalid clipboard goes through popup validation and still returns URL text
  - `xpwapp` ignores clipboard lookup and always goes straight to popup validation
  - `xwapp` remains clipboard-first and side-effect-only
- Keep helper-level tests for URL generation and phone normalization unchanged, and add any small assertions needed for the new trigger names/reference content.
- Manual Windows smoke tests:
  - `xlwapp`: valid clipboard inserts URL, keeps URL in clipboard, does not open browser
  - `xlwapp`: invalid clipboard opens popup, validates phone, inserts URL, keeps URL in clipboard
  - `xpwapp`: popup opens immediately even if clipboard has a valid phone, then browser opens and clipboard keeps URL
  - `xwapp`: regression test for current clipboard-first open-browser flow

## Assumptions
- `xlwapp` should both insert the generated URL and leave the same URL in the clipboard.
- `xpwapp` should always bypass clipboard phone detection.
- Telephone validation for `xlwapp` and `xpwapp` must be exactly the same as `xwapp`, using the existing WhatsApp normalization rules.
- Popup defaults remain blank for phone and message.
