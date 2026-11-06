import "./styles/teo/foundations.css";
import "./styles/teo/elements.css";
import "./styles/teo/windows-tokens.css";
import "./styles/teo/windows-elements.css";
import "./styles/app.css";

import { availableMonitors, getCurrentWindow, PhysicalPosition, PhysicalSize } from "@tauri-apps/api/window";

import {
  type AppEvent, type AppInfo, type Backup, type BackupPreview, BridgeError, type ChangeCounts, type Choice, type Confirmation,
  type CopyAnswer, type CreateTypeAnswer, type DraftCheck, type ImportCounts,
  type DynamicRenameAnswer, type DynamicSection, type DynamicToggleAnswer, type FormFieldDef, type FormInfo,
  type FormSaveAnswer, type Group, type HealthAnswer, type HotkeySaveAnswer, type Preview,
  type GroupForm, type Groups, type GroupSaveAnswer, type Library, type ListFilter, type MappingEntry,
  type MappingItem, type MappingSaveAnswer, type MappingType, type Notice, type RenameAnswer, type SaveAnswer,
  type SaveCheck,
  type Snippet, type SwitcherRow, type Transfer, type Variable, type Variables, type WindowState, request,
  startBridge,
} from "./bridge";
import { attachCompletion, type Candidate } from "./completion";
import { h, icon } from "./dom";
import { setLanguage, t } from "./i18n";
import { createRichEditor, type RichEditor, type Span, type Style } from "./richtext";

type Kind = "textos" | "mapeamentos";
type Page = Kind | "dinamicos" | "backups" | "settings";

/** One row of a collection: a static snippet, or an item of the selected mapping type. */
interface Item {
  name: string;
  effectiveTrigger: string;
  preview: string;
  rich: boolean;
  keys: boolean;
  favorite: boolean;
  group?: string | null;
  enabled?: boolean;
  shadowed?: boolean;
}

/** A saved item as the editor opens it, metadata included (the list may be filtered). */
interface Entry { name: string; text: string; rich: boolean; spans: Span[]; effectiveTrigger: string;
  favorite: boolean; groupId: string | null; revision: string }

/**
 * What an editor holds. `original` is the saved name it was opened from (null
 * for a new one); `type` is the mapping type a Mapeamentos draft belongs to.
 * `spans` are the text's styles (`savedSpans` as JSON, to compare); `rich`
 * says it has any. `favorite`, `groupId` and `effectiveTrigger` describe the saved item and
 * change at once, never as part of the draft. `formFrom` names the mapping
 * item a Duplicar copy came from, whose form the first save carries over.
 */
interface Draft {
  type: string | null;
  original: string | null;
  name: string;
  text: string;
  spans: Span[];
  rich: boolean;
  savedName: string;
  savedText: string;
  savedSpans: string;
  favorite: boolean;
  groupId: string | null;
  effectiveTrigger: string;
  formFrom?: string | null;
  /** Revision of the saved item the draft was opened at (null for a new one); saves send it as `base`. */
  revision: string | null;
}

interface Receipt { text: string; undo?: () => Promise<void> }

interface Collection { items: Item[]; total: number; query: string; draft: Draft | null; receipt: Receipt | null }

type Saved = { status: "saved"; name: string; revision: string };

/** How each collection reaches the app, so both pages share one list and editor. */
interface Source {
  list(): Promise<{ items: Item[]; total: number }>;
  get(name: string): Promise<Entry>;
  save(draft: Draft, confirmed: SaveCheck[]): Promise<Saved | Confirmation>;
  remove(draft: Draft): Promise<string>;
  undo(token: string): Promise<unknown>;
  setFavorite(draft: Draft, favorite: boolean): Promise<unknown>;
}

const listFilters = (): [ListFilter, string][] => [
  ["all", t("Todos")], ["favorites", t("Favoritos")], ["recent", t("Recentes")], ["disabled", t("Desativados")],
  ["problems", t("Com problema")],
];
// The group selector's value for snippets in no group (source/manager_bridge.py).
const UNGROUPED = "__ungrouped__";

const appWindow = getCurrentWindow();
const lightScheme = matchMedia("(prefers-color-scheme: light)");
const root = document.getElementById("app")!;

const blank = (): Collection => ({ items: [], total: 0, query: "", draft: null, receipt: null });

const state = {
  info: null as AppInfo | null,
  page: "textos" as Page,
  collections: { textos: blank(), mapeamentos: blank() } as Record<Kind, Collection>,
  types: [] as MappingType[],
  type: "_cpf_numbers",
  groups: [] as Group[],
  groupsReadOnly: false,
  // Textos' view: a list filter and a group ("" for every group, UNGROUPED for none).
  view: { filter: "all" as ListFilter, group: "" },
  cardStatus: {} as Record<string, { text: string; error: boolean }>,
  dynamics: { sections: [] as DynamicSection[], query: "", receipt: "" },
  settingsReceipt: "",
  backups: { items: [] as Backup[], receipt: "" },
};

const refs = {
  infobar: null as HTMLElement | null,
  hiddenNote: null as HTMLElement | null,
  status: null as HTMLElement | null,
  items: null as HTMLElement | null,
  count: null as HTMLElement | null,
  detail: null as HTMLElement | null,
  saveState: null as HTMLElement | null,
  saveButton: null as HTMLButtonElement | null,
  effective: null as HTMLElement | null,
  receipt: null as HTMLElement | null,
  search: null as HTMLInputElement | null,
  viewBar: null as HTMLElement | null,
  meta: null as HTMLElement | null,
};

const sources: Record<Kind, Source> = {
  textos: {
    list: async () => {
      const library = await request<Library>("library.list", {
        filter: state.view.filter, group: state.view.group || null,
      });
      return { items: library.items.map((item) => ({ ...item, name: item.trigger })), total: library.total };
    },
    get: async (name) => {
      const snippet = await request<Snippet>("snippet.get", { trigger: name });
      return { ...snippet, name: snippet.trigger };
    },
    save: async (draft, confirmed) => {
      const answer = await request<SaveAnswer>("snippet.save", {
        trigger: draft.name, text: draft.text, spans: draft.spans, original: draft.original, confirmed,
        base: draft.revision,
      });
      return answer.status === "saved" ? { status: "saved", name: answer.trigger, revision: answer.revision } : answer;
    },
    remove: async (draft) =>
      (await request<{ undoToken: string }>("snippet.delete", { trigger: draft.original })).undoToken,
    undo: (token) => request("snippet.undoDelete", { token }),
    setFavorite: (draft, favorite) => request("snippet.setFavorite", { trigger: draft.original, favorite }),
  },
  mapeamentos: {
    list: async () => {
      const items = await request<MappingItem[]>("mapping.list", { type: state.type });
      return { items, total: items.length };
    },
    get: async (name) => ({ ...(await request<MappingEntry>("mapping.get", { type: state.type, name })), groupId: null }),
    save: async (draft, confirmed) => {
      const answer = await request<MappingSaveAnswer>("mapping.save", {
        type: draft.type, name: draft.name, text: draft.text, spans: draft.spans, original: draft.original, confirmed,
        formFrom: draft.formFrom ?? null, base: draft.revision,
      });
      return answer.status === "saved" ? { status: "saved", name: answer.name, revision: answer.revision } : answer;
    },
    remove: async (draft) =>
      (await request<{ undoToken: string }>("mapping.delete", { type: draft.type, name: draft.original }))
        .undoToken,
    undo: (token) => request("mapping.undoDelete", { token }),
    setFavorite: (draft, favorite) =>
      request("mapping.setFavorite", { type: draft.type, name: draft.original, favorite }),
  },
};

function viewActive(): boolean {
  return state.view.filter !== "all" || state.view.group !== "";
}

function readOnlyMessage(): string {
  return t("Os metadados da biblioteca são somente leitura nesta versão; favoritos, grupos e formulários não podem ser alterados.");
}

function isKind(page: Page): page is Kind {
  return page === "textos" || page === "mapeamentos";
}

function activeKind(): Kind | null {
  return isKind(state.page) ? state.page : null;
}

function currentType(): MappingType | undefined {
  return state.types.find((type) => type.key === state.type);
}

function typeLabel(key: string | null): string {
  return state.types.find((type) => type.key === key)?.label ?? key ?? "";
}

// ---------------------------------------------------------------------------
// Appearance

function applyAppearance(): void {
  const info = state.info;
  const preference = info?.appearance ?? "dark";
  const dark = preference === "system" ? !lightScheme.matches : preference === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.body.dataset.density = info?.density ?? "compact";
}

lightScheme.addEventListener("change", applyAppearance);

function clock(): string {
  return new Date().toLocaleTimeString(state.info?.language ?? "pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---------------------------------------------------------------------------
// Dialogs (ContentDialog): every question the window asks goes through here.

interface DialogButton { id: string; label: string; tone?: "primary" | "danger" }

function openDialog(dialog: HTMLDialogElement, focus: HTMLElement | null): void {
  const returnFocus = document.activeElement as HTMLElement | null;
  dialog.addEventListener("close", () => {
    dialog.remove();
    returnFocus?.focus();
  });
  document.body.append(dialog);
  dialog.showModal();
  focus?.focus();
}

function ask(title: string, message: string, buttons: DialogButton[]): Promise<string> {
  return new Promise((resolve) => {
    const dialog = h("dialog", { "aria-labelledby": "dialog-title" },
      h("h2", { id: "dialog-title" }, title),
      h("p", {}, message),
      h("menu", {}, ...buttons.map((button) => h("button", {
        type: "button",
        class: button.tone === "primary" ? "primary" : button.tone === "danger" ? "danger-fill" : undefined,
        onclick: () => dialog.close(button.id),
      }, button.label))),
    );
    // Escape and the backdrop mean the last, cancelling button.
    dialog.addEventListener("close", () => resolve(dialog.returnValue || buttons[buttons.length - 1].id));
    // With no primary action (a destructive question), Enter must land on the cancelling button.
    openDialog(dialog, dialog.querySelector("button.primary") ?? dialog.querySelector("menu button:last-child"));
  });
}

function alertError(title: string, error: unknown): Promise<string> {
  return ask(title, errorText(error), [{ id: "ok", label: t("OK"), tone: "primary" }]);
}

type FieldValue = string | boolean;
type Values = Record<string, FieldValue>;

interface FormField {
  id: string;
  label: string;
  kind?: "text" | "textarea" | "select" | "switch";
  value?: FieldValue;
  options?: Choice[];
  hint?: string;
  mono?: boolean;
  /** The field shows only while this holds for the dialog's current values. */
  shownWhen?: (values: Values) => boolean;
}

type Problem = { field: string; message: string } | null;
type Control = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

function fieldControl(field: FormField, describedBy: string): Control {
  const common = { id: `dialog-${field.id}`, "aria-labelledby": `dialog-${field.id}-label`, "aria-describedby": describedBy };
  const textClass = field.mono ? "field mono" : "field";
  if (field.kind === "switch") {
    return h("input", { ...common, type: "checkbox", role: "switch", class: "el-switch", checked: field.value === true });
  }
  if (field.kind === "select") {
    return h("select", { ...common, class: "field" }, ...(field.options ?? []).map((option) =>
      h("option", { value: option.value, selected: option.value === field.value }, option.label)));
  }
  if (field.kind === "textarea") {
    return h("textarea", { ...common, class: textClass, rows: 3, spellcheck: "false", value: String(field.value ?? "") });
  }
  return h("input", {
    ...common, class: textClass, autocomplete: "off", spellcheck: "false", value: String(field.value ?? ""),
  });
}

/**
 * A dialog of fields. `submit` answers null to close, or the field and
 * message to show under it while the dialog stays open. `confirmWord` keeps
 * the submit button off until the first field holds exactly that word.
 */
function formDialog(options: {
  title: string; message?: string; fields: FormField[]; action: string; danger?: boolean; confirmWord?: string;
  submit: (values: Values) => Promise<Problem>;
}): Promise<boolean> {
  return new Promise((resolve) => {
    const controls = new Map<string, Control>();
    const rows = new Map<string, HTMLElement>();
    const errors = new Map<string, HTMLElement>();
    const submitButton = h("button", {
      type: "submit", class: options.danger ? "danger-fill" : "primary", disabled: !!options.confirmWord,
    }, options.action);
    const values = (): Values => Object.fromEntries([...controls].map(([id, control]) =>
      [id, control instanceof HTMLInputElement && control.type === "checkbox" ? control.checked : control.value]));
    const update = () => {
      const current = values();
      for (const field of options.fields) rows.get(field.id)!.hidden = !!field.shownWhen && !field.shownWhen(current);
      if (options.confirmWord) submitButton.disabled = String(current[options.fields[0].id]).trim() !== options.confirmWord;
    };
    let done = false;
    const dialog = h("dialog", { "aria-labelledby": "dialog-title" },
      h("form", {
        method: "dialog",
        oninput: (event: Event) => {
          (event.target as HTMLElement).removeAttribute("aria-invalid");
          update();
        },
        onsubmit: async (event: Event) => {
          event.preventDefault();
          submitButton.disabled = true;
          const problem = await options.submit(values());
          submitButton.disabled = false;
          for (const [id, element] of errors) element.textContent = id === problem?.field ? problem.message : "";
          if (problem) {
            controls.get(problem.field)?.setAttribute("aria-invalid", "true");
            controls.get(problem.field)?.focus();
            return;
          }
          done = true;
          dialog.close();
        },
      },
      h("h2", { id: "dialog-title" }, options.title),
      options.message ? h("p", {}, options.message) : null,
      ...options.fields.map((field) => {
        const error = h("span", { id: `dialog-${field.id}-error`, class: "error", role: "alert" });
        const hint = field.hint ? h("span", { class: "hint", id: `dialog-${field.id}-hint` }, field.hint) : null;
        const control = fieldControl(field, [hint?.id, error.id].filter(Boolean).join(" "));
        controls.set(field.id, control);
        errors.set(field.id, error);
        const label = h("span", { id: `dialog-${field.id}-label` }, field.label);
        // The family styles a switch only inside its .el-choice label.
        const row = field.kind === "switch"
          ? h("div", { class: "dialog-field" }, h("label", { class: "el-choice" }, control, label), hint, error)
          : h("label", { class: "dialog-field" }, label, control, hint, error);
        rows.set(field.id, row);
        return row;
      }),
      h("menu", {},
        submitButton,
        h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar"))),
      ),
    );
    update();
    const first = controls.values().next().value ?? null;
    openDialog(dialog, first);
    // After openDialog's own close listener, so focus is back where it was when a caller acts on the answer.
    dialog.addEventListener("close", () => resolve(done));
    if (first instanceof HTMLInputElement && first.type !== "checkbox") first.select();
  });
}

/**
 * A drop-down menu behind a labeled button with a chevron (DESIGN.md: never
 * icon-only). `entries` is read each time it opens, so it reflects the view.
 */
function menuButton(label: string,
  entries: () => { label: string; icon?: string; disabled?: boolean; run: () => void }[],
  attrs: Record<string, unknown> = {}, leading?: string): HTMLElement {
  const menu = h("div", { class: "menu", popover: "auto", role: "menu", "aria-label": label });
  const button = h("button", {
    type: "button", class: "el-button", "aria-haspopup": "menu", "aria-expanded": "false", ...attrs,
    onclick: () => {
      menu.replaceChildren(...entries().map((entry) => h("button", {
        type: "button", role: "menuitem", disabled: entry.disabled,
        onclick: () => {
          menu.hidePopover();
          // What the entry opens returns focus here when it closes.
          button.focus();
          entry.run();
        },
      }, entry.icon ? icon(entry.icon) : null, entry.label)));
      const box = button.getBoundingClientRect();
      menu.style.top = `${box.bottom + 4}px`;
      menu.style.left = `${box.left}px`;
      menu.showPopover();
      menu.querySelector<HTMLElement>("button:not([disabled])")?.focus();
    },
  }, leading ? icon(leading) : null, label, icon("chevron-down"));
  menu.addEventListener("toggle", (event) =>
    button.setAttribute("aria-expanded", String((event as Event & { newState: string }).newState === "open")));
  menu.addEventListener("keydown", (event) => {
    const items = [...menu.querySelectorAll<HTMLElement>("button:not([disabled])")];
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      items[(at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
    } else if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      // The popover is gone by the time the document hears it: that Esc must not also reach the editor.
      event.stopPropagation();
      menu.hidePopover();
      button.focus();
    }
  });
  return h("span", { class: "menu-anchor" }, button, menu);
}

// ---------------------------------------------------------------------------
// Data

async function refreshInfo(): Promise<void> {
  state.info = await request<AppInfo>("app.info");
  setLanguage(state.info.language);
  applyAppearance();
  renderInfobar();
  renderStatus();
}

/** Read the app again and the page on screen: the library or the app's state changed behind this window. */
async function refreshVisible(): Promise<void> {
  const kind = activeKind();
  const page = state.page;
  await refreshInfo();
  if (kind) {
    await refreshList(kind);
    await reconcileDraft(kind);
  }
  else if (page === "dinamicos") await refreshDynamics();
  else if (page === "backups") await refreshBackups();
}

async function refreshTypes(): Promise<void> {
  state.types = await request<MappingType[]>("mapping.types");
  if (!currentType()) state.type = state.types.find((type) => type.key === "_cpf_numbers")?.key ?? state.types[0]?.key;
}

async function refreshGroups(): Promise<void> {
  const answer = await request<Groups>("groups.list");
  state.groups = answer.groups;
  state.groupsReadOnly = answer.readOnly;
  // A group deleted elsewhere must not keep narrowing the list to nothing.
  if (state.view.group && state.view.group !== UNGROUPED && !state.groups.some((group) => group.id === state.view.group)) {
    state.view.group = "";
  }
}

async function refreshList(kind: Kind): Promise<void> {
  // Both pages need the groups' read-only flag; Textos also needs the groups.
  if (kind === "mapeamentos") await refreshTypes();
  await refreshGroups();
  const { items, total } = await sources[kind].list();
  Object.assign(state.collections[kind], { items, total });
  if (state.page === kind) {
    renderList();
    renderTypeBar();
    renderViewBar();
    renderMeta();
  }
}

function draftFrom(entry: Entry, type: string | null): Draft {
  return {
    type, original: entry.name, name: entry.name, text: entry.text, spans: entry.spans, rich: entry.rich,
    savedName: entry.name, savedText: entry.text, savedSpans: JSON.stringify(entry.spans),
    favorite: entry.favorite, groupId: entry.groupId, effectiveTrigger: entry.effectiveTrigger,
    revision: entry.revision,
  };
}

function newDraft(type: string | null, name: string, text = "", spans: Span[] = []): Draft {
  return {
    type, original: null, name, text, spans, rich: spans.length > 0, savedName: name, savedText: "", savedSpans: "[]",
    favorite: false, groupId: null, effectiveTrigger: name, revision: null,
  };
}

/** Read the saved item again after a change that moves its metadata or its trigger. */
async function reloadEntry(kind: Kind): Promise<void> {
  const draft = state.collections[kind].draft;
  if (!draft?.original) return;
  try {
    const entry = await sources[kind].get(draft.original);
    Object.assign(draft, { favorite: entry.favorite, groupId: entry.groupId, effectiveTrigger: entry.effectiveTrigger });
  } catch (error) {
    console.error("reload failed", error);
  }
}

function isDirty(kind: Kind): boolean {
  const draft = state.collections[kind].draft;
  if (!draft) return false;
  return draft.name.trim() !== draft.savedName || draft.text !== draft.savedText
    || JSON.stringify(draft.spans) !== draft.savedSpans;
}

let reconciling = false;

/**
 * The library changed behind the open editor (a tray reload, an outside edit, another window):
 * a clean editor shows the new version or empties; a draft asks, as the classic manager did.
 * Keeping the draft over a newer version moves its base there, so Salvar then overwrites knowingly.
 */
async function reconcileDraft(kind: Kind): Promise<void> {
  const draft = state.collections[kind].draft;
  if (reconciling || !draft?.original || draft.revision === null) return;
  reconciling = true;
  try {
    const check = await request<DraftCheck>("draft.check", {
      kind: kind === "textos" ? "static" : "mapping", key: draft.original, base: draft.revision, container: draft.type,
    });
    // The editor may have moved on while the app answered.
    if (state.collections[kind].draft !== draft || check.status === "unchanged") return;
    const name = draft.original;
    if (!isDirty(kind)) {
      const fresh = check.status === "gone" ? null : draftFrom(await sources[kind].get(name), draft.type);
      // Typing during that read made it a draft: keep it, and let the next refresh ask.
      if (state.collections[kind].draft !== draft || isDirty(kind)) return;
      state.collections[kind].draft = fresh;
      if (state.page === kind) { renderList(); renderDetail(); }
      return;
    }
    const gone = check.status === "gone";
    const choice = await ask(
      t("A biblioteca mudou"),
      gone ? t("A biblioteca mudou: {name} não existe mais.", { name })
        : t("A biblioteca mudou: {name} tem uma versão salva mais nova.", { name }),
      [
        { id: "library", label: gone ? t("Descartar rascunho") : t("Usar a versão nova"), tone: "primary" },
        { id: "keep", label: t("Manter rascunho") },
      ],
    );
    if (state.collections[kind].draft !== draft) return;
    if (choice === "keep") {
      // Gone: the draft becomes a new item and Salvar creates it again.
      if (gone) Object.assign(draft, { original: null, revision: null, savedName: "", savedText: "", savedSpans: "[]" });
      else draft.revision = check.revision;
    } else {
      state.collections[kind].draft = gone ? null : draftFrom(await sources[kind].get(name), draft.type);
    }
    if (state.page === kind) { renderList(); renderDetail(); }
  } finally {
    reconciling = false;
  }
}

/** Settle an unsaved draft before it would be dropped. True when it is safe to continue. */
async function resolveDraft(kind: Kind): Promise<boolean> {
  if (!isDirty(kind)) return true;
  const draft = state.collections[kind].draft!;
  const name = draft.name.trim() || (kind === "textos" ? t("novo snippet") : t("novo item"));
  const choice = await ask(
    t("Alterações não salvas"),
    t("{name} tem alterações que ainda não foram salvas.", { name }),
    [
      { id: "save", label: t("Salvar"), tone: "primary" },
      { id: "discard", label: t("Descartar") },
      { id: "cancel", label: t("Cancelar") },
    ],
  );
  if (choice === "save") return save(kind);
  if (choice !== "discard") return false;
  // Descartar drops the edits now, so a caller that keeps the editor (Duplicar, Renomear) shows the saved item.
  if (draft.original === null) state.collections[kind].draft = null;
  else Object.assign(draft, { name: draft.savedName, text: draft.savedText, spans: JSON.parse(draft.savedSpans) });
  if (state.page === kind) renderDetail();
  return true;
}

async function openItem(kind: Kind, name: string): Promise<void> {
  const collection = state.collections[kind];
  const type = kind === "mapeamentos" ? state.type : null;
  if (collection.draft?.original === name && collection.draft.type === type) return;
  if (!(await resolveDraft(kind))) return;
  let entry: Entry;
  try {
    entry = await sources[kind].get(name);
  } catch (error) {
    await alertError(kind === "textos" ? t("Não foi possível abrir o snippet") : t("Não foi possível abrir o item"),
      error);
    await refreshList(kind);
    return;
  }
  collection.draft = draftFrom(entry, type);
  renderList();
  renderDetail();
}

async function newItem(kind: Kind): Promise<void> {
  if (!(await resolveDraft(kind))) return;
  const collection = state.collections[kind];
  const prefill = collection.query.trim();
  collection.draft = newDraft(kind === "mapeamentos" ? state.type : null, prefill);
  renderList();
  renderDetail();
  document.getElementById(prefill ? "text" : "name")?.focus();
}

const saving = new Set<Kind>();

/** Salvar and Ctrl+S. True when nothing is left unsaved. */
async function save(kind: Kind): Promise<boolean> {
  // A second Salvar while one is in flight would carry the same base and read as someone else's change.
  if (saving.has(kind)) return false;
  saving.add(kind);
  try {
    return await saveDraft(kind);
  } finally {
    saving.delete(kind);
  }
}

async function saveDraft(kind: Kind, confirmed: SaveCheck[] = []): Promise<boolean> {
  const draft = state.collections[kind].draft;
  if (!draft || !isDirty(kind)) return true;
  let answer: Saved | Confirmation;
  try {
    answer = await sources[kind].save(draft, confirmed);
  } catch (error) {
    await alertError(error instanceof BridgeError && error.code === "invalid"
      ? (kind === "textos" ? t("Salvar snippet") : t("Salvar item")) : t("Erro ao salvar"), error);
    return false;
  }
  if (answer.status === "confirm") {
    const choice = await ask(answer.title, answer.message, [
      { id: "ok", label: answer.action, tone: answer.check === "replace" || answer.check === "stale" ? "danger" : "primary" },
      { id: "cancel", label: t("Cancelar") },
    ]);
    return choice === "ok" ? saveDraft(kind, [...confirmed, answer.check]) : false;
  }
  Object.assign(draft, {
    original: answer.name, name: answer.name, savedName: answer.name, savedText: draft.text,
    savedSpans: JSON.stringify(draft.spans), formFrom: null, revision: answer.revision,
  });
  const shown = kind === "textos" ? answer.name : t("{name} em {type}", { name: answer.name, type: typeLabel(draft.type) });
  showReceipt(kind, { text: t("Salvo às {time} · {name}", { time: clock(), name: shown }) });
  // Saving under another name makes it another item, with that item's metadata.
  await reloadEntry(kind);
  await refreshList(kind);
  if (state.page === kind) renderDetail();
  return true;
}

async function deleteCurrent(kind: Kind): Promise<void> {
  const collection = state.collections[kind];
  const draft = collection.draft;
  if (!draft?.original) return;
  const name = draft.original;
  const type = draft.type;
  let token: string;
  try {
    token = await sources[kind].remove(draft);
  } catch (error) {
    await alertError(kind === "textos" ? t("Excluir snippet") : t("Excluir item"), error);
    return;
  }
  // Deleting asks nothing: Desfazer brings it back, metadata included.
  collection.draft = null;
  showReceipt(kind, {
    text: t("Excluído às {time} · {name}", { time: clock(), name }),
    undo: async () => {
      try {
        await sources[kind].undo(token);
      } catch (error) {
        await alertError(t("Desfazer exclusão"), error);
        return;
      }
      if (type !== null && type !== state.type) {
        if (!(await resolveDraft(kind))) return;
        state.type = type;
      }
      await refreshList(kind);
      await openItem(kind, name);
      showReceipt(kind, { text: t("Restaurado às {time} · {name}", { time: clock(), name }) });
    },
  });
  await refreshList(kind);
  renderDetail();
}

// Favorito and Grupo apply at once, like the classic manager; the draft stays as typed.
async function setFavorite(kind: Kind, favorite: boolean): Promise<void> {
  const draft = state.collections[kind].draft;
  if (!draft?.original) return;
  try {
    await sources[kind].setFavorite(draft, favorite);
    draft.favorite = favorite;
  } catch (error) {
    await alertError(t("Favorito"), error);
  }
  await refreshList(kind);
}

async function setGroup(group: string): Promise<void> {
  const draft = state.collections.textos.draft;
  if (!draft?.original) return;
  try {
    await request("snippet.setGroup", { trigger: draft.original, group });
  } catch (error) {
    await alertError(t("Grupo"), error);
  }
  // A group prefix changes what the person types.
  await reloadEntry("textos");
  await refreshList("textos");
}

/** Duplicar and Ctrl+D: a copy of the saved item, which opens in the editor. */
async function duplicateCurrent(kind: Kind): Promise<void> {
  if (!state.collections[kind].draft?.original || !(await resolveDraft(kind))) return;
  const collection = state.collections[kind];
  const source = collection.draft;
  if (!source?.original) return;
  if (kind === "mapeamentos") {
    // A mapping copy is a new draft of the same type, saved under the identifier given to it, form included.
    collection.draft = { ...newDraft(source.type, "", source.savedText, JSON.parse(source.savedSpans)),
      formFrom: source.original };
    renderList();
    renderDetail();
    document.getElementById("name")?.focus();
    return;
  }
  let copy: string | null = null;
  await formDialog({
    title: t("Duplicar snippet"),
    fields: [{ id: "trigger", label: t("Trigger da cópia de {trigger}", { trigger: source.original }), mono: true }],
    action: t("Duplicar"),
    submit: async (values) => {
      let answer: CopyAnswer;
      try {
        answer = await request<CopyAnswer>("snippet.duplicate", {
          trigger: source.original, destination: String(values.trigger),
        });
      } catch (error) {
        return { field: "trigger", message: errorText(error) };
      }
      if (answer.status === "invalid") return { field: "trigger", message: answer.message };
      copy = answer.trigger;
      return null;
    },
  });
  if (copy === null) return;
  await refreshList("textos");
  await openItem("textos", copy);
  showReceipt("textos", { text: t("Duplicado às {time} · {name}", { time: clock(), name: copy }) });
}

/** Renomear and F2: a new trigger for the saved snippet, metadata included. */
async function renameCurrent(): Promise<void> {
  const collection = state.collections.textos;
  if (!collection.draft?.original || !(await resolveDraft("textos"))) return;
  const source = collection.draft;
  if (!source?.original) return;
  let renamed: string | null = null;
  await formDialog({
    title: t("Renomear snippet"),
    fields: [{ id: "trigger", label: t("Novo trigger de {trigger}", { trigger: source.original }), mono: true,
      value: source.original }],
    action: t("Renomear"),
    submit: async (values) => {
      const confirmed: SaveCheck[] = [];
      for (;;) {
        let answer: RenameAnswer;
        try {
          answer = await request<RenameAnswer>("snippet.rename", {
            trigger: source.original, destination: String(values.trigger), confirmed,
          });
        } catch (error) {
          return { field: "trigger", message: errorText(error) };
        }
        if (answer.status === "invalid") return { field: "trigger", message: answer.message };
        if (answer.status === "renamed") {
          renamed = answer.trigger;
          return null;
        }
        const choice = await ask(answer.title, answer.message, [
          { id: "ok", label: answer.action, tone: "primary" }, { id: "cancel", label: t("Cancelar") },
        ]);
        // Declining keeps the dialog open on the trigger, to pick another one.
        if (choice !== "ok") return { field: "trigger", message: "" };
        confirmed.push(answer.check);
      }
    },
  });
  if (renamed === null || renamed === source.original) return;
  Object.assign(source, { original: renamed, name: renamed, savedName: renamed });
  await reloadEntry("textos");
  await refreshList("textos");
  renderDetail();
  showReceipt("textos", { text: t("Renomeado às {time} · {name}", { time: clock(), name: renamed }) });
}

async function setView(change: Partial<typeof state.view>): Promise<void> {
  Object.assign(state.view, change);
  await refreshList("textos");
}

/** Novo grupo (no id) and Editar grupo. */
async function groupDialog(id: string | null): Promise<void> {
  let form: GroupForm;
  try {
    form = await request<GroupForm>("group.form", id ? { id } : {});
  } catch (error) {
    await alertError(id ? t("Editar grupo") : t("Novo grupo"), error);
    return;
  }
  const values = form.values;
  let saved: { id: string; label: string } | null = null;
  await formDialog({
    title: id ? t("Editar grupo") : t("Novo grupo"),
    fields: [
      { id: "label", label: t("Nome do grupo"), value: values.label },
      { id: "prefix", label: t("Prefixo do trigger"), value: values.prefix, mono: true,
        hint: t("Vem antes do trigger de cada snippet do grupo. Ex.: prefixo 'w' + trigger 'oi' -> woi") },
      { id: "enabled", label: t("Grupo ativo"), kind: "switch", value: values.enabled },
      { id: "terminator", label: t("Terminador"), kind: "select", value: values.terminator, options: form.terminators },
      { id: "application_mode", label: t("Modo de aplicativo"), kind: "select", value: values.application_mode,
        options: form.applicationModes, hint: form.windowsNote },
      { id: "executables", label: t("Executáveis (um por linha)"), kind: "textarea", mono: true,
        value: values.executables, shownWhen: (current) => current.application_mode !== "all" },
      { id: "notes", label: t("Notas"), kind: "textarea", value: values.notes },
    ],
    action: t("Salvar"),
    submit: async (current) => {
      let answer: GroupSaveAnswer;
      try {
        answer = await request<GroupSaveAnswer>("group.save", { id, values: current });
      } catch (error) {
        return { field: "label", message: errorText(error) };
      }
      if (answer.status === "invalid") return { field: answer.field, message: answer.message };
      saved = answer;
      return null;
    },
  });
  if (saved === null) return;
  const { label } = saved as { id: string; label: string };
  await reloadEntry("textos");
  await refreshList("textos");
  showReceipt("textos", {
    text: id ? t("Grupo atualizado às {time} · {name}", { time: clock(), name: label })
      : t("Grupo criado às {time} · {name}", { time: clock(), name: label }),
  });
}

/** Excluir grupo asks nothing: its snippets stay, in no group, and Desfazer brings both back. */
async function deleteGroup(id: string): Promise<void> {
  let answer: { undoToken: string; label: string };
  try {
    answer = await request("group.delete", { id });
  } catch (error) {
    await alertError(t("Excluir grupo"), error);
    return;
  }
  if (state.view.group === id) state.view.group = "";
  await reloadEntry("textos");
  await refreshList("textos");
  showReceipt("textos", {
    text: t("Excluído às {time} · {name}", { time: clock(), name: answer.label }),
    undo: async () => {
      try {
        await request("group.undoDelete", { token: answer.undoToken });
      } catch (error) {
        await alertError(t("Desfazer exclusão"), error);
        return;
      }
      await reloadEntry("textos");
      await refreshList("textos");
      showReceipt("textos", { text: t("Restaurado às {time} · {name}", { time: clock(), name: answer.label }) });
    },
  });
}

async function switchType(key: string): Promise<void> {
  if (key === state.type) return;
  // A type change empties the editor, so a draft is settled first.
  if (!(await resolveDraft("mapeamentos"))) {
    renderTypeBar();
    return;
  }
  const collection = state.collections.mapeamentos;
  state.type = key;
  collection.draft = null;
  collection.query = "";
  if (refs.search) refs.search.value = "";
  await refreshList("mapeamentos");
  renderDetail();
}

async function createType(): Promise<void> {
  let created: string | null = null;
  await formDialog({
    title: t("Novo tipo de mapeamento"),
    fields: [
      { id: "name", label: t("Nome do tipo") },
      { id: "prefix", label: t("Prefixo usado no trigger"), hint: t("Ex.: tipo 'email' + prefixo 'mail' -> mailtrabalho"),
        mono: true },
    ],
    action: t("Criar tipo"),
    submit: async (values) => {
      let answer: CreateTypeAnswer;
      try {
        answer = await request<CreateTypeAnswer>("mapping.createType", {
          name: String(values.name), prefix: String(values.prefix),
        });
      } catch (error) {
        return { field: "name", message: errorText(error) };
      }
      if (answer.status === "invalid") return { field: answer.field, message: answer.message };
      created = answer.key;
      return null;
    },
  });
  if (created === null) return;
  await refreshTypes();
  showReceipt("mapeamentos", { text: t("Tipo criado às {time} · {name}", { time: clock(), name: typeLabel(created) }) });
  await switchType(created);
  renderTypeBar();
}

async function deleteType(): Promise<void> {
  const type = currentType();
  if (!type || type.builtin) return;
  // Every item of the type goes with it, so the name has to be typed.
  const deleted = await formDialog({
    title: t("Excluir tipo"),
    message: t(
      "O tipo {type} será excluído com todos os itens ({count}).\n\nA exclusão não pode ser desfeita aqui; a biblioteca anterior continua em Cópias de segurança.",
      { type: type.label, count: type.count }),
    fields: [{ id: "word", label: t("Para confirmar, digite {word}", { word: type.label }), mono: true }],
    action: t("Excluir tipo"),
    danger: true,
    confirmWord: type.label,
    submit: async () => {
      try {
        await request("mapping.deleteType", { type: type.key });
      } catch (error) {
        return { field: "word", message: errorText(error) };
      }
      return null;
    },
  });
  if (!deleted) return;
  // The typed confirmation covered the type's items, open draft included.
  const collection = state.collections.mapeamentos;
  if (collection.draft?.type === type.key) collection.draft = null;
  await refreshList("mapeamentos");
  renderDetail();
  showReceipt("mapeamentos", { text: t("Tipo excluído às {time} · {name}", { time: clock(), name: type.label }) });
}

async function setSetting(card: string, key: string, value: unknown): Promise<void> {
  try {
    state.info = await request<AppInfo>("settings.set", { key, value });
    state.cardStatus[card] = { text: t("Salvo."), error: false };
  } catch (error) {
    state.cardStatus[card] = { text: errorText(error), error: true };
  }
  setLanguage(state.info!.language);
  applyAppearance();
  renderAll();
}

// ---------------------------------------------------------------------------
// Receipts: the status line under each list, with Desfazer when it applies.

const receiptTimers: Record<Kind, number> = { textos: 0, mapeamentos: 0 };

function showReceipt(kind: Kind, receipt: Receipt): void {
  state.collections[kind].receipt = receipt;
  window.clearTimeout(receiptTimers[kind]);
  // An undo stays offered for a while; afterwards the line keeps only the fact.
  if (receipt.undo) receiptTimers[kind] = window.setTimeout(() => showReceipt(kind, { text: receipt.text }), 15_000);
  if (state.page === kind) renderReceipt();
}

function renderReceipt(): void {
  const host = refs.receipt;
  const kind = activeKind();
  if (!host || !kind) return;
  const receipt = state.collections[kind].receipt;
  host.replaceChildren(
    ...(receipt ? [h("span", {}, receipt.text)] : []),
    ...(receipt?.undo ? [h("button", {
      type: "button",
      onclick: () => {
        const undo = receipt.undo!;
        showReceipt(kind, { text: receipt.text });
        void undo();
      },
    }, t("Desfazer"))] : []),
  );
}

// ---------------------------------------------------------------------------
// Rendering

function renderAll(): void {
  document.documentElement.lang = state.info?.language ?? "pt-BR";
  const navButton = (page: Page, iconId: string, label: string) => h("button", {
    type: "button",
    "aria-current": state.page === page ? "page" : "false",
    title: label,
    onclick: () => showPage(page),
  }, icon(iconId), h("span", { class: "label" }, label));

  refs.infobar = h("div", { class: "infobar", role: "region", "aria-label": t("Avisos") });
  const kind = activeKind();
  const page = h("main", { class: "page" }, refs.infobar,
    kind ? collectionPage(kind) : state.page === "dinamicos" ? dynamicsPage()
      : state.page === "backups" ? backupsPage() : settingsPage());

  root.replaceChildren(h("div", { class: "app" },
    h("nav", { class: "navigation", "aria-label": t("Seções") },
      h("div", { class: "brand" }, icon("document"), h("span", {}, "SnipType")),
      navButton("textos", "library", t("Textos")),
      navButton("mapeamentos", "mapping", t("Mapeamentos")),
      navButton("dinamicos", "dynamic", t("Dinâmicos")),
      navButton("backups", "backup", t("Backups")),
      refs.status = h("div", { class: "expansion", role: "group", "aria-label": t("Expansão") }),
      navButton("settings", "settings", t("Configurações")),
      h("p", { class: "version" }, state.info ? `${state.info.version} · ${state.info.channel}` : ""),
    ),
    page,
  ));
  renderInfobar();
  renderStatus();
  if (kind) {
    renderTypeBar();
    renderViewBar();
    renderList();
    renderDetail();
    renderReceipt();
  } else if (state.page === "dinamicos") {
    renderDynamics();
  } else if (state.page === "backups") {
    renderBackups();
  }
}

async function showPage(page: Page): Promise<void> {
  if (page === state.page) return;
  // Each editor keeps its draft while another page shows.
  state.page = page;
  scheduleWindowSave();
  renderAll();
  if (isKind(page)) {
    refs.search?.focus();
    await refreshList(page).catch((error) => console.error("refresh failed", error));
    await reconcileDraft(page).catch((error) => console.error("reconcile failed", error));
  } else if (page === "dinamicos") {
    refs.search?.focus();
    await refreshDynamics().catch((error) => console.error("refresh failed", error));
  } else if (page === "backups") {
    await refreshBackups().catch((error) => console.error("refresh failed", error));
  }
}

function renderInfobar(): void {
  const host = refs.infobar;
  if (!host) return;
  const issues = state.info?.issues ?? [];
  host.replaceChildren(...issues.map((issue) => {
    const actions = [
      ...(issue.action ? [h("button", { type: "button", class: "el-button", onclick: () => void runHealth(issue.action!) },
        issue.actionLabel ?? "")] : []),
      ...(issue.dismissible ? [h("button", { type: "button", class: "el-button",
        onclick: () => void dismissIssue(issue.id) }, t("Dispensar"))] : []),
    ];
    return h("div", {
      class: `el-message ${issue.severity === "error" ? "error" : issue.severity === "warning" ? "warning" : "info"}`,
      role: issue.severity === "error" ? "alert" : "status",
    }, h("strong", {}, issue.title), h("span", {}, issue.body),
    ...(actions.length ? [h("span", { class: "actions" }, ...actions)] : []));
  }));
}

/** The sidebar's expansion block: the state in words, Pausar/Retomar, and the last expansion. */
function renderStatus(): void {
  const host = refs.status;
  const info = state.info;
  if (!host || !info) return;
  const { state: expansion, label } = info.expansion;
  const toggleLabel = expansion === "paused" ? t("Retomar expansão") : t("Pausar expansão");
  // The narrow rail hides every .label: the buttons keep their names in title and aria-label.
  const toggle = expansion === "down"
    ? h("button", { type: "button", class: "el-button", disabled: true, title: t("Reinicie o SnipType"),
      "aria-label": t("Reinicie o SnipType") }, icon("pause"), h("span", { class: "label" }, t("Reinicie o SnipType")))
    : h("button", { type: "button", class: "el-button", title: toggleLabel, "aria-label": toggleLabel,
      onclick: () => void toggleExpansion() },
      icon(expansion === "paused" ? "play" : "pause"), h("span", { class: "label" }, toggleLabel));
  host.replaceChildren(
    h("p", { class: `state ${expansion}`, role: "status" }, h("span", { class: "dot", "aria-hidden": "true" }),
      h("span", { class: "label" }, label)),
    toggle,
    h("p", { class: "last label" }, info.lastExpansion),
    h("button", {
      type: "button", class: "el-button", disabled: !info.canEditLast,
      title: t("Editar último"), "aria-label": t("Editar último"),
      onclick: () => void request("app.editLast").catch((error) => alertError(t("Editar último"), error)),
    }, icon("document"), h("span", { class: "label" }, t("Editar último"))),
    h("button", {
      type: "button", class: "el-button", title: t("Notificações"), "aria-label": t("Notificações"),
      onclick: () => void showNotifications(),
    }, icon("bell"), h("span", { class: "label" }, t("Notificações"))),
  );
}

/** Notificações: what the app has said, newest first; errors are marked by word as well as color. */
async function showNotifications(): Promise<void> {
  const body = h("div", { class: "notices", role: "region", "aria-label": t("Últimas notificações"), tabindex: 0 });
  const errorsOnly = h("input", { type: "checkbox", role: "switch", class: "el-switch", id: "notices-errors" });
  const fill = async () => {
    let rows: Notice[];
    try {
      rows = await request<Notice[]>("notifications.list", { errorsOnly: errorsOnly.checked });
    } catch (error) {
      body.replaceChildren(h("p", { class: "error" }, errorText(error)));
      return;
    }
    if (!rows.length) {
      body.replaceChildren(h("p", { class: "muted" },
        errorsOnly.checked ? t("Nenhum erro registrado.") : t("Nenhuma notificação registrada ainda.")));
      return;
    }
    body.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, t("Quando")), h("th", {}, t("Tipo")), h("th", {}, t("Mensagem")))),
      h("tbody", {}, ...rows.map((row) => h("tr", { class: row.kind === "error" ? "error" : undefined },
        h("td", {}, row.when), h("td", {}, row.kindLabel), h("td", {}, row.message))))));
  };
  errorsOnly.addEventListener("change", () => void fill());
  const dialog = h("dialog", { class: "notices-dialog", "aria-labelledby": "dialog-title" },
    h("h2", { id: "dialog-title" }, t("Histórico de notificações")),
    h("label", { class: "el-choice", for: "notices-errors" }, errorsOnly, t("Somente erros")),
    body,
    h("menu", {}, h("button", { type: "button", class: "primary", onclick: () => dialog.close() }, t("Fechar"))),
  );
  await fill();
  openDialog(dialog, dialog.querySelector("menu button"));
}

async function copyText(text: string, card: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    state.cardStatus[card] = { text: t("Copiado."), error: false };
  } catch (error) {
    state.cardStatus[card] = { text: errorText(error), error: true };
  }
  renderAll();
}

/** One destination of the Dados card: the folder with Copiar, and the last run under it. */
function transferRow(transfer: Transfer): HTMLElement {
  const label = transfer.kind === "copy" ? t("Cópia espelho") : t("Pacote de sincronização");
  const off = transfer.kind === "copy" ? t("Desativada") : t("Desativado");
  return h("div", { class: "data-row" },
    h("span", {}, label),
    transfer.dir ? h("code", {}, transfer.dir) : h("span", { class: "muted" }, off),
    transfer.dir ? h("button", { type: "button", class: "el-button", onclick: () => void copyText(transfer.dir!, "data") },
      t("Copiar")) : h("span", {}),
    transfer.status ? h("div", { class: `transfer${transfer.failed ? " failed" : ""}`, role: transfer.failed ? "alert" : undefined },
      h("span", {}, transfer.status),
      ...(transfer.failed ? [
        h("button", { type: "button", class: "el-button",
          onclick: () => void request("data.openTransfer", { kind: transfer.kind })
            .catch((error) => alertError(t("Abrir pasta"), error)) }, t("Abrir pasta")),
        h("button", { type: "button", class: "el-button",
          onclick: () => void runHealth("retry_sync") }, t("Tentar agora")),
      ] : [])) : null,
  );
}

async function toggleExpansion(): Promise<void> {
  try {
    const answer = await request<{ receipt: string | null }>("app.toggleEnabled");
    if (answer.receipt) pageReceipt(answer.receipt);
  } catch (error) {
    await alertError(t("Expansão"), error);
  }
  await refreshInfo().catch((error) => console.error("refresh failed", error));
}

/** An issue's one recovery action: some open a page here, the others run in the app. */
async function runHealth(action: string): Promise<void> {
  try {
    const answer = await request<HealthAnswer>("health.run", { action });
    if (answer.page) await showPage(answer.page as Page);
    if (answer.receipt) pageReceipt(answer.receipt);
  } catch (error) {
    await alertError(t("Avisos"), error);
  }
  await refreshInfo().catch((error) => console.error("refresh failed", error));
  // Tentar agora on the Dados card: its transfer lines come from app.info, not from the bar.
  if (state.page === "settings") renderAll();
}

async function dismissIssue(id: string): Promise<void> {
  await request("health.dismiss", { id }).catch((error) => console.error("dismiss failed", error));
  await refreshInfo().catch((error) => console.error("refresh failed", error));
}

const typeBar = { host: null as HTMLElement | null };

function collectionPage(kind: Kind): HTMLElement {
  const collection = state.collections[kind];
  const textos = kind === "textos";
  refs.search = h("input", {
    id: "search-field", type: "search", class: "field", value: collection.query, autocomplete: "off", spellcheck: "false",
    placeholder: textos ? t("Buscar por trigger ou texto") : t("Buscar por identificador ou valor"),
    "aria-label": textos ? t("Buscar textos") : t("Buscar itens"),
    oninput: (event: Event) => {
      collection.query = (event.target as HTMLInputElement).value;
      renderList();
    },
    onkeydown: (event: KeyboardEvent) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        (refs.items?.querySelector(".item") as HTMLElement | null)?.focus();
      } else if (event.key === "Enter") {
        const first = visibleItems(kind)[0];
        if (first) void openItem(kind, first.name);
      }
    },
  });
  const title = textos ? t("Textos") : t("Mapeamentos");
  refs.items = h("div", { class: "items", role: "listbox", "aria-label": title, onkeydown: onListKey });
  refs.count = h("span");
  refs.receipt = h("div", { class: "receipt", role: "status", "aria-live": "polite" });
  refs.detail = h("section", { class: "detail", "aria-label": t("Editor") });
  typeBar.host = textos ? null : h("div", { class: "type-bar" });
  refs.viewBar = textos ? h("div", { class: "type-bar" }) : null;

  return h("div", { class: "textos" },
    h("section", { class: "collection", "aria-labelledby": "collection-title" },
      h("div", { class: "heading" },
        h("h1", { id: "collection-title" }, title),
        h("button", { type: "button", class: "primary", title: "Ctrl+N", onclick: () => void newItem(kind) },
          icon("plus"), textos ? t("Novo") : t("Novo item")),
      ),
      typeBar.host,
      refs.viewBar,
      h("div", { class: "search" }, icon("search"), refs.search),
      h("p", { class: "list-caption" }, h("span", {}, textos ? t("Trigger") : t("Identificador")), refs.count),
      refs.items,
      refs.receipt,
    ),
    refs.detail,
  );
}

function renderTypeBar(): void {
  const host = typeBar.host;
  if (!host) return;
  const type = currentType();
  host.replaceChildren(
    h("select", {
      class: "field", "aria-label": t("Tipo de mapeamento"),
      onchange: (event: Event) => void switchType((event.target as HTMLSelectElement).value),
    }, ...state.types.map((option) => h("option", { value: option.key, selected: option.key === state.type },
      `${option.label} · ${option.count}`))),
    h("button", { type: "button", class: "el-button", title: t("Novo tipo"), onclick: () => void createType() },
      icon("plus"), h("span", { class: "sr-only" }, t("Novo tipo"))),
    h("button", {
      type: "button", class: "el-button danger", disabled: !type || type.builtin,
      title: type?.builtin ? t("Não é possível excluir tipos padrão (CPF, CNPJ).") : t("Excluir tipo"),
      onclick: () => void deleteType(),
    }, t("Excluir tipo")),
  );
}

/** Textos' Exibir and Grupo filters, and the Grupos menu beside them. */
function renderViewBar(): void {
  const host = refs.viewBar;
  if (!host) return;
  const selected = state.groups.find((group) => group.id === state.view.group);
  host.replaceChildren(
    h("select", {
      class: "field", "aria-label": t("Exibir"),
      onchange: (event: Event) => void setView({ filter: (event.target as HTMLSelectElement).value as ListFilter }),
    }, ...listFilters().map(([value, label]) => h("option", { value, selected: value === state.view.filter }, label))),
    h("select", {
      class: "field", "aria-label": t("Filtrar por grupo"),
      onchange: (event: Event) => void setView({ group: (event.target as HTMLSelectElement).value }),
    },
    h("option", { value: "", selected: state.view.group === "" }, t("Todos os grupos")),
    h("option", { value: UNGROUPED, selected: state.view.group === UNGROUPED }, t("Sem grupo")),
    ...state.groups.map((group) => h("option", { value: group.id, selected: group.id === state.view.group },
      group.enabled ? group.label : t("{name} (desativado)", { name: group.label })))),
    menuButton(t("Grupos"), () => [
      { label: t("Novo grupo…"), run: () => void groupDialog(null) },
      { label: t("Editar grupo…"), disabled: !selected, run: () => void groupDialog(selected!.id) },
      { label: t("Excluir grupo"), disabled: !selected, run: () => void deleteGroup(selected!.id) },
    ], {
      disabled: state.groupsReadOnly,
      title: state.groupsReadOnly ? readOnlyMessage()
        : selected ? undefined : t("Escolha um grupo no filtro para editar ou excluir."),
    }),
  );
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Name prefix first, then name substring, then text matches. */
function visibleItems(kind: Kind): Item[] {
  const { items, query } = state.collections[kind];
  const needle = fold(query.trim());
  if (!needle) return items;
  const ranked: [number, Item][] = [];
  for (const item of items) {
    const name = fold(item.name);
    const rank = name.startsWith(needle) ? 0 : name.includes(needle) ? 1
      : fold(item.preview).includes(needle) ? 2 : -1;
    if (rank >= 0) ranked.push([rank, item]);
  }
  return ranked.sort((a, b) => a[0] - b[0]).map(([, item]) => item);
}

/** Oculto pelo filtro atual: the open item is saved but the list's search or view hides it. */
function renderHiddenNote(): void {
  const host = refs.hiddenNote;
  const kind = activeKind();
  if (!host || !kind) return;
  const draft = state.collections[kind].draft;
  const shown = !!draft?.original && (kind === "textos" || draft.type === state.type)
    && !visibleItems(kind).some((item) => item.name === draft.original);
  host.hidden = !shown;
  host.replaceChildren(...(shown ? [
    h("span", {}, t("Oculto pelo filtro atual.")),
    h("button", { type: "button", class: "el-button", onclick: () => void revealCurrent(kind) }, t("Mostrar na lista")),
  ] : []));
}

/** Mostrar na lista: clear what hides the open item, then select it in the list. */
async function revealCurrent(kind: Kind): Promise<void> {
  const collection = state.collections[kind];
  const name = collection.draft?.original;
  if (!name) return;
  collection.query = "";
  if (refs.search) refs.search.value = "";
  if (kind === "textos" && viewActive()) await setView({ filter: "all", group: "" });
  else renderList();
  const item = [...(refs.items?.querySelectorAll<HTMLElement>(".item") ?? [])].find((element) => element.dataset.name === name);
  item?.scrollIntoView({ block: "nearest" });
  item?.focus();
}

function renderList(): void {
  const host = refs.items;
  const kind = activeKind();
  if (!host || !kind) return;
  renderHiddenNote();
  const collection = state.collections[kind];
  const textos = kind === "textos";
  const items = visibleItems(kind);
  const draft = collection.draft;
  const current = draft && (textos || draft.type === state.type) ? draft.original : null;
  const narrowed = textos && viewActive();
  refs.count!.textContent = collection.query.trim() || narrowed
    ? t("{shown} de {total}", { shown: items.length, total: collection.total })
    : textos ? t("{total} textos", { total: collection.total })
    : t("{total} itens", { total: collection.total });
  if (!items.length) {
    if (narrowed && !collection.query.trim()) {
      host.replaceChildren(h("div", { class: "empty-list" },
        h("p", {}, t("Nenhum texto nesta visualização.")),
        h("button", { type: "button", class: "el-button", onclick: () => void setView({ filter: "all", group: "" }) },
          t("Mostrar todos"))));
      return;
    }
    const empty = textos
      ? collection.items.length || narrowed ? t("Nenhum texto encontrado. Ctrl+N cria um com este trigger.")
        : t("Nenhum texto ainda. Use Novo para criar o primeiro, ou importe uma biblioteca.")
      : collection.items.length ? t("Nenhum item corresponde à busca.") : t("Este tipo ainda não tem itens.");
    // An empty library offers Importar beside Novo (DESIGN.md).
    const offerImport = textos && !collection.total;
    host.replaceChildren(h("div", { class: "empty-list" }, h("p", {}, empty),
      offerImport ? h("button", { type: "button", class: "el-button", onclick: () => importLibrary() }, t("Importar…")) : null));
    return;
  }
  // One Tab stop for the whole list: the open item, else the first one.
  const tabStop = items.some((item) => item.name === current) ? current : items[0].name;
  // ceiling: renders every row; virtualize if libraries beyond ~5k snippets feel slow.
  host.replaceChildren(...items.map((item) => h("button", {
    type: "button", class: "item", role: "option", "data-name": item.name,
    "aria-selected": item.name === current ? "true" : "false", tabindex: item.name === tabStop ? "0" : "-1",
    "aria-label": itemLabel(item),
    onclick: () => void openItem(kind, item.name),
  },
  h("span", { class: "trigger" }, item.effectiveTrigger === item.name
    ? item.name : `${item.name} → ${item.effectiveTrigger}`),
  h("span", { class: "badges" },
    item.favorite ? icon("favorite") : null,
    item.rich ? h("span", { class: "el-badge" }, t("formatado")) : null,
    item.keys ? h("span", { class: "el-badge", title: t("Pressiona Enter ou Tab ao expandir.") },
      icon("bi-keyboard"), t("teclas")) : null,
    item.shadowed ? h("span", { class: "el-badge", title: t("Um snippet dinâmico usa este trigger e tem prioridade.") },
      t("sombreado")) : null,
    item.group ? h("span", { class: "el-badge" }, item.group) : null,
    item.enabled === false ? h("span", { class: "el-badge" }, t("desativado")) : null,
  ),
  h("span", { class: "preview" }, item.preview || "—"))));
  host.querySelector<HTMLElement>(".item[aria-selected=true]")?.scrollIntoView({ block: "nearest" });
}

/** What a screen reader says for a row: its trigger, its badges in words, then its text. */
function itemLabel(item: Item): string {
  const trigger = item.effectiveTrigger === item.name ? item.name : `${item.name} → ${item.effectiveTrigger}`;
  return [
    trigger,
    item.favorite ? t("favorito") : "",
    item.rich ? t("formatado") : "",
    item.keys ? t("teclas") : "",
    item.shadowed ? t("sombreado") : "",
    item.group ?? "",
    item.enabled === false ? t("desativado") : "",
    item.preview,
  ].filter(Boolean).join(", ");
}

function onListKey(event: KeyboardEvent): void {
  const target = event.target as HTMLElement;
  const kind = activeKind();
  if (!kind || !target.classList.contains("item")) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const sibling = event.key === "ArrowDown" ? target.nextElementSibling : target.previousElementSibling;
    if (sibling instanceof HTMLElement) sibling.focus();
    else if (event.key === "ArrowUp") refs.search?.focus();
  } else if (event.key === "Delete" && target.getAttribute("aria-selected") === "true") {
    event.preventDefault();
    void deleteCurrent(kind);
  }
}

function updateSaveState(): void {
  const kind = activeKind();
  if (!kind) return;
  const dirty = isDirty(kind);
  const draft = state.collections[kind].draft;
  if (refs.saveButton) refs.saveButton.disabled = !dirty;
  if (refs.saveState) {
    refs.saveState.textContent = dirty ? t("Alterações não salvas") : draft?.original ? t("Salvo") : "";
    refs.saveState.classList.toggle("dirty", dirty);
  }
  if (refs.effective && draft && kind === "textos") {
    refs.effective.textContent = draft.original && draft.effectiveTrigger !== draft.original
      ? t("Com o prefixo do grupo, digite {trigger} para expandir.", { trigger: draft.effectiveTrigger })
      : t("O que você digita para expandir. Triggers com '_' são reservados.");
  } else if (refs.effective && draft) {
    const prefix = state.types.find((type) => type.key === draft.type)?.prefix ?? "";
    const name = draft.name.trim();
    refs.effective.textContent = name
      ? t("Digite {trigger} para expandir.", { trigger: prefix + name })
      : t("Digite o prefixo {prefix} e o identificador para expandir.", { prefix });
  }
  document.title = isDirty("textos") || isDirty("mapeamentos") ? "• SnipType" : "SnipType";
}

/** Negrito, Itálico, Sublinhado, Código, Tachado and Limpar formatação, over the editor's selection. */
function formatBar(editor: RichEditor, hint: HTMLElement): HTMLElement {
  const styles: [Style, string, string, string][] = [
    ["bold", "bi-type-bold", t("Negrito"), "Ctrl+B"], ["italic", "bi-type-italic", t("Itálico"), "Ctrl+I"],
    ["underline", "bi-type-underline", t("Sublinhado"), "Ctrl+U"], ["code", "bi-code-slash", t("Código"), ""],
    ["strike", "bi-type-strikethrough", t("Tachado"), ""],
  ];
  // The buttons never take focus from a mouse click, so the selection they act on stays put.
  const keep = (event: Event) => event.preventDefault();
  return h("div", { class: "format-bar", role: "toolbar", "aria-label": t("Formatação"), "aria-controls": "text" },
    ...styles.map(([style, symbol, label, keys]) => h("button", {
      type: "button", class: "el-button", title: keys ? `${label} (${keys})` : label, "aria-label": label,
      onmousedown: keep,
      onclick: () => {
        if (!editor.toggle(style)) hint.textContent = t("Selecione o texto para formatar.");
        editor.focus();
      },
    }, icon(symbol))),
    h("button", {
      type: "button", class: "el-button", onmousedown: keep,
      onclick: () => {
        editor.clear();
        editor.focus();
      },
    }, icon("bi-eraser"), t("Limpar formatação")),
  );
}

// ---------------------------------------------------------------------------
// Inserir: the variables the app resolves, offered instead of left to be guessed.

// "{d}" becomes the date token with its offset. A date token cannot hold a
// space, so a written-out date is several tokens around plain text.
const DATE_PRESETS = [
  "%%{d}%%",
  "%%{d}:dd/MM/yy%%",
  "%%{d}:yyyy-MM-dd%%",
  "%%{d}:HH:mm%%",
  "%%{d}:dd/MM/yyyy%% %%{d}:HH:mm%%",
  "%%{d}:dd%% de %%{d}:MMMM%% de %%{d}:yyyy%%",
  "%%{d}:dddd%%, %%{d}:dd%% de %%{d}:MMMM%% de %%{d}:yyyy%%",
];
// Same grammar as source/builtin_tokens.py.
const DATE_OFFSET = /^[+-]\d{1,3}[dwmy]$/;

async function loadVariables(exclude: string | null): Promise<Variables> {
  const variables = await request<Variables>("variables.list");
  // A snippet that names itself is left as typed, so it is not offered to itself.
  variables.snippets = variables.snippets.filter((variable) => variable.name !== exclude);
  return variables;
}

async function completionCandidates(exclude: string | null): Promise<Candidate[]> {
  const variables = await loadVariables(exclude);
  return [
    { name: "clipboard-paste", detail: t("Texto da área de transferência") },
    { name: "_cursor", detail: t("Onde o cursor fica depois da expansão") },
    { name: "_date", detail: t("Data de hoje (dd/MM/yyyy)") },
    { name: "_date:HH:mm", detail: t("Hora atual (HH:mm)") },
    { name: "_date+1d", detail: t("Data de amanhã") },
    { name: "_enter", detail: t("Pressiona Enter (envia mensagens e formulários)") },
    { name: "_tab", detail: t("Pressiona Tab (vai para o próximo campo)") },
    ...variables.snippets, ...variables.dynamics, ...variables.mappings,
  ];
}

async function insertReference(editor: RichEditor, exclude: string | null): Promise<void> {
  let variables: Variables;
  try {
    variables = await loadVariables(exclude);
  } catch (error) {
    await alertError(t("Snippet existente"), error);
    return;
  }
  const sections: [string, Variable[]][] = [
    [t("Textos"), variables.snippets], [t("Dinâmicos"), variables.dynamics], [t("Mapeamentos"), variables.mappings],
  ];
  let chosen: string | null = null;
  const search = h("input", {
    class: "field", type: "search", autocomplete: "off", spellcheck: "false", "aria-label": t("Buscar"),
    placeholder: t("Buscar"),
  });
  const list = h("div", { class: "field-list reference-list" });
  const empty = h("p", { class: "muted", hidden: true }, t("Nada encontrado."));
  const dialog = h("dialog", { class: "wide", "aria-labelledby": "dialog-title" },
    h("h2", { id: "dialog-title" }, t("Inserir snippet existente")),
    h("p", {}, t("Ao expandir, o texto do snippet escolhido entra no lugar da variável.")),
    search, list, empty,
    h("menu", {}, h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar"))),
  );
  const draw = () => {
    const needle = fold(search.value.trim());
    const rows: HTMLElement[] = [];
    for (const [label, items] of sections) {
      const matches = items.filter((item) => fold(item.name).includes(needle) || fold(item.detail).includes(needle));
      if (!matches.length) continue;
      rows.push(h("span", { class: "list-caption" }, label));
      rows.push(...matches.map((item) => h("button", {
        type: "button",
        onclick: () => {
          chosen = item.name;
          dialog.close();
        },
      }, h("span", { class: "mono" }, item.name), h("span", { class: "muted" }, item.detail))));
    }
    list.replaceChildren(...rows);
    empty.hidden = rows.length > 0;
  };
  search.addEventListener("input", draw);
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    list.querySelector<HTMLButtonElement>("button")?.click();
  });
  draw();
  openDialog(dialog, search);
  // Listening after openDialog lets it hand focus back first; the insert then moves it to the editor.
  await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve()));
  if (chosen) editor.insert(`%%${chosen}%%`);
}

async function insertDate(editor: RichEditor): Promise<void> {
  let examples: string[];
  try {
    const preview = await request<Preview>("preview.get", {
      text: DATE_PRESETS.map((preset) => preset.replaceAll("{d}", "_date")).join("\n"),
    });
    examples = preview.text.split("\n");
  } catch (error) {
    await alertError(t("Data e hora"), error);
    return;
  }
  let inserted = "";
  const done = await formDialog({
    title: t("Inserir data e hora"),
    message: t("A data é calculada na hora em que o snippet expande."),
    fields: [
      {
        id: "format", label: t("Formato"), kind: "select", value: "0",
        options: [
          ...DATE_PRESETS.map((preset, index) => ({ value: String(index), label: examples[index] ?? preset })),
          { value: "custom", label: t("Personalizado…") },
        ],
      },
      {
        id: "pattern", label: t("Padrão"), mono: true, value: "dd/MM/yyyy",
        hint: t("dd dia · MM mês · MMMM mês por extenso · yyyy ano · dddd dia da semana · HH:mm:ss hora. Sem espaços."),
        shownWhen: (values) => values.format === "custom",
      },
      {
        id: "offset", label: t("Quando"), kind: "select", value: "",
        options: [
          { value: "", label: t("No momento da expansão") }, { value: "+1d", label: t("Amanhã") },
          { value: "-1d", label: t("Ontem") }, { value: "+7d", label: t("Daqui a 7 dias") },
          { value: "+1m", label: t("Daqui a 1 mês") }, { value: "custom", label: t("Outro…") },
        ],
      },
      {
        id: "amount", label: t("Deslocamento"), mono: true, value: "+15d",
        hint: t("Sinal, até três dígitos e a unidade: d (dias), w (semanas), m (meses) ou y (anos)."),
        shownWhen: (values) => values.offset === "custom",
      },
    ],
    action: t("Inserir"),
    submit: async (values) => {
      const offset = values.offset === "custom" ? String(values.amount).trim() : String(values.offset);
      if (offset && !DATE_OFFSET.test(offset)) {
        return { field: "amount", message: t("Use o formato +15d: sinal, até três dígitos e d, w, m ou y.") };
      }
      const date = `_date${offset}`;
      if (values.format === "custom") {
        const pattern = String(values.pattern).trim();
        if (!pattern || /[%\s]/.test(pattern)) {
          return { field: "pattern", message: t("O padrão não pode ter espaços nem %.") };
        }
        inserted = `%%${date}:${pattern}%%`;
      } else {
        inserted = DATE_PRESETS[Number(values.format)].replaceAll("{d}", date);
      }
      return null;
    },
  });
  if (done) editor.insert(inserted);
}

async function insertField(editor: RichEditor): Promise<void> {
  let name = "";
  const done = await formDialog({
    title: t("Inserir campo de formulário"),
    message: t("Ao expandir, o SnipType pede o valor deste campo. Depois de salvar, use Formulário para definir o tipo."),
    fields: [{ id: "name", label: t("Nome do campo"), mono: true, value: "" }],
    action: t("Inserir"),
    submit: async (values) => {
      const typed = String(values.name).trim();
      if (!/^[^%\s]+$/.test(typed)) return { field: "name", message: t("Use um nome sem espaços nem %.") };
      if (typed.startsWith("_") || typed === "clipboard-paste") {
        return { field: "name", message: t("Esse nome é reservado pelo SnipType.") };
      }
      let variables: Variables;
      try {
        variables = await loadVariables(null);
      } catch (error) {
        return { field: "name", message: errorText(error) };
      }
      if ([variables.snippets, variables.dynamics, variables.mappings].some((items) =>
        items.some((item) => item.name === typed))) {
        return { field: "name", message: t("Já existe um snippet com esse nome: a variável usaria o texto dele.") };
      }
      name = typed;
      return null;
    },
  });
  if (done) editor.insert(`%%${name}%%`);
}

/** Inserir: every kind of variable, so nobody has to know the syntax. */
function insertMenu(editor: RichEditor, exclude: string | null): HTMLElement {
  return menuButton(t("Inserir"), () => [
    { label: t("Área de transferência"), icon: "bi-clipboard", run: () => editor.insert("%%clipboard-paste%%") },
    { label: t("Snippet existente…"), icon: "bi-journal-text", run: () => void insertReference(editor, exclude) },
    { label: t("Data e hora…"), icon: "bi-calendar-event", run: () => void insertDate(editor) },
    { label: t("Posição do cursor"), icon: "bi-cursor-text", run: () => editor.insert("%%_cursor%%") },
    { label: t("Campo de formulário…"), icon: "bi-input-cursor-text", run: () => void insertField(editor) },
    { label: t("Tecla Enter"), icon: "bi-arrow-return-left", run: () => editor.insert("%%_enter%%") },
    { label: t("Tecla Tab"), icon: "bi-arrow-bar-right", run: () => editor.insert("%%_tab%%") },
  ], { title: t("Inserir variável (ou digite %%)") }, "bi-braces");
}

function renderDetail(): void {
  const host = refs.detail;
  const kind = activeKind();
  if (!host || !kind) return;
  const textos = kind === "textos";
  const collection = state.collections[kind];
  // A Mapeamentos draft stays with its own type; another type shows no editor.
  const draft = collection.draft && (textos || collection.draft.type === state.type) ? collection.draft : null;
  refs.effective = null;
  if (!draft) {
    refs.saveButton = null;
    refs.saveState = null;
    refs.hiddenNote = null;
    host.replaceChildren(h("div", { class: "blank" },
      icon(textos ? "document" : "mapping"),
      h("p", {}, textos ? t("Selecione um texto na lista ou crie um novo.")
        : t("Selecione um item na lista ou crie um novo.")),
      h("button", { type: "button", class: "primary", onclick: () => void newItem(kind) }, icon("plus"),
        textos ? t("Novo") : t("Novo item")),
    ));
    updateSaveState();
    return;
  }

  refs.saveButton = h("button", {
    type: "button", class: "primary", title: "Ctrl+S", onclick: () => void save(kind),
  }, icon("check"), t("Salvar"));
  refs.saveState = h("span", { class: "state", role: "status" });
  refs.effective = h("span", { class: "hint", id: "name-hint", "aria-live": "polite" });
  const onInput = (field: "name") => (event: Event) => {
    draft[field] = (event.target as HTMLInputElement).value;
    updateSaveState();
  };
  const heading = textos
    ? draft.original ?? t("Novo texto")
    : draft.original ? t("{name} em {type}", { name: draft.original, type: typeLabel(draft.type) })
    : t("Novo item em {type}", { type: typeLabel(draft.type) });

  refs.meta = draft.original ? h("div", { class: "meta-row" }) : null;
  const formatHint = h("span", { class: "hint", "aria-live": "polite" });
  // Only a saved snippet can be named by a variable; its own name is not offered to it.
  const exclude = textos ? draft.original : null;
  const editor = createRichEditor({
    id: "text", label: textos ? t("Texto") : t("Valor"), describedBy: "text-hint",
    value: { text: draft.text, spans: draft.spans },
    onChange: () => {
      ({ text: draft.text, spans: draft.spans } = editor.value());
      draft.rich = draft.spans.length > 0;
      formatHint.textContent = "";
      updateSaveState();
    },
  });
  host.replaceChildren(
    h("div", { class: "commands" },
      refs.saveButton,
      draft.original ? h("button", { type: "button", title: "Ctrl+D", onclick: () => void duplicateCurrent(kind) },
        t("Duplicar")) : null,
      draft.original && textos ? h("button", { type: "button", title: "F2", onclick: () => void renameCurrent() },
        t("Renomear")) : null,
      h("button", { type: "button", onclick: () => void showPreview(kind) }, t("Prévia")),
      draft.original ? h("button", { type: "button", class: "danger", title: "Delete", onclick: () => void deleteCurrent(kind) },
        t("Excluir")) : null,
      refs.saveState,
    ),
    refs.hiddenNote = h("div", { class: "hidden-note", role: "status", hidden: true }),
    h("div", { class: "editor" },
      h("h2", {}, heading),
      refs.meta,
      h("label", {},
        h("span", { id: "name-label" }, textos ? t("Trigger") : t("Identificador")),
        h("input", {
          id: "name", class: "field", value: draft.name, autocomplete: "off",
          "aria-labelledby": "name-label", "aria-describedby": "name-hint",
          spellcheck: "false", oninput: onInput("name"),
        }),
        refs.effective,
      ),
      h("div", { class: "grow text-field" },
        h("span", { class: "field-label", id: "text-label" }, textos ? t("Texto") : t("Valor")),
        h("div", { class: "editor-tools" }, formatBar(editor, formatHint), insertMenu(editor, exclude)),
        editor.element,
        attachCompletion(editor, () => completionCandidates(exclude)),
        h("span", { class: "hint", id: "text-hint" }, textos ? t("Digite %% para inserir uma variável, ou use Inserir.")
          : t("O texto que entra no lugar do trigger."), " ", formatHint),
      ),
    ),
  );
  renderMeta();
  updateSaveState();
  renderHiddenNote();
}

/** The saved item's Grupo and Favorito, redrawn in place so the draft's fields keep focus and caret. */
function renderMeta(): void {
  const host = refs.meta;
  const kind = activeKind();
  const draft = kind ? state.collections[kind].draft : null;
  if (!host || !kind || !draft?.original) return;
  const locked = state.groupsReadOnly;
  const title = locked ? readOnlyMessage() : undefined;
  const group = kind === "textos" ? h("label", { class: "inline" },
    h("span", {}, t("Grupo")),
    h("select", {
      class: "field", disabled: locked, title,
      onchange: (event: Event) => void setGroup((event.target as HTMLSelectElement).value),
    },
    h("option", { value: "", selected: !draft.groupId }, t("Sem grupo")),
    ...state.groups.map((option) => h("option", { value: option.id, selected: option.id === draft.groupId },
      option.label))),
  ) : null;
  host.replaceChildren(...(group ? [group] : []), h("button", {
    type: "button", class: "el-button", "aria-pressed": String(draft.favorite), disabled: locked, title,
    onclick: () => void setFavorite(kind, !draft.favorite),
  }, icon("favorite"), t("Favorito")), h("button", {
    type: "button", class: "el-button", onclick: () => void editForm(kind),
  }, t("Formulário…")));
  updateSaveState();
}

// ---------------------------------------------------------------------------
// Formulário: the fields a snippet asks for when it expands. Prévia: what it types.

/** The saved item a form or a preview is about, as the bridge names it. */
function formTarget(kind: Kind, draft: Draft): Record<string, unknown> {
  return kind === "mapeamentos" ? { name: draft.original, type: draft.type } : { name: draft.original };
}

/** Only the keys a field of `field.type` keeps, as the classic editor stores them. */
function storedField(field: FormFieldDef): FormFieldDef {
  const base: FormFieldDef = { name: field.name.trim(), type: field.type, default: field.default };
  if (field.label?.trim()) base.label = field.label.trim();
  if (field.type === "optional") return { ...base, default: field.default === true, content: field.content ?? "" };
  const text = typeof field.default === "string" ? field.default : "";
  if (field.type === "choice") return { ...base, default: text, options: (field.options ?? []).filter((o) => o !== "") };
  if (field.type === "date") return { ...base, default: text, output_format: field.output_format ?? "" };
  return { ...base, default: text };
}

/** A field switched to `type` gets that type's starting values where it has none. */
function retype(field: FormFieldDef, type: string, dateFormat: string): void {
  field.type = type;
  if (type === "optional") {
    field.default = field.default === true;
    field.content ??= "";
  } else {
    if (typeof field.default !== "string") field.default = "";
    if (type === "choice" && !field.options?.length) field.options = [t("Opção 1")];
    if (type === "date") {
      field.output_format ||= dateFormat;
      field.default ||= "today";
    }
  }
}

async function editForm(kind: Kind): Promise<void> {
  const draft = state.collections[kind].draft;
  if (!draft?.original) return;
  let info: FormInfo;
  try {
    info = await request<FormInfo>("form.get", formTarget(kind, draft));
  } catch (error) {
    await alertError(t("Formulário"), error);
    return;
  }
  const fields: FormFieldDef[] = info.fields.map((field) => ({ ...field, options: field.options ? [...field.options] : undefined }));
  let selected = fields.length ? 0 : -1;
  const list = h("div", { class: "field-list", role: "listbox", "aria-label": t("Campos do formulário") });
  const editor = h("div", { class: "field-editor" });
  const error = h("p", { class: "error", role: "alert" });
  const typeLabel = (type: string) => info.types.find((choice) => choice.value === type)?.label ?? type;

  const renderList = () => {
    list.replaceChildren(...(fields.length ? fields.map((field, index) => h("button", {
      type: "button", role: "option", "aria-selected": String(index === selected),
      onclick: () => {
        selected = index;
        renderList();
        renderEditor();
      },
    }, h("span", { class: "mono" }, field.name || t("(sem nome)")), h("span", { class: "muted" }, typeLabel(field.type))))
      : [h("p", { class: "muted" }, t("Nenhum campo. Use Adicionar."))]));
  };

  let fieldIds = 0;
  const input = (label: string, value: string, set: (value: string) => void, extra: Record<string, unknown> = {}) => {
    const id = `form-field-${fieldIds += 1}`;
    return h("label", { class: "dialog-field" }, h("span", { id: `${id}-label` }, label), h("input", {
      class: extra.mono ? "field mono" : "field", value, autocomplete: "off", spellcheck: "false",
      "aria-labelledby": `${id}-label`, "aria-describedby": extra.hint ? `${id}-hint` : undefined,
      oninput: (event: Event) => set((event.target as HTMLInputElement).value),
    }), extra.hint ? h("span", { class: "hint", id: `${id}-hint` }, String(extra.hint)) : null);
  };

  const renderEditor = () => {
    const field = fields[selected];
    if (!field) {
      editor.replaceChildren();
      return;
    }
    const typeSpecific: HTMLElement[] = [];
    if (field.type === "choice") {
      typeSpecific.push(h("label", { class: "dialog-field" }, h("span", {}, t("Opções (uma por linha)")),
        h("textarea", {
          class: "field", rows: 4, spellcheck: "false", value: (field.options ?? []).join("\n"),
          oninput: (event: Event) => { field.options = (event.target as HTMLTextAreaElement).value.split("\n"); },
        })));
    } else if (field.type === "date") {
      typeSpecific.push(input(t("Formato da data"), field.output_format ?? "", (value) => { field.output_format = value; },
        { mono: true, hint: t("Como a data entra no texto, por exemplo %d/%m/%Y.") }));
    } else if (field.type === "optional") {
      typeSpecific.push(input(t("Conteúdo quando selecionado"), field.content ?? "", (value) => { field.content = value; }));
    }
    editor.replaceChildren(
      input(t("Nome"), field.name, (value) => {
        field.name = value;
        renderList();
      }, { mono: true, hint: t("O %%nome%% que o texto usa.") }),
      input(t("Rótulo"), field.label ?? "", (value) => { field.label = value; }, { hint: t("O que o formulário mostra; vazio usa o nome.") }),
      h("label", { class: "dialog-field" }, h("span", {}, t("Tipo")), h("select", {
        class: "field",
        onchange: (event: Event) => {
          retype(field, (event.target as HTMLSelectElement).value, info.dateFormat);
          renderList();
          renderEditor();
        },
      }, ...info.types.map((choice) => h("option", { value: choice.value, selected: choice.value === field.type }, choice.label)))),
      field.type === "optional"
        ? h("div", { class: "dialog-field" }, h("label", { class: "el-choice" }, h("input", {
          type: "checkbox", role: "switch", class: "el-switch", checked: field.default === true,
          onchange: (event: Event) => { field.default = (event.target as HTMLInputElement).checked; },
        }), h("span", {}, t("Selecionado por padrão"))))
        : input(t("Valor padrão"), String(field.default ?? ""), (value) => { field.default = value; },
          field.type === "date" ? { hint: t("today, ou uma data como 31/12/2026.") } : {}),
      ...typeSpecific,
    );
  };

  const move = (delta: number) => {
    const target = selected + delta;
    if (selected < 0 || target < 0 || target >= fields.length) return;
    [fields[selected], fields[target]] = [fields[target], fields[selected]];
    selected = target;
    renderList();
    renderEditor();
  };

  let saved = false;
  const submit = h("button", { type: "submit", class: "primary", disabled: info.readOnly }, t("Salvar"));
  const dialog = h("dialog", { class: "wide", "aria-labelledby": "dialog-title" },
    h("form", {
      method: "dialog",
      onsubmit: async (event: Event) => {
        event.preventDefault();
        submit.disabled = true;
        let answer: FormSaveAnswer;
        try {
          answer = await request<FormSaveAnswer>("form.save", { ...formTarget(kind, draft), fields: fields.map(storedField) });
        } catch (failure) {
          error.textContent = errorText(failure);
          submit.disabled = false;
          return;
        }
        submit.disabled = false;
        if (answer.status === "invalid") {
          error.textContent = answer.message;
          if (answer.index !== null && answer.index < fields.length) {
            selected = answer.index;
            renderList();
            renderEditor();
          }
          return;
        }
        saved = true;
        dialog.close();
      },
    },
    h("h2", { id: "dialog-title" }, t("Formulário — {name}", { name: draft.original })),
    h("p", { class: "muted" }, info.variables.length
      ? t("Campos que o texto pede: {names}", { names: info.variables.map((name) => `%%${name}%%`).join(", ") })
      : t("O texto não pede campos de formulário.")),
    info.readOnly ? h("p", { class: "muted" }, readOnlyMessage()) : null,
    h("div", { class: "form-editor" },
      h("div", { class: "field-column" }, list,
        h("div", { class: "field-actions" },
          h("button", {
            type: "button", class: "el-button", onclick: () => {
              fields.push({ name: "", type: "text", default: "" });
              selected = fields.length - 1;
              renderList();
              renderEditor();
              editor.querySelector("input")?.focus();
            },
          }, icon("plus"), t("Adicionar")),
          h("button", {
            type: "button", class: "el-button danger", onclick: () => {
              if (selected < 0) return;
              fields.splice(selected, 1);
              selected = Math.min(selected, fields.length - 1);
              renderList();
              renderEditor();
            },
          }, t("Remover")),
          h("button", { type: "button", class: "el-button", onclick: () => move(-1) }, t("Mover para cima")),
          h("button", { type: "button", class: "el-button", onclick: () => move(1) }, t("Mover para baixo")),
        )),
      editor),
    error,
    h("menu", {}, submit, h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar"))),
    ),
  );
  renderList();
  renderEditor();
  await new Promise<void>((resolve) => {
    dialog.addEventListener("close", () => resolve());
    openDialog(dialog, list.querySelector("button") ?? submit);
  });
  if (saved) showReceipt(kind, { text: t("Formulário salvo às {time} · {name}", { time: clock(), name: draft.original }) });
}

/** Prévia: the editor's text as expansion would type it, fields at their defaults. */
async function showPreview(kind: Kind): Promise<void> {
  const draft = state.collections[kind].draft;
  if (!draft) return;
  // The editor's text, unsaved edits included; formatting does not change what is typed.
  const params = { ...(draft.original ? formTarget(kind, draft) : kind === "mapeamentos" ? { type: draft.type } : {}),
    text: draft.text };
  let preview: Preview;
  try {
    preview = await request<Preview>("preview.get", params);
  } catch (error) {
    await alertError(t("Prévia"), error);
    return;
  }
  const dialog = h("dialog", { class: "wide", "aria-labelledby": "dialog-title" },
    h("h2", { id: "dialog-title" }, draft.original ? t("Prévia — {name}", { name: draft.original }) : t("Prévia")),
    h("pre", { class: "preview-text", tabindex: "0" }, preview.text || " "),
    preview.status ? h("p", { class: "muted" }, preview.status) : null,
    h("menu", {}, h("button", { type: "button", class: "primary", onclick: () => dialog.close() }, t("Fechar"))),
  );
  openDialog(dialog, dialog.querySelector("button"));
}

// ---------------------------------------------------------------------------
// Dinâmicos: the built-in snippets that compute their text, on or off and renamed in place.

async function refreshDynamics(): Promise<void> {
  state.dynamics.sections = await request<DynamicSection[]>("dynamics.list");
  if (state.page === "dinamicos") renderDynamics();
}

function dynamicsReceipt(text: string): void {
  state.dynamics.receipt = text;
  if (state.page === "dinamicos") renderDynamics();
}

async function setDynamicEnabled(key: string, trigger: string, enabled: boolean): Promise<void> {
  const confirmed: SaveCheck[] = [];
  for (;;) {
    let answer: DynamicToggleAnswer;
    try {
      answer = await request<DynamicToggleAnswer>("dynamic.setEnabled", { key, enabled, confirmed });
    } catch (error) {
      await alertError(enabled ? t("Ativar") : t("Desativar"), error);
      break;
    }
    if (answer.status === "saved") {
      dynamicsReceipt(enabled ? t("Ativado às {time} · {name}", { time: clock(), name: trigger })
        : t("Desativado às {time} · {name}", { time: clock(), name: trigger }));
      break;
    }
    const choice = await ask(answer.title, answer.message, [
      { id: "ok", label: answer.action, tone: "primary" }, { id: "cancel", label: t("Cancelar") },
    ]);
    if (choice !== "ok") break;
    confirmed.push(answer.check);
  }
  // Redraw from the app either way, so a refused switch snaps back.
  await refreshDynamics();
}

async function renameDynamic(key: string, trigger: string): Promise<void> {
  let renamed: string | null = null;
  await formDialog({
    title: t("Renomear trigger"),
    message: t("Identificador armazenado: {key}", { key }),
    fields: [{ id: "trigger", label: t("Novo trigger de {trigger}", { trigger }), mono: true, value: trigger }],
    action: t("Renomear"),
    submit: async (values) => {
      const confirmed: SaveCheck[] = [];
      for (;;) {
        let answer: DynamicRenameAnswer;
        try {
          answer = await request<DynamicRenameAnswer>("dynamic.rename", {
            key, trigger: String(values.trigger), confirmed,
          });
        } catch (error) {
          return { field: "trigger", message: errorText(error) };
        }
        if (answer.status === "invalid") return { field: "trigger", message: answer.message };
        if (answer.status === "renamed") {
          renamed = answer.trigger;
          return null;
        }
        const choice = await ask(answer.title, answer.message, [
          { id: "ok", label: answer.action, tone: "primary" }, { id: "cancel", label: t("Cancelar") },
        ]);
        if (choice !== "ok") return { field: "trigger", message: "" };
        confirmed.push(answer.check);
      }
    },
  });
  if (renamed === null || renamed === trigger) return;
  dynamicsReceipt(t("Renomeado às {time} · {name}", { time: clock(), name: renamed }));
  await refreshDynamics();
}

const dynamicsRefs = {
  list: null as HTMLElement | null, count: null as HTMLElement | null, receipt: null as HTMLElement | null,
};

function dynamicsPage(): HTMLElement {
  refs.search = h("input", {
    id: "search-field", type: "search", class: "field", value: state.dynamics.query, autocomplete: "off",
    spellcheck: "false", placeholder: t("Buscar por trigger ou descrição"), "aria-label": t("Buscar snippets dinâmicos"),
    oninput: (event: Event) => {
      state.dynamics.query = (event.target as HTMLInputElement).value;
      renderDynamics();
    },
  });
  dynamicsRefs.list = h("div", { class: "dynamic-sections" });
  dynamicsRefs.count = h("span", { class: "muted" });
  dynamicsRefs.receipt = h("div", { class: "receipt", role: "status", "aria-live": "polite" });
  return h("div", { class: "settings-page" },
    h("header", {},
      h("h1", {}, t("Snippets dinâmicos")),
      h("p", { class: "muted" }, t("Triggers que montam o texto na hora: datas, indicadores, cotações e links do WhatsApp.")),
    ),
    h("div", { class: "dynamic-toolbar" },
      h("div", { class: "search" }, icon("search"), refs.search), dynamicsRefs.count),
    dynamicsRefs.receipt,
    dynamicsRefs.list,
  );
}

function renderDynamics(): void {
  const host = dynamicsRefs.list;
  if (!host || state.page !== "dinamicos") return;
  const needle = fold(state.dynamics.query.trim());
  let total = 0;
  let shown = 0;
  const sections = state.dynamics.sections.map((section) => {
    const items = section.items.filter((item) => {
      total += 1;
      return !needle || fold([section.label, item.key, item.trigger, item.description].join(" ")).includes(needle);
    });
    shown += items.length;
    if (!items.length) return null;
    const headingId = `dynamic-${section.id}`;
    return h("section", { class: "cards", "aria-labelledby": headingId },
      h("h2", { id: headingId, class: "section-title" }, section.label),
      ...items.map((item) => h("div", { class: `card dynamic${item.enabled ? "" : " off"}` },
        h("label", { class: "el-choice" },
          h("input", {
            type: "checkbox", role: "switch", class: "el-switch", checked: item.enabled,
            "aria-label": t("{trigger} ativo", { trigger: item.trigger }),
            onchange: (event: Event) => void setDynamicEnabled(item.key, item.trigger,
              (event.target as HTMLInputElement).checked),
          })),
        h("div", { class: "stack" },
          h("code", { class: "trigger" }, item.key === item.trigger ? item.trigger : `${item.key} → ${item.trigger}`),
          h("span", { class: "muted" }, item.description)),
        h("button", {
          type: "button", class: "el-button", "aria-label": t("Renomear {trigger}", { trigger: item.trigger }),
          onclick: () => void renameDynamic(item.key, item.trigger),
        },
          t("Renomear")),
      )));
  });
  dynamicsRefs.count!.textContent = t("{shown} de {total}", { shown, total });
  dynamicsRefs.receipt!.textContent = state.dynamics.receipt;
  host.replaceChildren(...(shown ? sections.filter((section) => section !== null)
    : [h("p", { class: "empty-list" }, t("Nenhum snippet dinâmico encontrado."))]));
}

// ---------------------------------------------------------------------------
// Backups: restore a backup, make one now, export the library or import a file.

async function refreshBackups(): Promise<void> {
  state.backups.items = await request<Backup[]>("backups.list");
  if (state.page === "backups") renderBackups();
}

function backupsReceipt(text: string): void {
  state.backups.receipt = text;
  if (state.page === "backups") renderBackups();
}

/** The receipt of something done from the page showing now, on that page's status line. */
function pageReceipt(text: string): void {
  const kind = activeKind();
  if (kind) showReceipt(kind, { text });
  else if (state.page === "dinamicos") dynamicsReceipt(text);
  else if (state.page === "settings") settingsReceipt(text);
  else backupsReceipt(text);
}

function settingsReceipt(text: string): void {
  state.settingsReceipt = text;
  const line = document.getElementById("settings-receipt");
  if (line) line.textContent = text;
}

function countsText(counts: ChangeCounts): string {
  return t("Novos: {new} · Sobrescritos: {overwritten} · Removidos: {removed}", { ...counts });
}

/** Settle every unsaved draft before the library is replaced under them. */
async function resolveAllDrafts(): Promise<boolean> {
  for (const kind of ["textos", "mapeamentos"] as Kind[]) {
    if (!isDirty(kind)) continue;
    if (!(await resolveDraft(kind))) return false;
  }
  return true;
}

/** After a restore or an import the editors open from the new library. */
async function libraryReplaced(): Promise<void> {
  // A receipt described the library that was there: its Desfazer must not act on the new one.
  for (const kind of ["textos", "mapeamentos"] as Kind[]) {
    state.collections[kind].draft = null;
    state.collections[kind].receipt = null;
  }
  const kind = activeKind();
  if (kind) {
    await refreshList(kind);
    renderDetail();
  }
  await refreshBackups();
}

async function createBackup(): Promise<void> {
  try {
    await request("backup.create");
  } catch (error) {
    await alertError(t("Criar backup"), error);
    return;
  }
  backupsReceipt(t("Backup criado às {time}", { time: clock() }));
  await refreshBackups();
}

async function restoreBackup(name: string): Promise<void> {
  let preview: BackupPreview;
  try {
    preview = await request<BackupPreview>("backup.preview", { name });
  } catch (error) {
    await alertError(t("Restaurar backup"), error);
    return;
  }
  const choice = await ask(t("Restaurar backup"),
    t("Backup: {taken}\n{changes}\n\nA biblioteca atual é trocada por este backup. Antes, ela é salva em um novo backup.",
      { taken: preview.when, changes: countsText(preview.counts) }),
    [{ id: "ok", label: t("Restaurar backup"), tone: "primary" }, { id: "cancel", label: t("Cancelar") }]);
  if (choice !== "ok" || !(await resolveAllDrafts())) return;
  let restored: { when: string };
  try {
    restored = await request("backup.restore", { name });
  } catch (error) {
    await alertError(t("Restaurar backup"), error);
    return;
  }
  backupsReceipt(t("Backup restaurado às {time} · {name}", { time: clock(), name: restored.when }));
  await libraryReplaced();
}

interface SaveFilePicker {
  showSaveFilePicker(options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }):
    Promise<{ name: string; createWritable(): Promise<{ write(data: string): Promise<void>; close(): Promise<void> }> }>;
}

async function exportLibrary(): Promise<void> {
  let exported: { text: string; fileName: string };
  try {
    exported = await request("library.exportText");
  } catch (error) {
    await alertError(t("Exportar biblioteca"), error);
    return;
  }
  let saved = exported.fileName;
  try {
    // The system save dialog belongs to this window; the app never sees where the copy goes.
    const handle = await (window as unknown as SaveFilePicker).showSaveFilePicker({
      suggestedName: exported.fileName, types: [{ description: "JSON", accept: { "application/json": [".json"] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(exported.text);
    await writable.close();
    saved = handle.name;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    await alertError(t("Exportar biblioteca"), t("Falha ao exportar: {error}", { error: errorText(error) }));
    return;
  }
  pageReceipt(t("Biblioteca exportada às {time} · {name}", { time: clock(), name: saved }));
}

/** Importar…: called from a click, so the file picker opens while the click still counts. */
function importLibrary(): void {
  const input = h("input", { type: "file", accept: ".json,application/json" });
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) void importFile(file);
  });
  input.click();
}

async function importFile(file: File): Promise<void> {
  const title = t("Importar biblioteca");
  let text: string;
  let counts: ImportCounts;
  try {
    text = await file.text();
    counts = await request<ImportCounts>("library.importPreview", { text });
  } catch (error) {
    await alertError(title, error);
    return;
  }
  const choice = await ask(title, t(
    "Arquivo: {file}\n\nMesclar mantém a biblioteca atual e dá prioridade ao arquivo.\n{merge}\n\nSubstituir tudo troca a biblioteca pelo arquivo.\n{replace}\n\nAntes, a biblioteca atual é salva em um backup.",
    { file: file.name, merge: countsText(counts.merge), replace: countsText(counts.replace) }), [
    { id: "merge", label: t("Mesclar"), tone: "primary" },
    { id: "replace", label: t("Substituir tudo…"), tone: "danger" },
    { id: "cancel", label: t("Cancelar") },
  ]);
  if (choice === "cancel") return;
  // Replacing drops every item the file lacks, so it takes the typed word too.
  const word = t("SUBSTITUIR");
  if (choice === "replace" && !(await formDialog({
    title: t("Substituir tudo"),
    message: t("A biblioteca inteira é trocada pelo conteúdo de {file}.\n{replace}\n\nAntes, a biblioteca atual é salva em um backup.",
      { file: file.name, replace: countsText(counts.replace) }),
    fields: [{ id: "word", label: t("Para confirmar, digite {word}", { word }), mono: true }],
    action: t("Substituir tudo"),
    danger: true,
    confirmWord: word,
    submit: async () => null,
  }))) return;
  if (!(await resolveAllDrafts())) return;
  try {
    await request("library.import", { text, mode: choice });
  } catch (error) {
    await alertError(title, error);
    return;
  }
  pageReceipt(t("Biblioteca importada às {time} · {name}", { time: clock(), name: file.name }));
  await libraryReplaced();
}

const backupsRefs = { list: null as HTMLElement | null, receipt: null as HTMLElement | null };

function sizeText(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function backupsPage(): HTMLElement {
  backupsRefs.list = h("div", { class: "backup-list" });
  backupsRefs.receipt = h("div", { class: "receipt", role: "status", "aria-live": "polite" });
  return h("div", { class: "settings-page" },
    h("header", {},
      h("h1", {}, t("Backups da biblioteca")),
      h("p", { class: "muted" }, t("Cada alteração guarda a versão anterior aqui; os 30 backups mais recentes ficam guardados.")),
      h("code", { class: "path" }, state.info?.dataDir ?? ""),
    ),
    h("div", { class: "backup-actions" },
      h("button", { type: "button", class: "primary", onclick: () => void createBackup() }, icon("plus"), t("Criar backup")),
      h("button", { type: "button", class: "el-button", onclick: () => void exportLibrary() }, t("Exportar…")),
      h("button", { type: "button", class: "el-button", onclick: () => importLibrary() }, t("Importar…")),
      h("button", { type: "button", class: "el-button", onclick: () => void request("app.openDataFolder") },
        t("Abrir pasta")),
    ),
    backupsRefs.receipt,
    backupsRefs.list,
  );
}

function renderBackups(): void {
  const host = backupsRefs.list;
  if (!host || state.page !== "backups") return;
  backupsRefs.receipt!.textContent = state.backups.receipt;
  const items = state.backups.items;
  if (!items.length) {
    host.replaceChildren(h("p", { class: "empty-list" }, t("Nenhum backup. Use Criar backup para proteger a biblioteca.")));
    return;
  }
  const count = (value: number | null) => value === null ? t("inválido") : String(value);
  host.replaceChildren(
    h("p", { class: "muted" }, t("{count} backups disponíveis", { count: items.length })),
    h("table", { class: "backups", "aria-label": t("Backups da biblioteca") },
      h("thead", {}, h("tr", {},
        h("th", { scope: "col" }, t("Quando")), h("th", { scope: "col", class: "num" }, t("Textos")),
        h("th", { scope: "col", class: "num" }, t("Listas")), h("th", { scope: "col", class: "num" }, t("Tamanho")),
        h("th", { scope: "col" }, h("span", { class: "sr-only" }, t("Ações"))))),
      h("tbody", {}, ...items.map((backup, index) => h("tr", {},
        h("td", {}, backup.when, backup.empty ? h("span", { class: "muted" }, ` · ${t("0 itens")}`) : null),
        h("td", { class: "num" }, count(backup.texts)),
        h("td", { class: "num" }, count(backup.lists)),
        h("td", { class: "num" }, sizeText(backup.size)),
        h("td", { class: "action" }, h("button", {
          type: "button", class: "el-button", disabled: backup.texts === null,
          // Two backups can share a minute, so the position keeps every button's name apart.
          "aria-label": t("Restaurar o backup {index} de {count}: {when}", {
            index: index + 1, count: items.length, when: backup.when,
          }),
          onclick: () => void restoreBackup(backup.name),
        }, t("Restaurar"))),
      ))),
    ),
  );
}

function settingsPage(): HTMLElement {
  const info = state.info!;
  const status = (card: string) => {
    const entry = state.cardStatus[card];
    return entry ? h("span", { class: `status${entry.error ? " error" : ""}`, role: "status" }, entry.text) : null;
  };
  const segment = (card: string, key: string, current: string, choices: [string, string][]) =>
    h("div", { class: "el-segment", role: "radiogroup", "aria-labelledby": `card-${card}` },
      ...choices.map(([value, label]) => h("label", {},
        h("input", {
          type: "radio", name: key, value, checked: value === current,
          onchange: () => void setSetting(card, key, value),
        }),
        h("span", {}, label))));
  const card = (id: string, title: string, body: string | Node, ...control: (Node | null)[]) =>
    h("section", { class: "card", "aria-labelledby": `card-${id}` },
      h("h2", { id: `card-${id}` }, title), h("p", {}, body), h("div", { class: "control" }, ...control));

  return h("div", { class: "settings-page" },
    h("header", {},
      h("h1", {}, t("Configurações")),
      h("p", { id: "settings-receipt", class: "receipt", role: "status", "aria-live": "polite" }, state.settingsReceipt),
      h("p", { class: "muted" }, t("Ajuste a aparência, a expansão e os dados do SnipType.")),
    ),
    h("div", { class: "cards" },
      card("language", t("Idioma"), t("Idioma da interface. O texto dos snippets não muda."),
        status("language"),
        h("select", {
          class: "field", "aria-labelledby": "card-language",
          onchange: (event: Event) => void setSetting("language", "language", (event.target as HTMLSelectElement).value),
        }, ...Object.entries(info.languages).map(([code, name]) =>
          h("option", { value: code, selected: code === info.language }, name)))),
      card("appearance", t("Aparência"), t("Siga o tema do Windows ou escolha um fixo."),
        status("appearance"),
        segment("appearance", "appearance", info.appearance,
          [["system", t("Sistema")], ["light", t("Claro")], ["dark", t("Escuro")]])),
      card("density", t("Densidade"), t("Espaço dos controles e das linhas."),
        status("density"),
        segment("density", "density", info.density,
          [["compact", t("Compacta")], ["comfortable", t("Confortável")], ["touch", t("Toque")]])),
      card("expansion", t("Modo terminador"),
        t("Expande só depois de um espaço ou pontuação, que continua no texto. Enter não conta."),
        status("expansion"),
        h("label", { class: "el-choice" },
          h("input", {
            type: "checkbox", role: "switch", class: "el-switch", checked: info.terminatorMode,
            "aria-labelledby": "card-expansion",
            onchange: (event: Event) => void setSetting("expansion", "terminatorMode",
              (event.target as HTMLInputElement).checked),
          }))),
      h("section", { class: "card hotkeys", "aria-labelledby": "card-hotkeys" },
        h("h2", { id: "card-hotkeys" }, t("Atalhos de teclado")),
        h("p", { id: "hotkeys-hint" },
          t("Clique em um campo e pressione a combinação, como Ctrl+Shift+M. Backspace desativa o atalho.")),
        status("hotkeys"),
        h("div", { class: "hotkey-rows" }, ...info.hotkeys.map((hotkey) => h("div", { class: "hotkey-row" },
          h("span", {}, hotkey.label),
          hotkeyField(hotkey.action, hotkey.label, hotkey.display),
          h("button", {
            type: "button", class: "el-button", disabled: !hotkey.binding,
            onclick: () => void saveHotkey(hotkey.action, null),
          }, t("Desativar")))))),
      h("section", { class: "card data", "aria-labelledby": "card-data" },
        h("h2", { id: "card-data" }, t("Dados")),
        h("p", {}, t("Biblioteca, backups e logs ficam nesta pasta.")),
        status("data"),
        h("div", { class: "data-rows" },
          h("div", { class: "data-row" },
            h("span", {}, t("Pasta de dados")), h("code", {}, info.dataDir),
            h("button", { type: "button", class: "el-button", onclick: () => void copyText(info.dataDir, "data") },
              t("Copiar"))),
          ...info.transfers.map(transferRow)),
        h("p", { class: "muted" }, t("A cópia espelho e o pacote de sincronização são definidos em settings.json.")),
        h("div", { class: "control" },
          h("button", { type: "button", class: "el-button", onclick: () => void request("app.openDataFolder") },
            t("Abrir pasta")))),
    ),
  );
}

// ---------------------------------------------------------------------------
// Atalhos de teclado: the three workflow hotkeys, recorded by pressing them.

/** Save all three hotkeys with `action` set to `binding` (null turns it off). */
async function saveHotkey(action: string, binding: string | null): Promise<void> {
  const info = state.info!;
  const bindings = Object.fromEntries(info.hotkeys.map((hotkey) =>
    [hotkey.action, hotkey.action === action ? binding : hotkey.binding]));
  let answer: HotkeySaveAnswer;
  try {
    answer = await request<HotkeySaveAnswer>("hotkeys.save", { bindings });
  } catch (error) {
    state.cardStatus.hotkeys = { text: errorText(error), error: true };
    renderAll();
    return;
  }
  if (answer.status === "invalid") {
    const label = info.hotkeys.find((hotkey) => hotkey.action === answer.field)?.label ?? answer.field;
    state.cardStatus.hotkeys = { text: `${label}: ${answer.message}`, error: true };
  } else {
    info.hotkeys = answer.hotkeys;
    state.cardStatus.hotkeys = { text: t("Salvo."), error: false };
  }
  renderAll();
  document.getElementById(`hotkey-${action}`)?.focus();
}

/** A field that records the next key combination pressed in it. Esc and Tab leave it as it was. */
function hotkeyField(action: string, label: string, display: string): HTMLElement {
  return h("input", {
    id: `hotkey-${action}`, class: "field hotkey", readonly: true, value: display || t("Desativado"),
    "aria-label": label, "aria-describedby": "hotkeys-hint",
    // While the field has the focus, pressing an existing hotkey records it instead of running it.
    onfocus: () => void request("hotkeys.recording", { active: true }).catch(() => undefined),
    onblur: () => void request("hotkeys.recording", { active: false }).catch(() => undefined),
    onkeydown: (event: KeyboardEvent) => {
      if (event.key === "Tab" || (event.key === "Escape" && !event.ctrlKey && !event.altKey && !event.metaKey)) {
        if (event.key === "Escape") (event.target as HTMLElement).blur();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      void request<{ binding: string | null }>("hotkeys.capture", {
        key: event.key, code: event.code, ctrl: event.ctrlKey, alt: event.altKey, shift: event.shiftKey,
        meta: event.metaKey,
      }).then((captured) => {
        if (captured.binding === null) return;
        return saveHotkey(action, captured.binding || null);
      }).catch((error) => console.error("hotkey capture failed", error));
    },
  });
}

// ---------------------------------------------------------------------------
// Keyboard, window and app events

document.addEventListener("keydown", (event) => {
  if (document.querySelector("dialog[open], .menu:popover-open")) return;
  const ctrl = event.ctrlKey || event.metaKey;
  const kind = activeKind();
  // Keys every page answers: the switcher, Editar último, the sections, the shortcut sheet.
  if (ctrl && !event.altKey && !event.shiftKey) {
    const page = PAGES[Number(event.key) - 1];
    if (/^[1-5]$/.test(event.key) && page) {
      event.preventDefault();
      void showPage(page);
      return;
    }
    const global = event.key.toLowerCase();
    if (global === "k") {
      event.preventDefault();
      showSwitcher();
      return;
    }
    if (global === "e") {
      event.preventDefault();
      if (state.info?.canEditLast) void request("app.editLast").catch((error) => console.error("edit last failed", error));
      return;
    }
    if (event.key === "/") {
      event.preventDefault();
      showShortcuts();
      return;
    }
  }
  if (kind && event.key === "Escape" && !ctrl && !event.altKey) {
    event.preventDefault();
    void escapeEditor(kind);
    return;
  }
  if (state.page === "dinamicos" && ctrl && event.key.toLowerCase() === "f") {
    event.preventDefault();
    refs.search?.focus();
    refs.search?.select();
    return;
  }
  if (!kind) return;
  if (event.key === "F2" && kind === "textos") {
    event.preventDefault();
    void renameCurrent();
    return;
  }
  if (!ctrl) return;
  const key = event.key.toLowerCase();
  if (key === "d") {
    event.preventDefault();
    void duplicateCurrent(kind);
  } else if (key === "s") {
    event.preventDefault();
    void save(kind);
  } else if (key === "n") {
    event.preventDefault();
    void newItem(kind);
  } else if (key === "f") {
    event.preventDefault();
    refs.search?.focus();
    refs.search?.select();
  }
});

// The library may change behind this window (a tray reload, a restore, an
// import): look again whenever the person comes back to it.
window.addEventListener("focus", () => {
  void request("window.focus", { focused: true }).catch(() => undefined);
  void refreshVisible().catch((error) => console.error("refresh failed", error));
});
window.addEventListener("blur", () => void request("window.focus", { focused: false }).catch(() => undefined));

void appWindow.onCloseRequested(async (event) => {
  const dirty = (["textos", "mapeamentos"] as Kind[]).filter(isDirty);
  if (!dirty.length) return;
  event.preventDefault();
  for (const kind of dirty) {
    if (state.page !== kind) await showPage(kind);
    if (!(await resolveDraft(kind))) return;
  }
  await appWindow.destroy();
});

/** Editar o último item: open the item the app points at, on its own page. */
async function takeTarget(): Promise<void> {
  const target = await request<{ kind: string; key: string; container: string | null } | null>("app.takeTarget");
  if (!target) return;
  if (target.kind === "page") {
    // Configurar atalhos from the tray: the hotkeys card in Configurações.
    await showPage(target.key as Page);
    document.getElementById("card-hotkeys")?.scrollIntoView({ block: "center" });
    (document.querySelector(".hotkey") as HTMLElement | null)?.focus();
    return;
  }
  await openTarget(target);
}

/** Show one item where it lives: a text, a mapping item in its type, or a dynamic snippet. */
async function openTarget(target: { kind: string; key: string; container: string | null }): Promise<void> {
  if (target.kind === "dynamic") {
    state.dynamics.query = target.key;
    await showPage("dinamicos");
    renderDynamics();
    return;
  }
  const kind: Kind = target.kind === "mapping" ? "mapeamentos" : "textos";
  if (kind === "mapeamentos" && target.container && target.container !== state.type) {
    if (state.page !== "mapeamentos") await showPage("mapeamentos");
    await switchType(target.container);
    if (state.type !== target.container) return;
  }
  await showPage(kind);
  await openItem(kind, target.key);
}

// ---------------------------------------------------------------------------
// Ctrl+K switcher, Ctrl+/ shortcut sheet, Esc.

/** Ctrl+K: find any item by trigger, group or content and open it, or create a text from the query. */
function showSwitcher(): void {
  let rows: SwitcherRow[] = [];
  const list = h("select", { id: "switcher-list", class: "field switcher-list", size: 12, "aria-label": t("Resultados") });
  const create = h("button", { type: "button", class: "el-button", hidden: true }, "");
  let generation = 0;
  const fill = async (query: string) => {
    const mine = ++generation;
    const found = await request<SwitcherRow[]>("switcher.search", { query }).catch(() => [] as SwitcherRow[]);
    if (mine !== generation) return;
    rows = found;
    list.replaceChildren(...rows.map((row, index) => h("option", { value: String(index) },
      `${row.label} · ${row.trigger}${row.preview ? ` — ${row.preview}` : ""}`)));
    if (rows.length) list.selectedIndex = 0;
    const name = query.trim();
    create.hidden = !name;
    create.textContent = t("Criar \"{query}\"", { query: name });
  };
  const search = h("input", {
    type: "search", class: "field", autocomplete: "off", spellcheck: "false",
    placeholder: t("Pesquisar snippets"), "aria-label": t("Pesquisar snippets"), "aria-controls": "switcher-list",
    oninput: () => void fill(search.value),
    onkeydown: (event: KeyboardEvent) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const next = list.selectedIndex + (event.key === "ArrowDown" ? 1 : -1);
        if (next >= 0 && next < rows.length) list.selectedIndex = next;
      }
    },
  });
  let chosen: SwitcherRow | null = null;
  let creating = false;
  const dialog = h("dialog", { class: "switcher", "aria-labelledby": "dialog-title" },
    h("form", {
      method: "dialog",
      onsubmit: (event: Event) => {
        event.preventDefault();
        chosen = rows[list.selectedIndex] ?? null;
        if (chosen) dialog.close();
      },
    },
    h("h2", { id: "dialog-title" }, t("Alternar snippet")),
    search,
    list,
    h("menu", {},
      h("button", { type: "submit", class: "primary" }, t("Abrir")),
      create,
      h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar")))),
  );
  create.addEventListener("click", () => {
    creating = true;
    dialog.close();
  });
  list.addEventListener("dblclick", () => dialog.querySelector("form")!.requestSubmit());
  dialog.addEventListener("close", () => {
    const query = search.value.trim();
    if (chosen) void openTarget(chosen);
    else if (creating && query) void createFromSwitcher(query);
  });
  void fill("");
  openDialog(dialog, search);
}

async function createFromSwitcher(query: string): Promise<void> {
  await showPage("textos");
  state.collections.textos.query = query;
  renderAll();
  await newItem("textos");
}

const shortcuts = (): [string, string][] => [
  ["Ctrl+N", t("Novo com a busca")],
  ["Ctrl+S", t("Salvar")],
  ["Ctrl+D", t("Duplicar item salvo")],
  ["F2", t("Renomear texto")],
  ["Delete", t("Excluir na lista (Desfazer disponível)")],
  ["Esc", t("Limpar busca / descartar rascunho com confirmação")],
  ["Ctrl+K", t("Alternar snippet")],
  ["Ctrl+E", t("Editar último")],
  ["Ctrl+F", t("Buscar")],
  ["Ctrl+1–5", t("Seções")],
  ["↓ / Enter", t("Na busca: focar a lista")],
  ["Ctrl+B / I / U", t("Negrito / itálico / sublinhado")],
  ["Ctrl+/", t("Esta lista")],
];

function showShortcuts(): void {
  const dialog = h("dialog", { "aria-labelledby": "dialog-title" },
    h("h2", { id: "dialog-title" }, t("Teclado do gerenciador")),
    h("dl", { class: "shortcuts" }, ...shortcuts().flatMap(([keys, what]) => [h("dt", {}, keys), h("dd", {}, what)])),
    h("menu", {}, h("button", { type: "button", class: "primary", onclick: () => dialog.close() }, t("OK"))),
  );
  openDialog(dialog, dialog.querySelector("button"));
}

/** Esc in a collection: clear the search first, then offer to drop the draft. */
async function escapeEditor(kind: Kind): Promise<void> {
  const collection = state.collections[kind];
  if (document.activeElement === refs.search && collection.query) {
    collection.query = "";
    refs.search!.value = "";
    renderList();
    return;
  }
  if (!isDirty(kind)) return;
  const draft = collection.draft!;
  const choice = await ask(t("Descartar alterações?"),
    t("{name} tem alterações que ainda não foram salvas.", {
      name: draft.name.trim() || draft.savedName || (kind === "textos" ? t("novo snippet") : t("novo item")),
    }),
    [{ id: "discard", label: t("Descartar"), tone: "danger" }, { id: "cancel", label: t("Cancelar") }]);
  if (choice !== "discard" || collection.draft !== draft) return;
  if (draft.original === null) collection.draft = null;
  else Object.assign(draft, { name: draft.savedName, text: draft.savedText, spans: JSON.parse(draft.savedSpans) });
  renderList();
  renderDetail();
}

const PAGES: Page[] = ["textos", "mapeamentos", "dinamicos", "backups", "settings"];

async function onAppEvent({ event: name, text }: AppEvent): Promise<void> {
  if (name === "focus") {
    await appWindow.unminimize();
    await appWindow.setFocus();
  } else if (name === "target") {
    await takeTarget();
  } else if (name === "state") {
    await refreshInfo().catch((error) => console.error("refresh failed", error));
  } else if (name === "library") {
    // The app pushes this after a reload or a restore: a Desfazer receipt described the library that was there.
    for (const kind of ["textos", "mapeamentos"] as Kind[]) state.collections[kind].receipt = null;
    await refreshVisible().catch((error) => console.error("refresh failed", error));
  } else if (name === "receipt" && text) {
    // A tray or hotkey command while the person is in this window: its receipt, not a toast.
    pageReceipt(text);
  }
}

// ---------------------------------------------------------------------------
// Where the window reopens: the last size, position and page, while that place is still on a monitor.

type Rect = { x: number; y: number; width: number; height: number };
let normalRect: Rect | null = null;
let windowSaveTimer = 0;

/** At least a grip of the title bar must land on some monitor, or the window opens centered instead. */
async function onSomeMonitor(rect: Rect): Promise<boolean> {
  const grip = { left: rect.x, right: rect.x + rect.width, top: rect.y, bottom: rect.y + 40 };
  return (await availableMonitors()).some((monitor) => {
    const left = Math.max(grip.left, monitor.position.x);
    const right = Math.min(grip.right, monitor.position.x + monitor.size.width);
    const top = Math.max(grip.top, monitor.position.y);
    const bottom = Math.min(grip.bottom, monitor.position.y + monitor.size.height);
    return right - left >= 120 && bottom - top >= 20;
  });
}

/** Put the hidden window back at its saved rectangle. True when it should then be maximized. */
async function restoreWindow(saved: WindowState | undefined): Promise<boolean> {
  if (!saved || saved.width === undefined || saved.height === undefined || saved.x === undefined
    || saved.y === undefined) return false;
  const rect = { x: saved.x, y: saved.y, width: saved.width, height: saved.height };
  if (!(await onSomeMonitor(rect))) return false;
  // Position first: moving to a monitor of another scale rescales the window, so the size comes after.
  await appWindow.setPosition(new PhysicalPosition(rect.x, rect.y));
  await appWindow.setSize(new PhysicalSize(rect.width, rect.height));
  normalRect = rect;
  return !!saved.maximized;
}

async function saveWindow(): Promise<void> {
  if (await appWindow.isMinimized()) return;
  const maximized = await appWindow.isMaximized();
  if (!maximized) {
    const position = await appWindow.outerPosition();
    const size = await appWindow.innerSize();
    normalRect = { x: position.x, y: position.y, width: size.width, height: size.height };
  }
  // A window maximized from the start keeps the default rectangle it would return to.
  const value: WindowState = { ...(normalRect ?? {}), page: state.page };
  if (normalRect) value.maximized = maximized;
  await request("window.save", { value });
}

/** Moving, resizing and changing page all end here, once things settle. */
function scheduleWindowSave(): void {
  window.clearTimeout(windowSaveTimer);
  windowSaveTimer = window.setTimeout(() => void saveWindow().catch((error) => console.error("window save failed", error)), 800);
}

async function main(): Promise<void> {
  // The window starts hidden so it does not jump to its saved place; it shows whatever happens next.
  const showAnyway = window.setTimeout(() => void appWindow.show(), 3000);
  applyAppearance();
  await startBridge((event) => void onAppEvent(event));
  try {
    await refreshInfo();
    await refreshList("textos");
    await refreshTypes();
  } catch (error) {
    root.replaceChildren(h("div", { class: "fatal", role: "alert" },
      h("h1", {}, t("O SnipType não respondeu")),
      h("p", {}, errorText(error)),
      h("p", { class: "muted" }, t("Feche esta janela e abra o gerenciador de novo pelo ícone da bandeja."))));
    window.clearTimeout(showAnyway);
    await appWindow.show();
    return;
  }
  const maximize = await restoreWindow(state.info?.window).catch((error) => {
    console.error("restore failed", error);
    return false;
  });
  window.clearTimeout(showAnyway);
  await appWindow.show();
  // A window that opens focused may never fire "focus": say where the focus is now.
  void request("window.focus", { focused: document.hasFocus() }).catch(() => undefined);
  // Maximized only once shown: a hidden window maximized first restores to its default place.
  if (maximize) await appWindow.maximize();
  void appWindow.onMoved(scheduleWindowSave);
  void appWindow.onResized(scheduleWindowSave);
  const savedPage = state.info?.window.page as Page | undefined;
  if (savedPage && savedPage !== state.page) await showPage(savedPage);
  renderAll();
  refs.search?.focus();
  await takeTarget().catch((error) => console.error("target failed", error));
}

void main();
