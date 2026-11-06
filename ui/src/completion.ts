// Typing `%%` in the editor offers the variables the app resolves, filtered by
// what follows, so nobody has to know the names by heart. The list comes from
// the caller (the app's own `variables.list`), loaded once each time it opens.
import { h } from "./dom";
import { t } from "./i18n";
import type { RichEditor } from "./richtext";
import { chip, type TokenInfo } from "./tokens";

export interface Candidate { name: string; detail: string }

const LIMIT = 8;

function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** The name typed after an opening `%%` that ends at the caret, or null. A `%%` that closes a token opens nothing. */
export function openToken(before: string): string | null {
  const match = /%%([^%\s]*)$/.exec(before.replace(/%%[^%\s]+%%/g, " "));
  return match ? match[1] : null;
}

/** Name prefix first, then name substring, then detail matches; ties keep the caller's order. */
export function rank(candidates: Candidate[], query: string): Candidate[] {
  const needle = fold(query);
  const ranked: [number, number, Candidate][] = [];
  candidates.forEach((candidate, index) => {
    const name = fold(candidate.name);
    const score = name.startsWith(needle) ? 0 : name.includes(needle) ? 1
      : fold(candidate.detail).includes(needle) ? 2 : -1;
    if (score >= 0) ranked.push([score, index, candidate]);
  });
  return ranked.sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, LIMIT).map(([, , candidate]) => candidate);
}

/** Wire the popup to `editor`; returns the popup, which the caller places beside the editor. */
export function attachCompletion(
  editor: RichEditor, load: () => Promise<Candidate[]>, describe: (name: string) => TokenInfo,
): HTMLElement {
  const id = `${editor.element.id}-completion`;
  const list = h("div", { id, class: "menu completion", popover: "manual", role: "listbox", "aria-label": t("Variáveis") });
  const target = editor.element;
  target.setAttribute("aria-autocomplete", "list");
  let candidates: Candidate[] | null = null;
  let loading = false;
  let shown: Candidate[] = [];
  let query = "";
  let active = 0;

  const isOpen = () => list.matches(":popover-open");

  const close = () => {
    if (isOpen()) list.hidePopover();
    // Reloaded on the next `%%`, so a snippet saved meanwhile shows up.
    candidates = null;
    target.removeAttribute("aria-controls");
    target.removeAttribute("aria-activedescendant");
  };

  const render = () => {
    list.replaceChildren(...shown.map((candidate, index) => h("div", {
      id: `${id}-${index}`, role: "option", class: "completion-option", "aria-selected": String(index === active),
      // The editor keeps focus and caret while an option is clicked.
      onmousedown: (event: Event) => event.preventDefault(),
      onclick: () => accept(candidate),
    }, chip(`%%${candidate.name}%%`, describe(candidate.name)), h("span", { class: "muted" }, candidate.detail))));
    target.setAttribute("aria-activedescendant", `${id}-${active}`);
  };

  const place = () => {
    const caret = editor.caretRect();
    if (!caret) return;
    list.style.left = `${Math.max(4, Math.min(caret.left, window.innerWidth - list.offsetWidth - 4))}px`;
    const below = caret.bottom + 4;
    list.style.top = below + list.offsetHeight > window.innerHeight
      ? `${Math.max(4, caret.top - list.offsetHeight - 4)}px` : `${below}px`;
  };

  const update = () => {
    const before = editor.beforeCaret();
    const typed = before === null ? null : openToken(before);
    if (typed === null) {
      close();
      return;
    }
    if (typed !== query) active = 0;
    query = typed;
    if (!candidates) {
      if (loading) return;
      loading = true;
      load().then((loaded) => {
        candidates = loaded;
        update();
      }, (error) => console.error("completion: variables did not load", error)).finally(() => { loading = false; });
      return;
    }
    shown = rank(candidates, query);
    if (!shown.length) {
      if (isOpen()) list.hidePopover();
      return;
    }
    active = Math.min(active, shown.length - 1);
    render();
    target.setAttribute("aria-controls", id);
    if (!isOpen()) list.showPopover();
    place();
  };

  const accept = (candidate: Candidate) => {
    editor.replaceBeforeCaret(query.length + 2, `%%${candidate.name}%%`);
    close();
  };

  target.addEventListener("input", (event) => {
    if (!(event as InputEvent).isComposing) update();
  });
  // Moving the caret out of the token closes the list; moving within it refilters.
  target.addEventListener("keyup", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) update();
  });
  target.addEventListener("mousedown", close);
  target.addEventListener("blur", close);
  // Capture, so the editor's own Enter and the page's Escape never see a key the list used.
  target.addEventListener("keydown", (event) => {
    if (!isOpen() || !shown.length) return;
    let used = true;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      active = (active + (event.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
      render();
    } else if (event.key === "Enter" || event.key === "Tab") {
      accept(shown[active]);
    } else if (event.key === "Escape") {
      close();
    } else {
      used = false;
    }
    if (used) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  return list;
}
