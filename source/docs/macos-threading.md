# macOS tray + Tk threading model

Investigation spike for [issue #24](https://github.com/rteoo/txt_xpander/issues/24):
resolve how the pystray tray loop and the Tcl/Tk root coexist on macOS, where
both frameworks demand the main thread.

> **STATUS: analysis complete, ON-MAC VERIFICATION OUTSTANDING.**
> This document was produced on Windows. Every macOS runtime claim below is
> reasoned from framework contracts and the pystray 0.19.5 API — **none of it
> has been executed on a real Mac.** The recommended model must be validated
> against the verification checklist at the end before issue #24 can close.
> Nothing here changes the Windows code path; no code has been modified.

## The collision

On Windows the process runs two event loops on two threads and it works:

- `main()` → `TextExpander.run()` → `pystray.Icon.run()` **blocks the main
  thread** with the win32 message loop (`txt_xpander.pyw`, end of `run()`).
- The process's only `tk.Tk()` root lives on a **dedicated worker thread**
  (`gui_thread.py`, class `GuiThread`). Workers marshal onto it with
  `call`/`submit`; a `root.after(40ms, …)` pump drains the queue. Tk on Windows
  tolerates living on a non-main thread as long as *one* thread owns it.
- The pynput listener runs on its own thread and never touches Tk.

macOS breaks the "two loops, two threads" assumption on two independent counts:

1. **AppKit owns the main thread.** pystray's `darwin` backend drives an
   `NSApplication` / `NSRunLoop`. Cocoa requires that loop to run on thread 0
   (the main thread). This is not a pystray choice; it is an AppKit invariant.
2. **Aqua Tk owns the main thread.** The macOS Tk build (Aqua) is itself a Cocoa
   application: creating a `tk.Tk()` instantiates the shared `NSApplication`, and
   Tk's event handling is only reliable on the main thread. Off-main-thread Tk on
   macOS crashes or misrenders — the exact failure mode `GuiThread` relies on
   *not* happening on Windows.

So both frameworks want the main thread, and both want to run an
`NSApplication` loop. The saving grace — and the hinge of the whole design — is
that **there is only one `NSApplication` per process** (`+sharedApplication` is a
singleton). Tk creates it; pystray can be told to reuse it instead of trying to
own its own.

## The invariant that must survive

Whatever lands, the `GuiThread` public contract is load-bearing and must not
change (AGENTS.md, and every worker in the expansion path depends on it):

- Workers call `GuiThread.call(func, timeout)` (blocking, returns the result,
  re-raises) and `GuiThread.submit(func)` (fire-and-forget).
- The keyboard listener **never** calls into Tk.
- There is exactly one `tk.Tk()` in the process.

What may change is the *physical thread* the pump runs on. On Windows it is a
spawned worker thread; on macOS it must become the main thread. The marshaling
API is identical either way — `call`/`submit` push onto a queue drained by a
`root.after` pump; the pump does not care which thread it ticks on, only that
all Tk access is funnelled through it. This is why the abstraction was built the
way it was, and it is what makes the port tractable.

## Options evaluated

### Option 1 — main thread runs Tk `mainloop()`, tray runs detached (RECOMMENDED)

Invert ownership on macOS:

1. On the main thread, create the single `tk.Tk()` root (this instantiates the
   shared `NSApplication`).
2. Obtain that singleton: `AppKit.NSApplication.sharedApplication()`.
3. `icon.run_detached(darwin_nsapplication=<that NSApplication>)` — pystray
   0.19.5's own `run_detached` docstring documents exactly this parameter for
   macOS: *"Pass an instance of `NSApplication` retrieved from the library with
   which you are integrating … This will allow this library to integrate with
   the main loop."* pystray then schedules its status-item work onto the shared
   run loop instead of starting a second one.
4. Enter `root.mainloop()` on the main thread. That drives the shared
   `NSRunLoop`; the detached tray rides it; the `root.after` pump keeps draining
   the `GuiThread` queue.

`GuiThread` stays the public surface. On macOS `ensure_started()` does **not**
spawn a thread — it designates the main thread as the GUI thread, installs the
pump, and returns; the blocking `root.mainloop()` is what `run()` enters instead
of `icon.run()`. `call`/`submit` are unchanged. The keyboard listener still
never touches Tk.

Why this is the bet: it is the only option where each framework runs on the
thread it demands **and** the two share the one `NSApplication` the platform
allows, using an integration seam pystray ships specifically for it. No second
event loop, no off-main-thread Tk.

Risk / unknowns to close on the Mac:
- Exact call signature: confirm whether `darwin_nsapplication` is a kwarg to
  `run_detached` or must be set on the icon first, against the *installed*
  pystray version (the base signature is `run_detached(self, setup=None)`; the
  darwin subclass consumes the extra kwarg).
- The `setup=` callback fires on a **separate thread** (per the docstring) — it
  must not touch Tk directly; route any tray-ready work through `GuiThread`.
- Confirm `pyobjc` (`AppKit`) is present; pystray's darwin backend already pulls
  it in, so this is likely a transitive dependency, not a new top-level one.

### Option 2 — keep `icon.run()` on main, keep `GuiThread` off-main (LIKELY FAILS, cheap to test)

Change nothing but the platform seam: let pystray block the main thread as on
Windows and leave the Tk root on its worker thread. This is attractive only
because it is zero architectural change. It puts Tk off the main thread on
macOS, which is precisely the unsupported configuration. Expected outcome:
crashes or beachballs on the first dialog. Worth a 15-minute empirical check on
the Mac purely to confirm the failure and rule it out — do not build on it.

### Option 3 — macOS-native tray backend behind a `platform_support` seam (does not solve the core problem)

Swap pystray for a native menubar library (e.g. `rumps`) on macOS, kept behind a
seam so Windows/Linux stay on pystray. This does **not** dissolve the collision:
`rumps` also runs `NSApplication` on the main thread and still has to share it
with Aqua Tk — the same one-NSApplication problem, minus pystray's ready-made
`darwin_nsapplication` integration hook. It also adds a runtime dependency, which
per repo rules needs explicit approval, and it forks the tray/menu/autostart
surface across two libraries. Reserve as a fallback only if Option 1 proves that
pystray's darwin detached mode is broken on the target macOS/pystray combo.

## Recommendation

Pursue **Option 1**. Prototype it in this order on the Mac:

1. Minimal standalone script: `tk.Tk()` on main → get `sharedApplication()` →
   `pystray.Icon(...).run_detached(darwin_nsapplication=app)` → `root.mainloop()`.
   Prove a menu renders and a `root.after`-scheduled `Toplevel` opens without a
   crash. This isolates the framework question from the app.
2. If step 1 holds, wire it into a macOS branch of `TextExpander.run()` and a
   macOS mode of `GuiThread` (main-thread pump, no spawned thread). Keep the
   Windows path byte-for-byte unchanged behind `platform_support.current_os()`.
3. If step 1 fails, drop to Option 2 for one confirming test, then Option 3.

The seam belongs in `platform_support.py` (which already centralizes
`pin_tray_backend`, paste modifier, autostart), with `run()` and `GuiThread`
branching on it — not scattered `sys.platform` checks.

## Verification checklist (issue #24 acceptance criteria — DO ON A REAL MAC)

- [ ] Tray icon renders in the menu bar with a working menu.
- [ ] "Gerenciar Snippets" opens the manager window (a Tk `Toplevel`).
- [ ] An expansion dialog (e.g. a form-variable prompt, or `ask_ticker_input`)
      shows and returns a value to the worker thread via `GuiThread.call`.
- [ ] No crashes, no beachballs across the above.
- [ ] Keyboard listener still expands a trigger with no Tk contact.
- [ ] `GuiThread.call`/`submit` semantics unchanged (blocking result + re-raise;
      fire-and-forget).
- [ ] Windows regression: full suite green on Windows after the seam lands
      (`cd source && python -m unittest discover -s tests`). Baseline at time of
      writing: **424 tests, OK (1 skipped).**

## References

- `source/gui_thread.py` — the pump + marshaling contract to preserve.
- `source/platform_support.py` — where the OS seam belongs.
- `source/txt_xpander.pyw` — `TextExpander.run()` (tray + listener startup) and
  `main()`.
- pystray 0.19.5 `Icon.run_detached` docstring — the `darwin_nsapplication`
  integration contract this design rests on.
