# TextExpander benchmark for Sniptype

Research date: 2026-09-16. Sources are first-party TextExpander product, help, security, privacy, and pricing pages. Pricing, plan names, and feature availability are time-sensitive; verify again before using this as a release or commercial comparison. No secondary sources were used.

## Executive read

TextExpander is an account-backed snippet library with desktop, browser, and mobile clients. Its benchmark value is the depth around the basic trigger: searchable and grouped libraries, reusable dynamic content, form-like fill-ins, application scoping, rich text, scripts, public/team sharing, request/review workflows, usage reporting, and snippet history. The core expansion path and library-safety layer are already Sniptype strengths; the highest-value local improvements are in-place discovery, richer forms, per-group/application policy, and reversible snippet-level history.

Sniptype should keep its boundary: text and keyboard input only, local/private by default, Windows-first with macOS preview. TextExpander's AI, account, billing, hosted sharing, and organization features are not reasons to add voice capture, transcription, or a cloud dependency.

## Feature inventory and local translation

| TextExpander capability | What the official material says | Sniptype treatment |
|---|---|---|
| Triggered snippets | Abbreviations expand into longer content; labels improve searchability, and case-sensitive snippets are supported ([Snippets Overview](https://textexpander.com/learn/using/snippets)). | Keep the indexed keyboard path. Add explicit case sensitivity and stronger conflict diagnostics if useful; do not replace the suffix index with an O(n) scan. |
| Groups and prefixes | Groups organize snippets, can be prefixed, disabled, and scoped to all, selected, or no applications; expansion can require whitespace or other delimiters ([Snippet Group Settings](https://textexpander.com/learn/using/snippet-groups/snippet-group-settings)). | High priority: make groups first-class in the manager, with local per-group enable/disable, prefix, terminator policy, and executable/app allowlist. This fits the existing registry and optional terminator mode. |
| Search and quick insertion | Search matches abbreviation, content, or label in the app, tray/menu helper, or an inline popup at the cursor ([Searching Snippets](https://textexpander.com/learn/using/searching-snippets)). | High priority: tray search plus a keyboard-driven inline search popup. Search trigger, label, group, and plain-text preview without sending library data anywhere. |
| Plain and rich content | Plain Text adapts to the destination; Rich Text supports formatting, hyperlinks, and pictures; script formats also exist ([Snippets Overview](https://textexpander.com/learn/using/snippets)). | Rich text already exists in Sniptype. Improve preview/import/export and preserve all clipboard formats where practical. Keep scripts opt-in and local; never execute imported code silently. |
| Date/time and date math | Date/time macros support multiple formats; date math can add/subtract time and affects later date macros, including nested snippets ([Using Dates and Times](https://textexpander.com/learn/using/snippets/advanced-snippet-elements/date-time)). | Already aligned with Sniptype’s dynamic date registry. Add a documented, testable local date-format and offset syntax rather than a general scripting dependency. |
| Fill-ins | Single-line, multi-line, date picker, popup menu, and optional sections can personalize one snippet at expansion time ([Fill-in fields](https://textexpander.com/learn/using/snippets/advanced-snippet-elements/advanced-fill-ins)). | High priority: extend existing `%%field%%` forms with dropdowns, optional blocks, defaults, repeated named fields, and a date picker. Keep dialog work on the shared GUI thread. |
| Conditional sections | A dropdown chooses exactly one branch; branches can contain fill-ins, macros, nested snippets, images, tables, and nested conditional sections ([Conditional Sections](https://textexpander.com/learn/using/snippets/snippet-fill-ins/conditional-sections)). | Good next step after basic forms: a bounded local conditional/template format. Add recursion/depth limits and preview all branches to avoid expansion surprises. |
| Nested snippets | A snippet can insert another snippet; TextExpander lists nested snippets among its advanced/paid features ([Advanced Snippet Elements](https://textexpander.com/learn/using/snippets/advanced-snippet-elements), [free-plan feature limits](https://textexpander.com/learn/free-plan/using-snippets-with-paid-only-features)). | Sniptype already resolves one level of `%%snippet_ref%%` with cycle protection. Add dependency preview; only add deeper nesting with an explicit maximum depth. |
| Clipboard, cursor, and keyboard macros | Macros can insert clipboard text, move the cursor, insert snippets, and emit keys such as Enter, Escape, or Tab ([Advanced Snippet Elements](https://textexpander.com/learn/using/snippets/advanced-snippet-elements), [Special Codes](https://textexpander.com/learn/using/snippets/advanced-snippet-elements/special-codes)). | Clipboard insertion and variables already exist. Add safe cursor markers/selection and a small allowlisted key-macro set. Treat Enter/Tab as explicit high-risk actions and show a preview/confirmation option. |
| JavaScript / AppleScript / Shell snippets | TextExpander runs script snippets in its app context; JavaScript works on Windows/iOS, while AppleScript and Shell are platform-specific ([JavaScript snippets](https://textexpander.com/learn/using/snippets/scripting-textexpander/javascript), [Snippets Overview](https://textexpander.com/learn/using/snippets)). | Do not copy broad script execution by default. If requested, add a separately disabled local extension with explicit per-snippet permission, timeout, no network by default, and an audit trail. Never make imported snippets executable automatically. |
| Application scoping | Groups can expand everywhere, only in selected applications, or nowhere ([Snippet Group Settings](https://textexpander.com/learn/using/snippet-groups/snippet-group-settings)). | High priority privacy and safety feature. Implement Windows executable/process matching first; add macOS bundle identifiers when the preview matures. Default sensitive groups to an allowlist. |
| Import/export and backup | TextExpander imports `.textexpander`, CSV, and Google Sheets HTML, and exports groups as CSV; export requires edit/manage permission ([Importing and Exporting](https://textexpander.com/learn/using/importing-and-exporting-snippet-groups)). | Sniptype already has validated JSON import/export, restore UI, atomic writes, rotating backups, and corrupt-file recovery. Add CSV and richer import preview only when interoperability justifies it. |
| Workflow shortcuts and suggestions | TextExpander can create from clipboard, duplicate and preview snippets, edit the last expanded snippet, assign hotkeys, alias abbreviations, autocorrect, and suggest snippets from repeated typing ([Creating snippets](https://textexpander.com/learn/using/snippets/create), [Preferences](https://textexpander.com/learn/using/preferences), [Suggested Snippets](https://textexpander.com/learn/using/snippets/create/suggested-snippets)). | Add preview, duplicate, edit-last-expanded, favorites/recent, and configurable hotkeys. Avoid passive phrase harvesting by default; it conflicts with Sniptype's no-keystroke-logging premise. |
| Public groups/templates | Users can subscribe to reviewed public groups/templates; public snippets and groups are hosted and shareable ([Public groups](https://textexpander.com/learn/using/public-groups/contributing-to-snippets-in-public-groups), [Snippet templates](https://textexpander.com/learn/using/public-groups/using-snippet-templates)). | Optional local template packs shipped as files, with provenance and license metadata. A future static HTTPS catalog is a separate opt-in product; do not make it part of the private core. |
| Public snippet links | A published snippet is visible to anyone with the link, requires no sign-in, and is copied—not live-synced—into the recipient’s library ([Publish Snippets](https://textexpander.com/learn/using/share/publishing-snippets)). | Do not reproduce this by default. If sharing is needed, export an explicit redacted bundle or use a user-run local/LAN endpoint with expiry and no indexing. Make the public/private boundary visually unmistakable. |
| Team sharing and roles | Groups have can-expand, can-edit, and can-manage permissions; organizations and teams curate libraries ([Snippet Group Permissions](https://textexpander.com/learn/using/snippet-groups/snippet-group-permissions), [organization groups](https://textexpander.com/learn/organization/managing-organization-snippet-groups)). | Local single-user first. Later, model role metadata in a shared folder or user-run LAN service: read, edit, manage; never require a hosted identity provider. Keep personal and shared groups separate. |
| Requests/workflow | Members can submit new or changed snippet requests, assign them to editors/admins, and track them in-app ([Requests](https://textexpander.com/learn/organization/requests-propose-new-snippets-and-snippet-changes/accessing-and-managing-requests-assigned-to-you)). | Useful for small teams: a local `requests.json`/SQLite queue with proposed diff, requester, reviewer, status, and resolution. It can work over a shared folder before a server is justified. |
| Activity history/restore | Activity records create/edit/move/delete/restore events, shows before/after content, and can restore prior or deleted snippets; retention varies by plan ([Snippet Activity](https://textexpander.com/learn/organization/tracking-changes-to-snippets-with-snippet-activity)). | Highest-value governance feature for a private tool. Use append-only local journal plus content-addressed snapshots, diff/restore UI, and retention controls. Never upload content merely to obtain history. |
| Personal and organization statistics | Personal reports show time saved, expansion counts, and snippet usage with configurable date range and WPM ([Usage Statistics](https://textexpander.com/learn/accounts/statistics)); organization admins can view organization statistics ([Organization permissions](https://textexpander.com/learn/organization/organization-permissions)). | Add local-only counters: expansion count, estimated characters/time saved, failure count, and per-group totals. Keep raw trigger/content out of telemetry exports by default; provide a clear reset/export control. |
| AI recommendations | The pricing page lists AI Recommended Snippets in the Chrome extension, based on what the user is working on ([Pricing](https://textexpander.com/pricing)); the learning center describes it as a new feature ([Learning Center](https://textexpander.com/learn)). | Do not send typed context to a vendor. A future local recommender can use explicit snippet labels and a bounded on-device index; it must be off by default and never observe password fields or transmit keystrokes. |
| MCP access for agents | The current pricing comparison lists MCP access for AI agents ([Pricing](https://textexpander.com/pricing)); the retrieved first-party pages did not expose implementation or data-flow details. | Treat as unverified scope. If added, expose a read-only local library search/preview first, with explicit write approval and no raw keystroke or secret access. |
| Offline use and cross-platform clients | TextExpander documents Windows 10+, macOS 11.1+, Chrome v109+, mobile clients, and says expansion continues offline even though the account service synchronizes content ([Download](https://textexpander.com/download), [Security](https://textexpander.com/security), [iPhone/iPad](https://textexpander.com/learn/using/textexpander-for-iphone-ipad)). | Sniptype remains Windows-first and macOS preview. Preserve offline expansion. Its existing mobile bundle can support a separate consumer without turning desktop expansion into a hosted service. |

## Privacy and data-flow benchmark

TextExpander says its apps do not store or send keystrokes, but its documented behavior keeps a short encoded keystroke record in volatile memory (up to 30 keystrokes, or up to 300 with Snippet Suggestions); secure input fields disable capture when the host marks them secure ([keystrokes and snippet security](https://textexpander.com/learn/accounts/security/how-textexpander-handles-your-keystrokes-keylogging-and-snippet-security)). That is materially different from Sniptype’s local process, but it is still a useful threat-model requirement: no telemetry, no suggestion observer by default, and explicit exclusions for password managers, terminals, and other sensitive apps.

TextExpander documents encrypted data at rest (AES-256), TLS 1.2+ in transit, SOC 2/SOC 3, GDPR/CCPA handling, HIPAA compliance claims, subprocessors, retention, and possible disclosure under lawful requests ([Security](https://textexpander.com/security), [Privacy Policy](https://textexpander.com/privacy)). Those controls protect a hosted service; they do not make the service local. Its installation guidance requires an account and a running app on each device, with snippets synchronized through the account ([Installing TextExpander](https://textexpander.com/learn/accounts/installing-textexpander)).

The privacy boundary is especially important for teams: TextExpander’s closed-organization documentation says organization admins can see “Just Me” snippets and that the organization owns/controls organization data ([who can see snippets](https://textexpander.com/learn/organization/organization-account-and-settings/who-can-see-your-snippets-and-account-data-in-a-closed-textexpander-organization)). A private Sniptype design should make ownership simpler and stronger: the local user data directory is authoritative; sharing is explicit; no administrator can silently inspect personal groups; and any sync/export directory is opt-in, clearly named, and never created because of a typo.

## Sniptype's current baseline

The current repository already covers more of the benchmark than the old audit snapshot suggests:

- Immediate or optional terminator-gated expansion through a compiled longest-first trigger index.
- Plain and rich text, snippet and mapping references, clipboard variables, and single-line form fields.
- Local dynamic providers for date/time, Brazilian Central Bank data, market data, and WhatsApp actions.
- Manager search by trigger/content, value previews and markers, dynamic trigger rename/enable controls, and custom prefixed mappings.
- Rotating backups, corrupt-file quarantine/recovery, restore/import/export UI, atomic persistence, and an open-data-folder action.
- A deterministic optional mobile bundle and mirror, both written only to user-selected paths; their plaintext exposure is documented.
- Local user data by default, no account, no telemetry, and no storage or transmission of observed keystrokes.

That baseline changes the roadmap: do not rebuild backup/import/search plumbing. Extend it into faster retrieval, richer metadata/forms, app-aware safety, and per-snippet history.

## Recommended implementation order for Sniptype

### Now: private daily-use quality

1. **Inline command palette:** a global hotkey that opens search beside the caret, searches trigger/content/group/label locally, previews the result, and inserts without opening the manager.
2. **Richer fill-ins:** defaults, multi-line fields, dropdowns, optional sections, repeated named values, and date picking on the existing GUI-thread/form architecture.
3. **Groups plus application policy:** first-class groups with label/notes/prefix, enable state, terminator policy, and Windows executable allow/deny rules. This directly reduces accidental expansion in sensitive apps.
4. **Workflow shortcuts:** preview, duplicate, edit-last-expanded, favorites/recent, and configurable hotkeys.
5. **Per-snippet local history:** an append-only journal with before/after views and restore. Keep the current whole-library rotating backups as the disaster-recovery layer.

The concrete implementation checkpoints for items 2–4 are in
[TextExpander benchmark features 2–4: implementation plan](textexpander-features-2-4-plan.md).

### Next: reusable local templates

1. Conditional sections with bounded nesting and branch preview.
2. Dependency preview for existing snippet references; optional deeper nesting with a strict depth limit.
3. Date/time math and a safe cursor-position marker, followed by a very small allowlisted key-macro set only if cross-application tests are reliable.
4. Local template packs with provenance/license metadata and a safe import review screen.
5. Local-only usage counters for expansion count, characters/time saved, and failures, with clear reset/export controls and no raw typed context.

### Later: small-team collaboration without a hosted core

1. Optional encrypted bundle sync under the user's chosen folder, Syncthing, LAN, or USB transport; expansion must continue offline.
2. Read-only local MCP search/preview over snippets explicitly marked agent-visible; writes require an explicit user action and sensitive mappings stay excluded by default.
3. Shared-folder or user-run LAN library with explicit read/edit/manage roles.
4. Local requests queue and review workflow.

### Deliberately out of scope

Voice capture, transcription, microphone permissions, recording history, hosted account/billing, vendor AI, public snippet links, and an always-on cloud sync service. These either violate Sniptype’s boundary or weaken its local/private promise. Script execution is also out of the default path; if it ever arrives, it needs a separate security design and explicit permissions.

## Benchmark caveats

- TextExpander’s pricing page is the authoritative current plan comparison, but plan limits and feature names can change; the page currently lists Free, Pro, Business, and Enterprise tiers and account-backed cross-device use ([Pricing](https://textexpander.com/pricing)).
- The official help center contains both current and legacy articles. The benchmark uses current-looking pages where possible and treats older macro/special-code material as capability evidence, not as a drop-in syntax specification.
- The retrieved official pages did not provide enough detail to verify MCP protocol permissions, AI recommendation retention, or a complete subprocessor/data-residency map. Those are open questions, not evidence that TextExpander handles data unsafely.
- No runtime or UI comparison was performed. This is a product/document benchmark; Sniptype still needs focused implementation tests and real Windows/macOS smoke tests for any selected feature.
