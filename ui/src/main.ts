import "./styles/teo/foundations.css";
import "./styles/teo/elements.css";
import "./styles/teo/windows-tokens.css";
import "./styles/teo/windows-elements.css";
import "./styles/app.css";

import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  type AppInfo, BridgeError, type CreateTypeAnswer, type LibraryItem, type MappingEntry, type MappingItem,
  type MappingSaveAnswer, type MappingType, type SaveAnswer, type SaveCheck, type Snippet,
  request, startBridge,
} from "./bridge";
import { h, icon } from "./dom";
import { setLanguage, t } from "./i18n";

type Kind = "textos" | "mapeamentos";
type Page = Kind | "settings";

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

/**
 * What an editor holds. `original` is the saved name it was opened from (null
 * for a new one); `type` is the mapping type a Mapeamentos draft belongs to.
 */
interface Draft {
  type: string | null;
  original: string | null;
  name: string;
  text: string;
  rich: boolean;
  savedName: string;
  savedText: string;
}

interface Receipt { text: string; undo?: () => Promise<void> }

interface Collection { items: Item[]; query: string; draft: Draft | null; receipt: Receipt | null }

type Saved = { status: "saved"; name: string };
type Confirm = Extract<SaveAnswer, { status: "confirm" }>;

/** How each collection reaches the app, so both pages share one list and editor. */
interface Source {
  list(): Promise<Item[]>;
  get(name: string): Promise<{ name: string; text: string; rich: boolean }>;
  save(draft: Draft, confirmed: SaveCheck[]): Promise<Saved | Confirm>;
  remove(draft: Draft): Promise<string>;
  undo(token: string): Promise<unknown>;
}

const appWindow = getCurrentWindow();
const lightScheme = matchMedia("(prefers-color-scheme: light)");
const root = document.getElementById("app")!;

const blank = (): Collection => ({ items: [], query: "", draft: null, receipt: null });

const state = {
  info: null as AppInfo | null,
  page: "textos" as Page,
  collections: { textos: blank(), mapeamentos: blank() } as Record<Kind, Collection>,
  types: [] as MappingType[],
  type: "_cpf_numbers",
  cardStatus: {} as Record<string, { text: string; error: boolean }>,
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
};

const sources: Record<Kind, Source> = {
  textos: {
    list: async () => (await request<LibraryItem[]>("library.list")).map((item) => ({ ...item, name: item.trigger })),
    get: async (name) => {
      const snippet = await request<Snippet>("snippet.get", { trigger: name });
      return { name: snippet.trigger, text: snippet.text, rich: snippet.rich };
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
  },
  mapeamentos: {
    list: () => request<MappingItem[]>("mapping.list", { type: state.type }),
    get: (name) => request<MappingEntry>("mapping.get", { type: state.type, name }),
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
  },
};

function isKind(page: Page): page is Kind {
  return page !== "settings";
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

interface FormField { id: string; label: string; hint?: string; mono?: boolean }

/**
 * A dialog with text fields. `submit` answers null to close, or the field and
 * message to show under it while the dialog stays open. `confirmWord` keeps
 * the submit button off until the first field holds exactly that word.
 */
function formDialog(options: {
  title: string; message?: string; fields: FormField[]; action: string; danger?: boolean; confirmWord?: string;
  submit: (values: Record<string, string>) => Promise<{ field: string; message: string } | null>;
}): Promise<boolean> {
  return new Promise((resolve) => {
    const inputs = new Map<string, HTMLInputElement>();
    const errors = new Map<string, HTMLElement>();
    const submitButton = h("button", {
      type: "submit", class: options.danger ? "danger-fill" : "primary", disabled: !!options.confirmWord,
    }, options.action);
    let done = false;
    const dialog = h("dialog", { "aria-labelledby": "dialog-title" },
      h("form", {
        method: "dialog",
        onsubmit: async (event: Event) => {
          event.preventDefault();
          const values = Object.fromEntries([...inputs].map(([id, input]) => [id, input.value]));
          submitButton.disabled = true;
          const problem = await options.submit(values);
          submitButton.disabled = false;
          for (const [id, element] of errors) element.textContent = id === problem?.field ? problem.message : "";
          if (problem) {
            inputs.get(problem.field)?.setAttribute("aria-invalid", "true");
            inputs.get(problem.field)?.focus();
            return;
          }
          done = true;
          dialog.close();
        },
      },
      h("h2", { id: "dialog-title" }, options.title),
      options.message ? h("p", {}, options.message) : null,
      ...options.fields.map((field) => {
        const input = h("input", {
          id: `dialog-${field.id}`, class: field.mono ? "field mono" : "field", autocomplete: "off", spellcheck: "false",
          "aria-describedby": `dialog-${field.id}-error`,
          oninput: () => {
            input.removeAttribute("aria-invalid");
            if (options.confirmWord) submitButton.disabled = inputs.get(options.fields[0].id)!.value.trim() !== options.confirmWord;
          },
        });
        inputs.set(field.id, input);
        const error = h("span", { id: `dialog-${field.id}-error`, class: "error", role: "alert" });
        errors.set(field.id, error);
        return h("label", { class: "dialog-field" },
          h("span", {}, field.label), input, field.hint ? h("span", { class: "hint" }, field.hint) : null, error);
      }),
      h("menu", {},
        submitButton,
        h("button", { type: "button", onclick: () => dialog.close() }, t("Cancelar"))),
      ),
    );
    dialog.addEventListener("close", () => resolve(done));
    openDialog(dialog, inputs.values().next().value ?? null);
  });
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

async function refreshList(kind: Kind): Promise<void> {
  if (kind === "mapeamentos") await refreshTypes();
  state.collections[kind].items = await sources[kind].list();
  if (state.page === kind) {
    renderList();
    renderTypeBar();
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
  return choice === "discard";
}

async function openItem(kind: Kind, name: string): Promise<void> {
  const collection = state.collections[kind];
  const type = kind === "mapeamentos" ? state.type : null;
  if (collection.draft?.original === name && collection.draft.type === type) return;
  if (!(await resolveDraft(kind))) return;
  let entry: { name: string; text: string; rich: boolean };
  try {
    entry = await sources[kind].get(name);
  } catch (error) {
    await alertError(kind === "textos" ? t("Não foi possível abrir o snippet") : t("Não foi possível abrir o item"),
      error);
    await refreshList(kind);
    return;
  }
  collection.draft = {
    type, original: entry.name, name: entry.name, text: entry.text, rich: entry.rich,
    savedName: entry.name, savedText: entry.text,
  };
  renderList();
  renderDetail();
}

async function newItem(kind: Kind): Promise<void> {
  if (!(await resolveDraft(kind))) return;
  const collection = state.collections[kind];
  const prefill = collection.query.trim();
  collection.draft = {
    type: kind === "mapeamentos" ? state.type : null,
    original: null, name: prefill, text: "", rich: false, savedName: prefill, savedText: "",
  };
  renderList();
  renderDetail();
  document.getElementById(prefill ? "text" : "name")?.focus();
}

/** Salvar and Ctrl+S. True when nothing is left unsaved. */
async function save(kind: Kind, confirmed: SaveCheck[] = []): Promise<boolean> {
  const draft = state.collections[kind].draft;
  if (!draft || draft.rich || !isDirty(kind)) return true;
  let answer: Saved | Confirm;
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
        answer = await request<CreateTypeAnswer>("mapping.createType", { name: values.name, prefix: values.prefix });
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
  const page = h("main", { class: "page" }, refs.infobar, kind ? collectionPage(kind) : settingsPage());

  root.replaceChildren(h("div", { class: "app" },
    h("nav", { class: "navigation", "aria-label": t("Seções") },
      h("div", { class: "brand" }, icon("document"), h("span", {}, "SnipType")),
      navButton("textos", "library", t("Textos")),
      navButton("mapeamentos", "mapping", t("Mapeamentos")),
      navButton("settings", "settings", t("Configurações"), "settings"),
      h("p", { class: "version" }, state.info ? `${state.info.version} · ${state.info.channel}` : ""),
    ),
    page,
  ));
  renderInfobar();
  if (kind) {
    renderTypeBar();
    renderList();
    renderDetail();
    renderReceipt();
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
    id: "search", type: "search", class: "field", value: collection.query, autocomplete: "off", spellcheck: "false",
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

  return h("div", { class: "textos" },
    h("section", { class: "collection", "aria-labelledby": "collection-title" },
      h("div", { class: "heading" },
        h("h1", { id: "collection-title" }, title),
        h("button", { type: "button", class: "primary", title: "Ctrl+N", onclick: () => void newItem(kind) },
          icon("plus"), textos ? t("Novo") : t("Novo item")),
      ),
      typeBar.host,
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
  refs.count!.textContent = collection.query.trim()
    ? t("{shown} de {total}", { shown: items.length, total: collection.items.length })
    : textos ? t("{total} textos", { total: collection.items.length })
    : t("{total} itens", { total: collection.items.length });
  if (!items.length) {
    const empty = textos
      ? collection.items.length ? t("Nenhum texto encontrado. Ctrl+N cria um com este trigger.")
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
  if (refs.effective && draft) {
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
  if (!textos) refs.effective = h("span", { class: "hint", "aria-live": "polite" });
  const onInput = (field: "name" | "text") => (event: Event) => {
    draft[field] = (event.target as HTMLInputElement | HTMLTextAreaElement).value;
    updateSaveState();
  };
  const heading = textos
    ? draft.original ?? t("Novo texto")
    : draft.original ? t("{name} em {type}", { name: draft.original, type: typeLabel(draft.type) })
    : t("Novo item em {type}", { type: typeLabel(draft.type) });

  host.replaceChildren(
    h("div", { class: "commands" },
      refs.saveButton,
      draft.original ? h("button", { type: "button", class: "danger", title: "Delete", onclick: () => void deleteCurrent(kind) },
        t("Excluir")) : null,
      refs.saveState,
    ),
    h("div", { class: "editor" },
      h("h2", {}, heading),
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
        textos ? h("span", { class: "hint" }, t("O que você digita para expandir. Triggers com '_' são reservados."))
          : refs.effective,
      ),
      h("label", { class: "grow" },
        h("span", {}, textos ? t("Texto") : t("Valor")),
        h("textarea", { id: "text", class: "field", value: draft.text, readOnly: draft.rich, oninput: onInput("text") }),
        textos ? h("span", { class: "hint" }, t("Variáveis como %%clipboard-paste%% são resolvidas na expansão."))
          : h("span", { class: "hint" }, t("O texto que entra no lugar do trigger.")),
      ),
    ),
  );
  updateSaveState();
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
        t("Snippets dinâmicos, formulários, grupos e backups continuam no gerenciador clássico por enquanto."),
        h("button", { type: "button", class: "el-button", onclick: () => void request("app.openClassicManager") },
          t("Abrir"))),
    ),
  );
}

// ---------------------------------------------------------------------------
// Keyboard, window and app events

document.addEventListener("keydown", (event) => {
  if (document.querySelector("dialog[open]")) return;
  const ctrl = event.ctrlKey || event.metaKey;
  const kind = activeKind();
  if (!ctrl || !kind) return;
  const key = event.key.toLowerCase();
  if (key === "s") {
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
  void refreshInfo().then(() => kind && refreshList(kind)).catch((error) => console.error("refresh failed", error));
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
