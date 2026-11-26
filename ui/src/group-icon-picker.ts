import { h, icon } from "./dom";
import { t } from "./i18n";
import "./styles/group-icon-picker.css";

export type GroupIcon = { kind: "lucide" | "emoji"; value: string };

const SVG = "http://www.w3.org/2000/svg";
let icons: Record<string, string> | undefined;
let names: string[] = [];
let catalogRequest: Promise<void> | undefined;
function loadCatalog(): Promise<void> {
  return catalogRequest ??= import("./assets/lucide-icons.json").then(({ default: catalog }) => {
    icons = catalog;
    names = Object.keys(catalog).sort();
  }).catch((error) => {
    catalogRequest = undefined;
    throw error;
  });
}
const emoji = ["📁", "📌", "⭐", "❤️", "💡", "🏠", "💼", "📚", "🎯", "🚀", "✅", "📝", "📅", "💬", "🌟", "🔧", "🎨", "🌱", "🐱", "🇧🇷"];
const allowedElements = new Set(["path", "circle", "rect", "line", "polyline", "polygon", "ellipse"]);
const allowedAttributes = new Set(["d", "cx", "cy", "r", "x", "y", "x1", "y1", "x2", "y2", "width", "height", "rx", "ry", "points"]);

/** Render catalog geometry only through a strict SVG element/attribute allowlist. */
function lucide(name: string): SVGSVGElement | null {
  if (!icons || !Object.hasOwn(icons, name)) return null;
  const parsed = new DOMParser().parseFromString(`<svg xmlns="${SVG}">${icons[name]}</svg>`, "image/svg+xml");
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const source of Array.from(parsed.documentElement.children)) {
    if (!allowedElements.has(source.localName)) continue;
    const child = document.createElementNS(SVG, source.localName);
    for (const attr of Array.from(source.attributes)) {
      if (allowedAttributes.has(attr.name) || (attr.name === "fill" && attr.value === "currentColor")) {
        child.setAttribute(attr.name, attr.value);
      }
    }
    svg.append(child);
  }
  return svg;
}

export function groupIcon(value: GroupIcon | null | undefined): HTMLElement {
  const wrapper = h("span", { class: "group-icon-glyph", "aria-hidden": "true" });
  if (value?.kind === "emoji") {
    wrapper.append(h("span", { class: "group-icon-emoji" }, value.value));
  } else {
    wrapper.append((value?.kind === "lucide" && lucide(value.value)) || icon("groups"));
    if (value?.kind === "lucide" && !icons) {
      void loadCatalog().then(() => {
        const glyph = lucide(value.value);
        if (glyph) wrapper.replaceChildren(glyph);
      }).catch(() => { /* Keep the folder glyph if the catalog cannot load. */ });
    }
  }
  return wrapper;
}

// The entry accepts one emoji grapheme, including flags, keycaps and joined sequences.
function isEmoji(value: string): boolean {
  if (!value || !/^(?:\p{Extended_Pictographic}|\p{Regional_Indicator}|[0-9#*]\uFE0F?\u20E3)/u.test(value)) return false;
  if (Array.from(value).length > 32) return false;
  return /^(?:\p{Extended_Pictographic}\uFE0F?(?:\p{Emoji_Modifier})?(?:\u200D\p{Extended_Pictographic}\uFE0F?(?:\p{Emoji_Modifier})?)*|\p{Regional_Indicator}{2}|[0-9#*]\uFE0F?\u20E3|\u{1F3F4}[\u{E0061}-\u{E007A}]+\u{E007F})$/u.test(value);
}

export function createGroupIconPicker(initial: GroupIcon | null | undefined): {
  element: HTMLElement; changedValue: () => GroupIcon | null | undefined;
} {
  let selected: GroupIcon | null = initial ? { ...initial } : null;
  let changed = false;
  let limit = 60;
  const current = h("span", { class: "group-icon-picker-current" });
  const summary = h("summary", {}, current, h("span", {}, t("Escolher ícone")), icon("chevron-down", "tp-i group-icon-picker-chevron"));
  const search = h("input", { class: "field", type: "search", placeholder: t("Buscar ícones"), "aria-label": t("Buscar ícones") });
  const grid = h("div", { class: "group-icon-picker-grid", role: "group", "aria-label": t("Ícones") });
  const more = h("button", { type: "button", class: "group-icon-picker-more" }, t("Mostrar mais"));
  const count = h("p", { class: "group-icon-picker-count", "aria-live": "polite" });
  const emojiInput = h("input", { class: "field", type: "text", placeholder: t("Digite ou cole um emoji"), "aria-label": t("Digite ou cole um emoji"), autocomplete: "off" });
  const emojiApply = h("button", { type: "button", disabled: true }, t("Usar emoji"));
  const emojiGrid = h("div", { class: "group-icon-picker-grid", role: "group", "aria-label": t("Emojis sugeridos") });
  const details = h("details", { class: "group-icon-picker" }, summary);

  function refreshCurrent(): void {
    current.replaceChildren(groupIcon(selected));
    for (const button of details.querySelectorAll<HTMLButtonElement>("[data-icon-kind]")) {
      button.setAttribute("aria-pressed", String(button.dataset.iconKind === selected?.kind && button.dataset.iconValue === selected?.value));
    }
  }
  function choose(value: GroupIcon | null): void {
    selected = value;
    changed = true;
    refreshCurrent();
    details.open = false;
    summary.focus();
  }
  function choice(value: GroupIcon, label: string): HTMLButtonElement {
    return h("button", {
      type: "button", title: label, "aria-label": label, "aria-pressed": "false",
      "data-icon-kind": value.kind, "data-icon-value": value.value,
      onclick: () => choose(value),
    }, groupIcon(value));
  }
  function renderIcons(): void {
    if (!icons) return;
    const query = search.value.trim().toLowerCase();
    const matches = names.filter((name) => name.includes(query));
    grid.replaceChildren(...matches.slice(0, limit).map((name) => choice({ kind: "lucide", value: name }, name)));
    more.hidden = matches.length <= limit;
    count.textContent = matches.length ? t("{shown} de {count} ícones", { shown: Math.min(limit, matches.length), count: matches.length }) : t("Nenhum ícone encontrado.");
    refreshCurrent();
  }
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  search.addEventListener("input", () => { limit = 60; renderIcons(); });
  more.addEventListener("click", () => { limit += 60; renderIcons(); });
  emojiInput.addEventListener("input", () => { emojiApply.disabled = !isEmoji(emojiInput.value.trim()); });
  emojiInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (!emojiApply.disabled) emojiApply.click();
    }
  });
  emojiApply.addEventListener("click", () => { if (isEmoji(emojiInput.value.trim())) choose({ kind: "emoji", value: emojiInput.value.trim() }); });
  emojiGrid.append(...emoji.map((value) => choice({ kind: "emoji", value }, value)));
  const iconPanel = h("div", { class: "group-icon-picker-mode" }, search, grid, count, more);
  const emojiPanel = h("div", { class: "group-icon-picker-mode" }, emojiGrid,
    h("div", { class: "group-icon-picker-entry" }, emojiInput, emojiApply),
    h("p", { class: "group-icon-picker-hint" }, t("Digite ou cole um emoji, ou use o seletor de emojis do sistema.")));
  const iconsButton = h("button", { type: "button", onclick: () => showMode("lucide") }, t("Ícones"));
  const emojiButton = h("button", { type: "button", onclick: () => showMode("emoji") }, t("Emoji"));
  function showMode(mode: GroupIcon["kind"]): void {
    const showIcons = mode === "lucide";
    iconPanel.hidden = !showIcons;
    emojiPanel.hidden = showIcons;
    iconsButton.setAttribute("aria-pressed", String(showIcons));
    emojiButton.setAttribute("aria-pressed", String(!showIcons));
    if (showIcons && details.open) {
      more.hidden = true;
      if (!icons) count.textContent = t("Carregando ícones…");
      void loadCatalog().then(renderIcons).catch(() => {
        count.textContent = t("Não foi possível carregar os ícones.");
      });
    }
  }
  details.append(h("div", { class: "group-icon-picker-panel" },
    h("div", { class: "group-icon-picker-tabs" }, iconsButton, emojiButton),
    iconPanel, emojiPanel,
    h("button", { type: "button", class: "group-icon-picker-reset", onclick: () => choose(null) }, t("Usar ícone padrão")),
  ));
  showMode(initial?.kind ?? "lucide");
  details.addEventListener("toggle", () => {
    if (details.open && !iconPanel.hidden) showMode("lucide");
  });
  details.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && details.open) {
      event.preventDefault();
      event.stopPropagation();
      details.open = false;
      summary.focus();
    }
  });
  refreshCurrent();
  return { element: details, changedValue: () => changed ? selected : undefined };
}
