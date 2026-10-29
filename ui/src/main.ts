import "./styles/teo/foundations.css";
import "./styles/teo/elements.css";
import "./styles/teo/windows-tokens.css";
import "./styles/teo/windows-elements.css";
import "./styles/app.css";

import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  type AppInfo, BridgeError, type LibraryItem, type SaveAnswer, type SaveCheck, type Snippet,
  request, startBridge,
} from "./bridge";
import { h, icon } from "./dom";
import { setLanguage, t } from "./i18n";

type Page = "textos" | "settings";

/** The snippet open in the editor. `original` is its saved trigger; null for a new one. */
interface Draft {
  original: string | null;
  trigger: string;
  text: string;
  rich: boolean;
  savedTrigger: string;
  savedText: string;
}

interface Receipt { text: string; undo?: () => Promise<void> }

const appWindow = getCurrentWindow();
const lightScheme = matchMedia("(prefers-color-scheme: light)");
const root = document.getElementById("app")!;

const state = {
  info: null as AppInfo | null,
  page: "textos" as Page,
  items: [] as LibraryItem[],
  query: "",
  draft: null as Draft | null,
  receipt: null as Receipt | null,
  cardStatus: {} as Record<string, { text: string; error: boolean }>,
};

const refs = {
  infobar: null as HTMLElement | null,
  items: null as HTMLElement | null,
  count: null as HTMLElement | null,
  detail: null as HTMLElement | null,
  saveState: null as HTMLElement | null,
  saveButton: null as HTMLButtonElement | null,
  receipt: null as HTMLElement | null,
  search: null as HTMLInputElement | null,
};

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

function ask(title: string, message: string, buttons: DialogButton[]): Promise<string> {
  return new Promise((resolve) => {
    const returnFocus = document.activeElement as HTMLElement | null;
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
    dialog.addEventListener("close", () => {
      dialog.remove();
      returnFocus?.focus();
      resolve(dialog.returnValue || buttons[buttons.length - 1].id);
    });
    document.body.append(dialog);
    dialog.showModal();
    (dialog.querySelector("button.primary") as HTMLButtonElement | null)?.focus();
  });
}

function alertError(title: string, error: unknown): Promise<string> {
  return ask(title, errorText(error), [{ id: "ok", label: t("OK"), tone: "primary" }]);
}

// ---------------------------------------------------------------------------
// Data

async function refreshInfo(): Promise<void> {
  state.info = await request<AppInfo>("app.info");
  setLanguage(state.info.language);
  applyAppearance();
  renderInfobar();
}

async function refreshList(): Promise<void> {
  state.items = await request<LibraryItem[]>("library.list");
  renderList();
}

function isDirty(): boolean {
  const draft = state.draft;
  if (!draft || draft.rich) return false;
  return draft.trigger.trim() !== draft.savedTrigger || draft.text !== draft.savedText;
}

/** Settle an unsaved draft before it would be dropped. True when it is safe to continue. */
async function resolveDraft(): Promise<boolean> {
  if (!isDirty()) return true;
  const name = state.draft!.trigger.trim() || t("novo snippet");
  const choice = await ask(
    t("Alterações não salvas"),
    t("{name} tem alterações que ainda não foram salvas.", { name }),
    [
      { id: "save", label: t("Salvar"), tone: "primary" },
      { id: "discard", label: t("Descartar") },
      { id: "cancel", label: t("Cancelar") },
    ],
  );
  if (choice === "save") return save();
  return choice === "discard";
}

async function openSnippet(trigger: string): Promise<void> {
  if (state.draft?.original === trigger) return;
  if (!(await resolveDraft())) return;
  let snippet: Snippet;
  try {
    snippet = await request<Snippet>("snippet.get", { trigger });
  } catch (error) {
    await alertError(t("Não foi possível abrir o snippet"), error);
    await refreshList();
    return;
  }
  state.draft = {
    original: snippet.trigger, trigger: snippet.trigger, text: snippet.text, rich: snippet.rich,
    savedTrigger: snippet.trigger, savedText: snippet.text,
  };
  renderList();
  renderDetail();
}

async function newSnippet(): Promise<void> {
  if (!(await resolveDraft())) return;
  const prefill = state.query.trim();
  state.draft = { original: null, trigger: prefill, text: "", rich: false, savedTrigger: prefill, savedText: "" };
  renderList();
  renderDetail();
  document.getElementById(prefill ? "text" : "trigger")?.focus();
}

/** Salvar and Ctrl+S. True when nothing is left unsaved. */
async function save(confirmed: SaveCheck[] = []): Promise<boolean> {
  const draft = state.draft;
  if (!draft || draft.rich) return true;
  if (!isDirty()) return true;
  let answer: SaveAnswer;
  try {
    answer = await request<SaveAnswer>("snippet.save", {
      trigger: draft.trigger, text: draft.text, original: draft.original, confirmed,
    });
  } catch (error) {
    await alertError(error instanceof BridgeError && error.code === "invalid"
      ? t("Salvar snippet") : t("Erro ao salvar"), error);
    return false;
  }
  if (answer.status === "confirm") {
    const choice = await ask(answer.title, answer.message, [
      { id: "ok", label: answer.action, tone: answer.check === "replace" ? "danger" : "primary" },
      { id: "cancel", label: t("Cancelar") },
    ]);
    return choice === "ok" ? save([...confirmed, answer.check]) : false;
  }
  Object.assign(draft, {
    original: answer.trigger, trigger: answer.trigger, savedTrigger: answer.trigger, savedText: draft.text,
  });
  showReceipt({ text: t("Salvo às {time} · {name}", { time: clock(), name: answer.trigger }) });
  await refreshList();
  renderDetail();
  return true;
}

async function deleteCurrent(): Promise<void> {
  const trigger = state.draft?.original;
  if (!trigger) return;
  let token: string;
  try {
    ({ undoToken: token } = await request<{ undoToken: string }>("snippet.delete", { trigger }));
  } catch (error) {
    await alertError(t("Excluir snippet"), error);
    return;
  }
  // Deleting asks nothing: Desfazer brings the snippet back, metadata included.
  state.draft = null;
  showReceipt({
    text: t("Excluído às {time} · {name}", { time: clock(), name: trigger }),
    undo: async () => {
      try {
        await request("snippet.undoDelete", { token });
      } catch (error) {
        await alertError(t("Desfazer exclusão"), error);
        return;
      }
      await refreshList();
      await openSnippet(trigger);
      showReceipt({ text: t("Restaurado às {time} · {name}", { time: clock(), name: trigger }) });
    },
  });
  await refreshList();
  renderDetail();
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
// Receipts: the status line under the list, with Desfazer when it applies.

let receiptTimer = 0;

function showReceipt(receipt: Receipt): void {
  state.receipt = receipt;
  window.clearTimeout(receiptTimer);
  // An undo stays offered for a while; afterwards the line keeps only the fact.
  if (receipt.undo) receiptTimer = window.setTimeout(() => showReceipt({ text: receipt.text }), 15_000);
  renderReceipt();
}

function renderReceipt(): void {
  const host = refs.receipt;
  if (!host) return;
  const receipt = state.receipt;
  host.replaceChildren(
    ...(receipt ? [h("span", {}, receipt.text)] : []),
    ...(receipt?.undo ? [h("button", {
      type: "button",
      onclick: () => {
        const undo = receipt.undo!;
        showReceipt({ text: receipt.text });
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
  const page = h("main", { class: "page" }, refs.infobar,
    state.page === "textos" ? textosPage() : settingsPage());

  root.replaceChildren(h("div", { class: "app" },
    h("nav", { class: "navigation", "aria-label": t("Seções") },
      h("div", { class: "brand" }, icon("document"), h("span", {}, "SnipType")),
      navButton("textos", "library", t("Textos")),
      navButton("settings", "settings", t("Configurações"), "settings"),
      h("p", { class: "version" }, state.info ? `${state.info.version} · ${state.info.channel}` : ""),
    ),
    page,
  ));
  renderInfobar();
  if (state.page === "textos") {
    renderList();
    renderDetail();
    renderReceipt();
  }
}

async function showPage(page: Page): Promise<void> {
  if (page === state.page) return;
  state.page = page;
  renderAll();
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

function textosPage(): HTMLElement {
  refs.search = h("input", {
    id: "search", type: "search", class: "field", value: state.query, autocomplete: "off", spellcheck: "false",
    placeholder: t("Buscar por trigger ou texto"), "aria-label": t("Buscar textos"),
    oninput: (event: Event) => {
      state.query = (event.target as HTMLInputElement).value;
      renderList();
    },
    onkeydown: (event: KeyboardEvent) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        (refs.items?.querySelector(".item") as HTMLElement | null)?.focus();
      } else if (event.key === "Enter") {
        const first = visibleItems()[0];
        if (first) void openSnippet(first.trigger);
      }
    },
  });
  refs.items = h("div", { class: "items", role: "list", "aria-label": t("Textos"), onkeydown: onListKey });
  refs.count = h("span");
  refs.receipt = h("div", { class: "receipt", role: "status", "aria-live": "polite" });
  refs.detail = h("section", { class: "detail", "aria-label": t("Editor") });

  return h("div", { class: "textos" },
    h("section", { class: "collection", "aria-labelledby": "textos-title" },
      h("div", { class: "heading" },
        h("h1", { id: "textos-title" }, t("Textos")),
        h("button", { type: "button", class: "primary", title: "Ctrl+N", onclick: () => void newSnippet() },
          icon("plus"), t("Novo")),
      ),
      h("div", { class: "search" }, icon("search"), refs.search),
      h("p", { class: "list-caption" }, h("span", {}, t("Trigger")), refs.count),
      refs.items,
      refs.receipt,
    ),
    refs.detail,
  );
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Trigger prefix first, then trigger substring, then text matches. */
function visibleItems(): LibraryItem[] {
  const needle = fold(state.query.trim());
  if (!needle) return state.items;
  const ranked: [number, LibraryItem][] = [];
  for (const item of state.items) {
    const trigger = fold(item.trigger);
    const rank = trigger.startsWith(needle) ? 0 : trigger.includes(needle) ? 1
      : fold(item.preview).includes(needle) ? 2 : -1;
    if (rank >= 0) ranked.push([rank, item]);
  }
  return ranked.sort((a, b) => a[0] - b[0]).map(([, item]) => item);
}

function renderList(): void {
  const host = refs.items;
  if (!host) return;
  const items = visibleItems();
  const current = state.draft?.original;
  refs.count!.textContent = state.query.trim()
    ? t("{shown} de {total}", { shown: items.length, total: state.items.length })
    : t("{total} textos", { total: state.items.length });
  if (!items.length) {
    host.replaceChildren(h("p", { class: "empty-list" }, state.items.length
      ? t("Nenhum texto encontrado. Ctrl+N cria um com este trigger.")
      : t("Nenhum texto ainda. Use Novo para criar o primeiro.")));
    return;
  }
  // ceiling: renders every row; virtualize if libraries beyond ~5k snippets feel slow.
  host.replaceChildren(...items.map((item) => h("button", {
    type: "button", class: "item", role: "listitem", "data-trigger": item.trigger,
    "aria-current": item.trigger === current ? "true" : "false",
    onclick: () => void openSnippet(item.trigger),
  },
  h("span", { class: "trigger" }, item.effectiveTrigger === item.trigger
    ? item.trigger : `${item.trigger} → ${item.effectiveTrigger}`),
  h("span", { class: "badges" },
    item.favorite ? icon("favorite") : null,
    item.rich ? h("span", { class: "el-badge" }, t("formatado")) : null,
    item.shadowed ? h("span", { class: "el-badge", title: t("Um snippet dinâmico usa este trigger e tem prioridade.") },
      t("sombreado")) : null,
    item.group ? h("span", { class: "el-badge" }, item.group) : null,
    !item.enabled ? h("span", { class: "el-badge" }, t("desativado")) : null,
  ),
  h("span", { class: "preview" }, item.preview || "—"))));
  host.querySelector<HTMLElement>(".item[aria-current=true]")?.scrollIntoView({ block: "nearest" });
}

function onListKey(event: KeyboardEvent): void {
  const target = event.target as HTMLElement;
  if (!target.classList.contains("item")) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const sibling = event.key === "ArrowDown" ? target.nextElementSibling : target.previousElementSibling;
    if (sibling instanceof HTMLElement) sibling.focus();
    else if (event.key === "ArrowUp") refs.search?.focus();
  } else if (event.key === "Delete" && target.dataset.trigger === state.draft?.original) {
    event.preventDefault();
    void deleteCurrent();
  }
}

function updateSaveState(): void {
  const dirty = isDirty();
  if (refs.saveButton) refs.saveButton.disabled = !dirty;
  if (refs.saveState) {
    refs.saveState.textContent = dirty ? t("Alterações não salvas")
      : state.draft?.original ? t("Salvo") : "";
    refs.saveState.classList.toggle("dirty", dirty);
  }
  document.title = dirty ? `• SnipType` : "SnipType";
}

function renderDetail(): void {
  const host = refs.detail;
  if (!host) return;
  const draft = state.draft;
  if (!draft) {
    refs.saveButton = null;
    refs.saveState = null;
    host.replaceChildren(h("div", { class: "blank" },
      icon("document"),
      h("p", {}, t("Selecione um texto na lista ou crie um novo.")),
      h("button", { type: "button", class: "primary", onclick: () => void newSnippet() }, icon("plus"), t("Novo")),
    ));
    updateSaveState();
    return;
  }

  refs.saveButton = h("button", {
    type: "button", class: "primary", title: "Ctrl+S", hidden: draft.rich, onclick: () => void save(),
  }, icon("check"), t("Salvar"));
  refs.saveState = h("span", { class: "state", role: "status" });
  const onInput = (field: "trigger" | "text") => (event: Event) => {
    draft[field] = (event.target as HTMLInputElement | HTMLTextAreaElement).value;
    updateSaveState();
  };

  host.replaceChildren(
    h("div", { class: "commands" },
      refs.saveButton,
      draft.original ? h("button", { type: "button", class: "danger", title: "Delete", onclick: () => void deleteCurrent() },
        t("Excluir")) : null,
      refs.saveState,
    ),
    h("div", { class: "editor" },
      h("h2", {}, draft.original ? draft.original : t("Novo texto")),
      draft.rich ? h("div", { class: "el-message", role: "note" },
        t("Este texto tem formatação. Esta janela mostra só o texto; edite a formatação no gerenciador clássico."),
        " ",
        h("button", { type: "button", class: "el-button quiet", onclick: () => void request("app.openClassicManager") },
          t("Abrir gerenciador clássico")),
      ) : null,
      h("label", {},
        h("span", {}, t("Trigger")),
        h("input", {
          id: "trigger", class: "field", value: draft.trigger, readOnly: draft.rich, autocomplete: "off",
          spellcheck: "false", oninput: onInput("trigger"),
        }),
        h("span", { class: "hint" }, t("O que você digita para expandir. Triggers com '_' são reservados.")),
      ),
      h("label", { class: "grow" },
        h("span", {}, t("Texto")),
        h("textarea", { id: "text", class: "field", value: draft.text, readOnly: draft.rich, oninput: onInput("text") }),
        h("span", { class: "hint" }, t("Variáveis como %%clipboard-paste%% são resolvidas na expansão.")),
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
        t("Mapeamentos, snippets dinâmicos, formulários, grupos e backups continuam no gerenciador clássico por enquanto."),
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
  if (!ctrl || state.page !== "textos") return;
  const key = event.key.toLowerCase();
  if (key === "s") {
    event.preventDefault();
    void save();
  } else if (key === "n") {
    event.preventDefault();
    void newSnippet();
  } else if (key === "f") {
    event.preventDefault();
    refs.search?.focus();
    refs.search?.select();
  }
});

// The library may change behind this window (classic manager, a reload, an
// import): look again whenever the person comes back to it.
window.addEventListener("focus", () => {
  void refreshInfo().then(refreshList).catch((error) => console.error("refresh failed", error));
});

void appWindow.onCloseRequested(async (event) => {
  if (!isDirty()) return;
  event.preventDefault();
  if (await resolveDraft()) await appWindow.destroy();
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
    await refreshList();
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
