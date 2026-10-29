import "./styles/teo/foundations.css";
import "./styles/teo/elements.css";
import "./styles/teo/windows-tokens.css";
import "./styles/teo/windows-elements.css";
import "./styles/app.css";

import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  type AppInfo, BridgeError, type Choice, type Confirmation, type CopyAnswer, type CreateTypeAnswer,
  type DynamicRenameAnswer, type DynamicSection, type DynamicToggleAnswer, type Group,
  type GroupForm, type Groups, type GroupSaveAnswer, type Library, type ListFilter, type MappingEntry,
  type MappingItem, type MappingSaveAnswer, type MappingType, type RenameAnswer, type SaveAnswer, type SaveCheck,
  type Snippet, request, startBridge,
} from "./bridge";
import { h, icon } from "./dom";
import { setLanguage, t } from "./i18n";

type Kind = "textos" | "mapeamentos";
type Page = Kind | "dinamicos" | "settings";

/** One row of a collection: a static snippet, or an item of the selected mapping type. */
interface Item {
  name: string;
  effectiveTrigger: string;
  preview: string;
  rich: boolean;
  favorite: boolean;
  group?: string | null;
  enabled?: boolean;
  shadowed?: boolean;
}

/** A saved item as the editor opens it, metadata included (the list may be filtered). */
interface Entry { name: string; text: string; rich: boolean; effectiveTrigger: string; favorite: boolean;
  groupId: string | null }

/**
 * What an editor holds. `original` is the saved name it was opened from (null
 * for a new one); `type` is the mapping type a Mapeamentos draft belongs to.
 * `favorite`, `groupId` and `effectiveTrigger` describe the saved item and
 * change at once, never as part of the draft.
 */
interface Draft {
  type: string | null;
  original: string | null;
  name: string;
  text: string;
  rich: boolean;
  savedName: string;
  savedText: string;
  favorite: boolean;
  groupId: string | null;
  effectiveTrigger: string;
}

interface Receipt { text: string; undo?: () => Promise<void> }

interface Collection { items: Item[]; total: number; query: string; draft: Draft | null; receipt: Receipt | null }

type Saved = { status: "saved"; name: string };

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
};

const refs = {
  infobar: null as HTMLElement | null,
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
        trigger: draft.name, text: draft.text, original: draft.original, confirmed,
      });
      return answer.status === "saved" ? { status: "saved", name: answer.trigger } : answer;
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
        type: draft.type, name: draft.name, text: draft.text, original: draft.original, confirmed,
      });
      return answer.status === "saved" ? { status: "saved", name: answer.name } : answer;
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
    openDialog(dialog, dialog.querySelector("button.primary"));
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
  const common = { id: `dialog-${field.id}`, "aria-describedby": describedBy };
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
        const control = fieldControl(field, error.id);
        controls.set(field.id, control);
        errors.set(field.id, error);
        const hint = field.hint ? h("span", { class: "hint" }, field.hint) : null;
        // The family styles a switch only inside its .el-choice label.
        const row = field.kind === "switch"
          ? h("div", { class: "dialog-field" }, h("label", { class: "el-choice" }, control, h("span", {}, field.label)),
            hint, error)
          : h("label", { class: "dialog-field" }, h("span", {}, field.label), control, hint, error);
        rows.set(field.id, row);
        return row;
      }),
      h("menu", {},
        submitButton,
        h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar"))),
      ),
    );
    update();
    dialog.addEventListener("close", () => resolve(done));
    const first = controls.values().next().value ?? null;
    openDialog(dialog, first);
    if (first instanceof HTMLInputElement && first.type !== "checkbox") first.select();
  });
}

/**
 * A drop-down menu behind a labeled button with a chevron (DESIGN.md: never
 * icon-only). `entries` is read each time it opens, so it reflects the view.
 */
function menuButton(label: string, entries: () => { label: string; disabled?: boolean; run: () => void }[],
  attrs: Record<string, unknown> = {}): HTMLElement {
  const menu = h("div", { class: "menu", popover: "auto", role: "menu", "aria-label": label });
  const button = h("button", {
    type: "button", class: "el-button", "aria-haspopup": "menu", "aria-expanded": "false", ...attrs,
    onclick: () => {
      menu.replaceChildren(...entries().map((entry) => h("button", {
        type: "button", role: "menuitem", disabled: entry.disabled,
        onclick: () => {
          menu.hidePopover();
          entry.run();
        },
      }, entry.label)));
      const box = button.getBoundingClientRect();
      menu.style.top = `${box.bottom + 4}px`;
      menu.style.left = `${box.left}px`;
      menu.showPopover();
      menu.querySelector<HTMLElement>("button:not([disabled])")?.focus();
    },
  }, label, icon("chevron-down"));
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
    type, original: entry.name, name: entry.name, text: entry.text, rich: entry.rich,
    savedName: entry.name, savedText: entry.text,
    favorite: entry.favorite, groupId: entry.groupId, effectiveTrigger: entry.effectiveTrigger,
  };
}

function newDraft(type: string | null, name: string, text = ""): Draft {
  return {
    type, original: null, name, text, rich: false, savedName: name, savedText: "",
    favorite: false, groupId: null, effectiveTrigger: name,
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
  if (!draft || draft.rich) return false;
  return draft.name.trim() !== draft.savedName || draft.text !== draft.savedText;
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
  else Object.assign(draft, { name: draft.savedName, text: draft.savedText });
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

/** Salvar and Ctrl+S. True when nothing is left unsaved. */
async function save(kind: Kind, confirmed: SaveCheck[] = []): Promise<boolean> {
  const draft = state.collections[kind].draft;
  if (!draft || draft.rich || !isDirty(kind)) return true;
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
      { id: "ok", label: answer.action, tone: answer.check === "replace" ? "danger" : "primary" },
      { id: "cancel", label: t("Cancelar") },
    ]);
    return choice === "ok" ? save(kind, [...confirmed, answer.check]) : false;
  }
  Object.assign(draft, { original: answer.name, name: answer.name, savedName: answer.name, savedText: draft.text });
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
    // A mapping copy is a new draft of the same type; it is saved under the identifier given to it.
    collection.draft = newDraft(source.type, "", source.savedText);
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
  const navButton = (page: Page, iconId: string, label: string, extra = "") => h("button", {
    type: "button",
    class: extra || undefined,
    "aria-current": state.page === page ? "page" : "false",
    title: label,
    onclick: () => showPage(page),
  }, icon(iconId), h("span", { class: "label" }, label));

  refs.infobar = h("div", { class: "infobar", role: "region", "aria-label": t("Avisos") });
  const kind = activeKind();
  const page = h("main", { class: "page" }, refs.infobar,
    kind ? collectionPage(kind) : state.page === "dinamicos" ? dynamicsPage() : settingsPage());

  root.replaceChildren(h("div", { class: "app" },
    h("nav", { class: "navigation", "aria-label": t("Seções") },
      h("div", { class: "brand" }, icon("document"), h("span", {}, "SnipType")),
      navButton("textos", "library", t("Textos")),
      navButton("mapeamentos", "mapping", t("Mapeamentos")),
      navButton("dinamicos", "dynamic", t("Dinâmicos")),
      navButton("settings", "settings", t("Configurações"), "settings"),
      h("p", { class: "version" }, state.info ? `${state.info.version} · ${state.info.channel}` : ""),
    ),
    page,
  ));
  renderInfobar();
  if (kind) {
    renderTypeBar();
    renderViewBar();
    renderList();
    renderDetail();
    renderReceipt();
  } else if (state.page === "dinamicos") {
    renderDynamics();
  }
}

async function showPage(page: Page): Promise<void> {
  if (page === state.page) return;
  // Each editor keeps its draft while another page shows.
  state.page = page;
  renderAll();
  if (isKind(page)) {
    refs.search?.focus();
    await refreshList(page).catch((error) => console.error("refresh failed", error));
  } else if (page === "dinamicos") {
    refs.search?.focus();
    await refreshDynamics().catch((error) => console.error("refresh failed", error));
  }
}

function renderInfobar(): void {
  const host = refs.infobar;
  if (!host) return;
  const issues = state.info?.issues ?? [];
  host.replaceChildren(...issues.map((issue) => h("div", {
    class: `el-message ${issue.severity === "error" ? "error" : issue.severity === "warning" ? "warning" : "info"}`,
    role: issue.severity === "error" ? "alert" : "status",
  }, h("strong", {}, issue.title), h("span", {}, issue.body))));
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
  refs.items = h("div", { class: "items", role: "list", "aria-label": title, onkeydown: onListKey });
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
      class: "field", "aria-label": t("Grupo"),
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

function renderList(): void {
  const host = refs.items;
  const kind = activeKind();
  if (!host || !kind) return;
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
        : t("Nenhum texto ainda. Use Novo para criar o primeiro.")
      : collection.items.length ? t("Nenhum item corresponde à busca.") : t("Este tipo ainda não tem itens.");
    host.replaceChildren(h("p", { class: "empty-list" }, empty));
    return;
  }
  // ceiling: renders every row; virtualize if libraries beyond ~5k snippets feel slow.
  host.replaceChildren(...items.map((item) => h("button", {
    type: "button", class: "item", role: "listitem", "data-name": item.name,
    "aria-current": item.name === current ? "true" : "false",
    onclick: () => void openItem(kind, item.name),
  },
  h("span", { class: "trigger" }, item.effectiveTrigger === item.name
    ? item.name : `${item.name} → ${item.effectiveTrigger}`),
  h("span", { class: "badges" },
    item.favorite ? icon("favorite") : null,
    item.rich ? h("span", { class: "el-badge" }, t("formatado")) : null,
    item.shadowed ? h("span", { class: "el-badge", title: t("Um snippet dinâmico usa este trigger e tem prioridade.") },
      t("sombreado")) : null,
    item.group ? h("span", { class: "el-badge" }, item.group) : null,
    item.enabled === false ? h("span", { class: "el-badge" }, t("desativado")) : null,
  ),
  h("span", { class: "preview" }, item.preview || "—"))));
  host.querySelector<HTMLElement>(".item[aria-current=true]")?.scrollIntoView({ block: "nearest" });
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
  } else if (event.key === "Delete" && target.getAttribute("aria-current") === "true") {
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
    type: "button", class: "primary", title: "Ctrl+S", hidden: draft.rich, onclick: () => void save(kind),
  }, icon("check"), t("Salvar"));
  refs.saveState = h("span", { class: "state", role: "status" });
  refs.effective = h("span", { class: "hint", "aria-live": "polite" });
  const onInput = (field: "name" | "text") => (event: Event) => {
    draft[field] = (event.target as HTMLInputElement | HTMLTextAreaElement).value;
    updateSaveState();
  };
  const heading = textos
    ? draft.original ?? t("Novo texto")
    : draft.original ? t("{name} em {type}", { name: draft.original, type: typeLabel(draft.type) })
    : t("Novo item em {type}", { type: typeLabel(draft.type) });

  refs.meta = draft.original ? h("div", { class: "meta-row" }) : null;
  // A mapping copy starts as plain text, so formatting would be lost on the way.
  const copyBlocked = !textos && draft.rich;
  host.replaceChildren(
    h("div", { class: "commands" },
      refs.saveButton,
      draft.original ? h("button", {
        type: "button", title: copyBlocked ? t("Itens formatados são duplicados no gerenciador clássico.") : "Ctrl+D",
        disabled: copyBlocked, onclick: () => void duplicateCurrent(kind),
      }, t("Duplicar")) : null,
      draft.original && textos ? h("button", { type: "button", title: "F2", onclick: () => void renameCurrent() },
        t("Renomear")) : null,
      draft.original ? h("button", { type: "button", class: "danger", title: "Delete", onclick: () => void deleteCurrent(kind) },
        t("Excluir")) : null,
      refs.saveState,
    ),
    h("div", { class: "editor" },
      h("h2", {}, heading),
      refs.meta,
      draft.rich ? h("div", { class: "el-message", role: "note" },
        t("Este texto tem formatação. Esta janela mostra só o texto; edite a formatação no gerenciador clássico."),
        " ",
        h("button", { type: "button", class: "el-button quiet", onclick: () => void request("app.openClassicManager") },
          t("Abrir gerenciador clássico")),
      ) : null,
      h("label", {},
        h("span", {}, textos ? t("Trigger") : t("Identificador")),
        h("input", {
          id: "name", class: "field", value: draft.name, readOnly: draft.rich, autocomplete: "off",
          spellcheck: "false", oninput: onInput("name"),
        }),
        refs.effective,
      ),
      h("label", { class: "grow" },
        h("span", {}, textos ? t("Texto") : t("Valor")),
        h("textarea", { id: "text", class: "field", value: draft.text, readOnly: draft.rich, oninput: onInput("text") }),
        textos ? h("span", { class: "hint" }, t("Variáveis como %%clipboard-paste%% são resolvidas na expansão."))
          : h("span", { class: "hint" }, t("O texto que entra no lugar do trigger.")),
      ),
    ),
  );
  renderMeta();
  updateSaveState();
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
  }, icon("favorite"), t("Favorito")));
  updateSaveState();
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
        h("button", { type: "button", class: "el-button", onclick: () => void renameDynamic(item.key, item.trigger) },
          t("Renomear")),
      )));
  });
  dynamicsRefs.count!.textContent = t("{shown} de {total}", { shown, total });
  dynamicsRefs.receipt!.textContent = state.dynamics.receipt;
  host.replaceChildren(...(shown ? sections.filter((section) => section !== null)
    : [h("p", { class: "empty-list" }, t("Nenhum snippet dinâmico encontrado."))]));
}

function settingsPage(): HTMLElement {
  const info = state.info!;
  const status = (card: string) => {
    const entry = state.cardStatus[card];
    return entry ? h("span", { class: `status${entry.error ? " error" : ""}`, role: "status" }, entry.text) : null;
  };
  const segment = (card: string, key: string, current: string, choices: [string, string][]) =>
    h("div", { class: "el-segment", role: "radiogroup", "aria-label": card },
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
      card("data", t("Dados"),
        h("span", { class: "stack" }, t("Biblioteca, backups e logs ficam nesta pasta."), h("code", {}, info.dataDir)),
        h("button", { type: "button", class: "el-button", onclick: () => void request("app.openDataFolder") },
          t("Abrir pasta"))),
      card("classic", t("Gerenciador clássico"),
        t("Formulários, formatação e backups continuam no gerenciador clássico por enquanto."),
        h("button", { type: "button", class: "el-button", onclick: () => void request("app.openClassicManager") },
          t("Abrir"))),
    ),
  );
}

// ---------------------------------------------------------------------------
// Keyboard, window and app events

document.addEventListener("keydown", (event) => {
  if (document.querySelector("dialog[open], .menu:popover-open")) return;
  const ctrl = event.ctrlKey || event.metaKey;
  const kind = activeKind();
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

// The library may change behind this window (classic manager, a reload, an
// import): look again whenever the person comes back to it.
window.addEventListener("focus", () => {
  const kind = activeKind();
  const page = state.page;
  void refreshInfo()
    .then(() => kind ? refreshList(kind) : page === "dinamicos" ? refreshDynamics() : undefined)
    .catch((error) => console.error("refresh failed", error));
});

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

async function onAppEvent(name: string): Promise<void> {
  if (name === "focus") {
    await appWindow.unminimize();
    await appWindow.setFocus();
  }
}

async function main(): Promise<void> {
  applyAppearance();
  await startBridge((name) => void onAppEvent(name));
  try {
    await refreshInfo();
    await refreshList("textos");
    await refreshTypes();
  } catch (error) {
    root.replaceChildren(h("div", { class: "fatal", role: "alert" },
      h("h1", {}, t("O SnipType não respondeu")),
      h("p", {}, errorText(error)),
      h("p", { class: "muted" }, t("Feche esta janela e abra o gerenciador de novo pelo ícone da bandeja."))));
    return;
  }
  renderAll();
  refs.search?.focus();
}

void main();
