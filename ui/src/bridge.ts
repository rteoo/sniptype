// Client side of source/manager_bridge.py. Requests leave through the Rust
// `bridge_send` command (one JSON line on stdout); answers and app events
// arrive as the `bridge` event (one JSON line read from stdin).
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface Issue {
  id: string; severity: string; title: string; body: string;
  /** The one recovery action (health_support), with its written label; null when there is none. */
  action: string | null; actionLabel: string | null; dismissible: boolean;
}

export type ExpansionState = "ok" | "paused" | "down";

export interface AppInfo {
  version: string;
  channel: string;
  language: string;
  languages: Record<string, string>;
  appearance: "system" | "light" | "dark";
  density: "compact" | "comfortable" | "touch";
  terminatorMode: boolean;
  dataDir: string;
  expansion: { state: ExpansionState; label: string };
  lastExpansion: string;
  canEditLast: boolean;
  hotkeys: Hotkey[];
  /** Where the window was last (physical pixels), and its page; {} the first time. */
  window: WindowState;
  transfers: Transfer[];
  issues: Issue[];
}

/** One Ctrl+K row: the item it opens and how it reads. */
export interface SwitcherRow {
  kind: "static" | "mapping" | "dynamic"; key: string; container: string | null;
  label: string; trigger: string; preview: string;
}

export interface HealthAnswer { page: string | null; receipt: string | null }

/** Cópia espelho (`copy`) or Pacote de sincronização (`export`): its folder, and what the last run did. */
export interface Transfer { kind: "copy" | "export"; dir: string | null; status: string | null; failed: boolean }

export interface Notice { when: string; kind: string; kindLabel: string; message: string }

export interface WindowState {
  x?: number; y?: number; width?: number; height?: number; maximized?: boolean; page?: string;
}

/** One workflow hotkey: `binding` is the stored pynput syntax (null when off), `display` how it reads. */
export interface Hotkey { action: string; label: string; binding: string | null; display: string }
export type HotkeySaveAnswer =
  | { status: "saved"; hotkeys: Hotkey[] } | { status: "invalid"; field: string; message: string };

export interface LibraryItem {
  trigger: string;
  effectiveTrigger: string;
  groupId: string | null;
  group: string | null;
  favorite: boolean;
  enabled: boolean;
  shadowed: boolean;
  rich: boolean;
  /** The text presses Enter or Tab when it expands. */
  keys: boolean;
  preview: string;
}

/** A filtered view of the static library; `total` counts every static snippet. */
export interface Library { items: LibraryItem[]; total: number }

export type ListFilter = "all" | "favorites" | "recent" | "disabled" | "problems";

export interface StyleSpan { tag: "bold" | "italic" | "underline" | "code" | "strike"; start: number; end: number }

export interface Snippet {
  trigger: string; text: string; rich: boolean; spans: StyleSpan[]; effectiveTrigger: string; favorite: boolean;
  groupId: string | null;
  /** Fingerprint of the stored value: a save sends it back as `base`, so a newer version is never overwritten unasked. */
  revision: string;
}

export type SaveCheck = "replace" | "warnings" | "shadow" | "stale";
export type Confirmation = { status: "confirm"; check: SaveCheck; title: string; message: string; action: string };
export type SaveAnswer = { status: "saved"; trigger: string; revision: string } | Confirmation;

/** What the library holds now under an open draft's item (editor_session.reconcile). */
export interface DraftCheck { status: "unchanged" | "changed" | "gone"; revision: string | null }

export type CopyAnswer = { status: "duplicated"; trigger: string } | { status: "invalid"; message: string };
export type RenameAnswer =
  | { status: "renamed"; trigger: string } | { status: "invalid"; message: string } | Confirmation;

export interface Group { id: string; label: string; prefix: string; enabled: boolean; count: number }
export interface Groups { readOnly: boolean; groups: Group[] }

export interface Choice { value: string; label: string }
export interface GroupValues {
  label: string; notes: string; prefix: string; enabled: boolean;
  terminator: string; application_mode: string; executables: string;
}
export interface GroupForm {
  values: GroupValues; terminators: Choice[]; applicationModes: Choice[]; windowsNote: string;
}
export type GroupSaveAnswer =
  | { status: "saved"; id: string; label: string }
  | { status: "invalid"; field: keyof GroupValues; message: string };

export interface DynamicItem { key: string; trigger: string; description: string; enabled: boolean }
export interface DynamicSection { id: string; label: string; items: DynamicItem[] }
export type DynamicToggleAnswer = { status: "saved"; key: string; enabled: boolean } | Confirmation;
export type DynamicRenameAnswer =
  | { status: "renamed"; key: string; trigger: string } | { status: "invalid"; message: string } | Confirmation;

export interface FormFieldDef {
  name: string; type: string; default: string | boolean; label?: string;
  options?: string[]; content?: string; output_format?: string;
}
export interface FormInfo {
  saved: boolean; fields: FormFieldDef[]; variables: string[]; types: Choice[]; dateFormat: string; readOnly: boolean;
}
export type FormSaveAnswer =
  | { status: "saved"; count: number } | { status: "invalid"; message: string; index: number | null };
export interface Preview { text: string; status: string }

/** What `%%name%%` can reference, by the name the app resolves. */
export interface Variable { name: string; detail: string }
export interface Variables { snippets: Variable[]; dynamics: Variable[]; mappings: Variable[] }

export interface ChangeCounts { new: number; overwritten: number; removed: number }
export interface Backup {
  name: string; when: string; texts: number | null; lists: number | null; size: number; empty: boolean;
}
export interface BackupPreview { name: string; when: string; counts: ChangeCounts }
export interface ImportCounts { merge: ChangeCounts; replace: ChangeCounts }

export interface MappingType { key: string; label: string; prefix: string; builtin: boolean; count: number }

export interface MappingItem {
  name: string; effectiveTrigger: string; favorite: boolean; rich: boolean; keys: boolean; preview: string;
}

export interface MappingEntry {
  type: string; name: string; text: string; rich: boolean; spans: StyleSpan[]; effectiveTrigger: string;
  favorite: boolean; revision: string;
}

export type MappingSaveAnswer = { status: "saved"; type: string; name: string; revision: string } | Confirmation;

export type CreateTypeAnswer =
  | { status: "created"; key: string }
  | { status: "invalid"; field: "name" | "prefix"; message: string };

export class BridgeError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

// The app answers on its GUI thread; a request that outlives this is a hung
// app, and the person gets told instead of a frozen window.
const REQUEST_TIMEOUT_MS = 30_000;

interface Pending { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: number }

const pending = new Map<number, Pending>();
let nextId = 1;

export async function startBridge(onEvent: (name: string) => void): Promise<void> {
  await listen<string>("bridge", (event) => {
    let message: { id?: number; result?: unknown; error?: { code: string; message: string }; event?: string };
    try {
      message = JSON.parse(event.payload);
    } catch {
      console.error("bridge: line is not JSON", event.payload);
      return;
    }
    if (typeof message.event === "string") {
      onEvent(message.event);
      return;
    }
    const waiter = message.id === undefined ? undefined : pending.get(message.id);
    if (!waiter) {
      console.error("bridge: answer for no request", message);
      return;
    }
    pending.delete(message.id!);
    window.clearTimeout(waiter.timer);
    if (message.error) waiter.reject(new BridgeError(message.error.code, message.error.message));
    else waiter.resolve(message.result);
  });
}

export function request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pending.delete(id);
      reject(new BridgeError("timeout", `${method}: no answer from SnipType`));
    }, REQUEST_TIMEOUT_MS);
    pending.set(id, { resolve: resolve as (value: unknown) => void, reject, timer });
    invoke("bridge_send", { line: JSON.stringify({ id, method, params }) }).catch((error) => {
      pending.delete(id);
      window.clearTimeout(timer);
      reject(new BridgeError("send_failed", String(error)));
    });
  });
}
