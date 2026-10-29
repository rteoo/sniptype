// Client side of source/manager_bridge.py. Requests leave through the Rust
// `bridge_send` command (one JSON line on stdout); answers and app events
// arrive as the `bridge` event (one JSON line read from stdin).
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface Issue { id: string; severity: string; title: string; body: string }

export interface AppInfo {
  version: string;
  channel: string;
  language: string;
  languages: Record<string, string>;
  appearance: "system" | "light" | "dark";
  density: "compact" | "comfortable" | "touch";
  terminatorMode: boolean;
  dataDir: string;
  issues: Issue[];
}

export interface LibraryItem {
  trigger: string;
  effectiveTrigger: string;
  group: string | null;
  favorite: boolean;
  enabled: boolean;
  shadowed: boolean;
  rich: boolean;
  preview: string;
}

export interface Snippet { trigger: string; text: string; rich: boolean }

export type SaveCheck = "replace" | "warnings";
export type SaveAnswer =
  | { status: "saved"; trigger: string }
  | { status: "confirm"; check: SaveCheck; title: string; message: string; action: string };

export interface MappingType { key: string; label: string; prefix: string; builtin: boolean; count: number }

export interface MappingItem { name: string; effectiveTrigger: string; favorite: boolean; rich: boolean; preview: string }

export interface MappingEntry { type: string; name: string; text: string; rich: boolean; effectiveTrigger: string }

export type MappingSaveAnswer =
  | { status: "saved"; type: string; name: string }
  | { status: "confirm"; check: SaveCheck; title: string; message: string; action: string };

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
