# Voice Input — Evaluation and Integration Plan

Status: **research only, nothing implemented.** Dated 2026-08-13.

Evaluates open-source speech-to-text projects as the basis for a dictation
feature in Txt Xpander, originally framed as "which Wispr Flow alternative
should we fork?" The short answer is that forking is the wrong shape; the
reasoning is below.

## Evidence and its limits

Everything marked **[verified]** was read from source in a shallow clone of the
project on 2026-08-13, or pulled from the GitHub API on the same date.
**[reported]** means it comes from the project's own README, docs, or model
catalog metadata and was not independently confirmed. **[inference]** is
reasoning, not measurement.

**No application was installed, built, or benchmarked.** There are no measured
latency, CPU, or RSS numbers anywhere in this document. Every performance claim
is vendor-reported metadata. Before committing to an engine, run the real
benchmark on target hardware — that gap is the single largest hole in this
evaluation.

## Verdict

Do not fork any of the three candidates. Add `sherpa-onnx` + `silero-vad` as an
opt-in module with download-on-demand models, and wire the result into the
existing snippet pipeline rather than beside it.

Rationale in [Why not a fork](#why-not-a-fork) and
[Proposed shape](#proposed-shape).

## Candidates evaluated

| | Handy | Buzz | OpenWhispr |
|---|---|---|---|
| Repo | `cjpais/Handy` | `chidiwilliams/buzz` | `OpenWhispr/openwhispr` |
| Stars / created | 29.4k · 2025-02 | 20.9k · 2022-09 | 5.4k · 2025-06 |
| Latest release | v0.9.5 · 2026-08-08 | v1.4.4 · 2026-03-14 | v1.8.3 · 2026-08-13 |
| Open issues | 152 | 22 | 287 |
| Stack | Rust + Tauri 2 | Python + PyQt | Electron 41 + JS |
| License | MIT | MIT | MIT |
| Hotkey → type into active app | yes | **no** | yes |
| Telemetry | none found | **PostHog, default on** | opt-in, default off |
| Account required | no | no | optional, skippable |
| Hidden cost | none | none | 2k words/week free cap (cloud path only) |

All figures **[verified]** via GitHub API, 2026-08-13.

### Handy — strongest of the three

- **No telemetry.** Grepped the full Rust and TypeScript tree for PostHog,
  Sentry, Amplitude, Segment, and Google Analytics. No hits, and no analytics
  SDK among the dependencies. **[verified]**
- **Cloud post-processing is opt-in and off.** `default_post_process_enabled()`
  returns `false` in `src-tauri/src/settings.rs:593`. The OpenAI / Anthropic /
  Groq / DeepSeek endpoints present in the tree are BYOK LLM cleanup of already
  transcribed text, not the transcription path. **[verified]**
- **Model downloads are SHA256-verified against a catalog compiled into the
  binary**, which serves as the trust anchor; mirror entries lacking a hash are
  rejected. Updates are minisign-signed, served from GitHub releases.
  **[verified]** This is a stronger supply-chain posture than most commercial
  equivalents and is the single most worthwhile pattern to copy.
- **Security-aware code.** `secure_input.rs` handles macOS Secure Event Input
  with an explicit guarantee that key identity is never logged. API keys are
  redacted in `Debug` output, with tests asserting it. **[verified]**
- **Tauri capabilities are scoped** — filesystem access limited to `$APPDATA`
  rather than the whole disk. **[verified]**

Weaknesses: `"csp": null` in `tauri.conf.json` (no Content-Security-Policy) and
an `assetProtocol` scope of `**`. Low practical risk given the frontend loads
only bundled local assets **[inference]**. BYOK API keys are stored in the Tauri
store as plaintext JSON under `%APPDATA%` rather than in Windows Credential
Manager — only relevant if post-processing is enabled **[verified]**.

Model catalog: 67 entries **[verified]**, current generation (Parakeet TDT v3,
Qwen3-ASR, Canary, Nemotron Streaming, Moonshine, Whisper). Sizes below are the
default quantization for each; the speed and accuracy scores are Handy's own
catalog metadata and **are not independent benchmarks** **[reported]**.

| Model | Default quant | Size | Langs | pt | Speed | Acc |
|---|---|---|---|---|---|---|
| Canary 180M Flash | Q8_0 | 218 MB | 4 | no | 98 | 88 |
| Parakeet Unified EN 0.6B | Q8_0 | 731 MB | 1 | no | 79 | 90 |
| Nemotron Streaming 3.5 | Q8_0 | 751 MB | 28 | **yes** | 84 | 82 |
| Whisper Medium | Q8_0 | 832 MB | 99 | **yes** | 42 | 84 |
| Cohere Transcribe | Q5_K_M | 1.77 GB | 14 | **yes** | 63 | 92 |

Parakeet TDT 0.6B v3 (25 languages, pt included) is also in the catalog and is
the likely pt-BR + English choice. **[verified]**

### Buzz — wrong category

Buzz has **no global hotkey and no injection into the active application**. Its
only output paths are clipboard copy and the transcript viewer. It is a
transcription studio — files, YouTube URLs, diarization, SRT export — not a
dictation layer. **[verified]** It cannot serve as the basis for this feature
regardless of its other qualities.

Separately, worth knowing: it reports to PostHog on every launch.

```python
# buzz/widgets/application.py:83
posthog.capture(distinct_id=self.settings.get_user_identifier(), event="app_launched",
                properties={app, locale, system, release, machine, version})
```

Persistent UUID, on by default, opt-out only via the `BUZZ_DISABLE_TELEMETRY`
environment variable — documented in `docs/preferences.md`, not the README.
No audio or transcript content is transmitted. **[verified]**

Its residual value to us is packaging know-how, covered below.

### OpenWhispr — open-core, not community open source

Functionally the closest competitor to Handy and genuinely cross-platform, but
the repo contains `WorkspaceBillingCard`, `UpgradePrompt`, `useBillingPortal`,
`InviteTeammateDialog`, plan tiers free/pro/team/business/enterprise, and hosted
`auth.openwhispr.com` / `api.openwhispr.com` with Google and Microsoft OAuth.
**[verified]**

- Paid tier: "Upgrade to Pro — unlimited transcriptions from as little as
  $8/month", gated behind a rolling 2,000 words/week cap. The cap applies **only
  to their hosted cloud transcription**; local models and BYOK are unlimited,
  and the sign-in step is skippable (`skipAuth` in `OnboardingFlow.tsx`).
  **[verified]** Honest, but the roadmap is steered by a commercial tier.
- Credential handling is **better than Handy's** — OS keychain first, Electron
  `safeStorage` fallback, in `src/helpers/secretCrypto.js`. Has a `SECURITY.md`
  with a 48h acknowledgement / 7d critical-fix SLA. **[verified]**
- Electron hardening is **worse**: two windows (Control Panel, floating overlay)
  run with `webSecurity: false`, disabling same-origin policy, to allow
  `file://`-origin fetches to auth and model APIs without CORS. The in-code
  rationale is honest but a main-process proxy would avoid it.
  `contextIsolation: true` and `nodeIntegration: false` throughout limit the
  blast radius. **[verified]**
- 287 open issues against 1,943 commits in ~14 months. **[verified]**

### Others surveyed

- **FluidVoice** (9.8k stars, GPL-3.0) and **VoiceInk** (5.9k stars,
  non-standard license, $39.99) — both **macOS-only**, and both license-hostile
  to a closed-source codebase. **[verified]**
- **WhisperWriter** (1.1k stars) is recommended by most "best of 2026" listicles
  and has had **no commit since 2024-08**. Unmaintained. **[verified]**
- Every other Windows-capable option is under 500 stars: `opentypeless` (447),
  `infiniV/VoiceFlow` (406), `VoiceSnap` (82), `drajb/whisper-local` (22, already
  stale). **[verified]**

**Search-result warning:** queries for "open source Wispr Flow alternative"
surface articles from `whisperstream.io`, `speakoflow.com`, `voicekeyboardpro.com`,
`getvoibe.com`, and `heymumble.com` — all competing paid products publishing
their own rankings. Treat as marketing. All findings here come from the repos.

## Why not a fork

Forking imports an entire application to obtain one subsystem, and commits us to
its upgrade path indefinitely. Concretely:

- **Handy** is Rust + Tauri. Consuming it means either rewriting Txt Xpander in
  Rust or shipping and maintaining a Rust sidecar process.
- **OpenWhispr** is Electron + JavaScript, and open-core.
- **Buzz** is the only stack match (Python, MIT) and is the wrong product
  category entirely.

The subsystem we actually need is audio capture, VAD, and inference — available
directly as libraries, without the surrounding application.

## What Txt Xpander already provides

The expensive parts of a dictation app are already built and shipping.
**[verified]**

| Dictation requirement | Existing implementation |
|---|---|
| Global hotkey listener | `pynput` listener, `txt_xpander.pyw:3593` |
| Inject text into focused app | `clipboard_support.py` paste path, incl. rich text |
| Capture / restore frontmost app | `platform_support.capture_frontmost_application()` |
| macOS secure input + permissions | `macos_permissions.py`, secure-input hot-path fix |
| Tray, autostart, installer, cross-platform | already shipping |

Missing: **audio capture → VAD → inference**. That is a module, not a fork.

## Proposed shape

Not yet approved. Adding any of these changes the dependency set and needs
sign-off per the global dependency policy.

- **`sherpa-onnx`** (Apache-2.0) — Parakeet TDT v3, runs on `onnxruntime`, which
  the bundle already carries. Python bindings, no PyTorch requirement, CPU-only,
  ~750 MB model, pt-BR supported. This is the engine Handy and OpenWhispr use
  for Parakeet. **[inference]** that it is the best fit — unbenchmarked.
- **`silero-vad`** for endpointing — small ONNX model on the same runtime.
- **`sounddevice`** for capture.

Patterns to copy from Handy (MIT permits reuse with attribution):

1. **SHA256-pinned model catalog compiled into the binary** as trust anchor.
   We would be downloading a ~750 MB blob onto user machines; this is the
   correct way to do it.
2. **Download models on first use into `%APPDATA%`**, never bundled. Keeps the
   installer lean and makes voice a genuinely optional component.
3. **Any cloud post-processing off by default.** Capture stays local; cleanup is
   opt-in.

Reference **Buzz's build tooling** (`Buzz.spec`, `hatch_build.py`,
`installer.iss`) for whisper.cpp/ffmpeg packaging on Windows, which is the
genuinely painful part. Take nothing else from it.

### Licensing constraint

Txt Xpander is closed-source. Handy, Buzz, and OpenWhispr are all MIT and safe
to draw from with attribution. **FluidVoice is GPL-3.0** and VoiceInk's license
is non-standard — do not copy from either. **[verified]**

## The product argument

A plain dictation feature is not worth building: Handy already does it well,
free, and composes with us today — it types into the focused field, we expand
triggers in the focused field. Dictating a trigger name already works with zero
code from us. **[inference — untested, and worth testing before any build.]**

The version that justifies the work is voice as an **input method for the
expander**: dictate into a snippet form field, speak a trigger to fire a
mapping, dictate into a variable and let `variable_support.py` and
`rich_text_support.py` handle it. That composition is unavailable to Handy or
Wispr Flow, and it is the only argument for the feature living here rather than
in a separate app running alongside.

## Side finding — PyInstaller is over-collecting

Unrelated to voice, found while measuring bundle weight. **[verified]**

`dist/Txt Xpander/_internal` contains:

```
torch          365 MB
cv2             99 MB
scipy           51 MB
transformers    42 MB
onnxruntime     34 MB
torchvision     12 MB
```

No source file imports `torch`, `cv2`, `transformers`, `onnxruntime`, `scipy`,
`numpy`, or `pandas` directly — `pandas`/`numpy` arrive legitimately via
`yfinance`, but `torch`, `cv2`, `transformers`, and `torchvision` do not appear
to be reachable at all. `Txt Xpander.spec` has `excludes=[]`, so PyInstaller is
collecting from global site-packages. **[inference]** on the cause; the import
absence and the sizes are measured.

Effect: roughly 520 MB of dead weight in the 215 MB installer / 821 MB unpacked
bundle, present since at least 3.0.0. A populated `excludes` list should bring
the installer closer to ~40 MB.

This should be fixed independently of any voice work — and doing so first means
STT dependencies land in a bundle that is honest about its own size.

## Open questions

1. Does Handy-alongside-Txt-Xpander already solve the need? Untested; cheapest
   possible outcome. **Test before writing code.**
2. Real latency, CPU, and RSS for Parakeet TDT v3 via `sherpa-onnx` on target
   Windows hardware. No numbers exist yet.
3. pt-BR accuracy for Parakeet v3 vs Whisper Medium on actual dictation, not
   benchmark audio.
4. Does the ~750 MB model download survive contact with real users, or does
   voice need a smaller default with the large model as an upgrade?

## Next steps

1. Fix `excludes=[]` in the spec — independent, and a bug in shipped releases.
2. Run the compose test (question 1) before any implementation.
3. If proceeding: benchmark `sherpa-onnx` + Parakeet v3 on Windows before the
   dependency-set discussion.
