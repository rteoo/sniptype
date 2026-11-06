// How a `%%name%%` token reads on screen: a chip with its kind's icon and a
// label, instead of the raw syntax. The text keeps the token; only its drawing
// changes. The kinds and their order follow
// source/variable_support.classify_variable.
import { h, icon } from "./dom";
import { t } from "./i18n";
import type { Variables } from "./bridge";

export type TokenKind =
  "clipboard" | "cursor" | "key" | "date" | "condition" | "snippet" | "dynamic" | "mapping" | "field";
export interface TokenInfo { kind: TokenKind; icon: string; label: string }

/** The names the library resolves, by kind; null until `variables.list` answers. */
export interface TokenLibrary { snippets: Set<string>; dynamics: Set<string>; mappings: Set<string> }

/** A complete token. Same grammar as variable_support.VARIABLE_RE. */
export const TOKEN = /%%([^%\s]+)%%/g;

// Same grammar as builtin_tokens._DATE_RE and _CONDITION_RE.
const DATE = /^_date([+-]\d{1,3}[dwmy])?(?::(.+))?$/;
const CONDITION = /^_(if|elif)(?::(.*))?$|^_(else|endif)$/;

export function libraryFrom(variables: Variables): TokenLibrary {
  const names = (items: { name: string }[]) => new Set(items.map((item) => item.name));
  return { snippets: names(variables.snippets), dynamics: names(variables.dynamics), mappings: names(variables.mappings) };
}

function conditionLabel(condition: string | undefined): string {
  const labels: Record<string, string> = {
    morning: t("manhã"), afternoon: t("tarde"), night: t("noite"), weekday: t("dia útil"),
    weekend: t("fim de semana"), mon: t("segunda"), tue: t("terça"), wed: t("quarta"), thu: t("quinta"),
    fri: t("sexta"), sat: t("sábado"), sun: t("domingo"),
  };
  return labels[condition ?? ""] ?? condition ?? "?";
}

export function describeToken(name: string, library: TokenLibrary | null): TokenInfo {
  if (name === "clipboard-paste") return { kind: "clipboard", icon: "bi-clipboard", label: t("Área de transferência") };
  if (name === "_cursor") return { kind: "cursor", icon: "bi-cursor-text", label: t("Cursor") };
  if (name === "_enter") return { kind: "key", icon: "bi-arrow-return-left", label: "Enter" };
  if (name === "_tab") return { kind: "key", icon: "bi-arrow-bar-right", label: "Tab" };
  const date = DATE.exec(name);
  if (date) return { kind: "date", icon: "bi-calendar-event", label: [t("Data"), date[1], date[2]].filter(Boolean).join(" · ") };
  const condition = CONDITION.exec(name);
  if (condition) {
    const word = condition[1] ?? condition[3];
    const label = word === "if" ? t("Se {condition}", { condition: conditionLabel(condition[2]) })
      : word === "elif" ? t("Senão, se {condition}", { condition: conditionLabel(condition[2]) })
      : word === "else" ? t("Senão") : t("Fim da condição");
    return { kind: "condition", icon: "bi-signpost-split", label };
  }
  if (library?.snippets.has(name)) return { kind: "snippet", icon: "bi-journal-text", label: name };
  if (library?.dynamics.has(name)) return { kind: "dynamic", icon: "dynamic", label: name };
  if (library?.mappings.has(name)) return { kind: "mapping", icon: "mapping", label: name };
  return { kind: "field", icon: "bi-input-cursor-text", label: name };
}

/** The chip for one token. Not editable inside: the editor treats it as one character of its own. */
export function chip(token: string, info: TokenInfo, extraClass = ""): HTMLElement {
  return h("span", {
    class: `chip chip-${info.kind}${extraClass ? ` ${extraClass}` : ""}`, contenteditable: "false",
    "data-token": token, title: token, role: "img", "aria-label": `${info.label} (${token})`,
  }, icon(info.icon), h("span", { class: "chip-label" }, info.label));
}

/** `text` with each complete token drawn as a chip; the rest stays text. */
export function withChips(text: string, library: TokenLibrary | null): Node[] {
  const nodes: Node[] = [];
  let at = 0;
  for (const match of text.matchAll(TOKEN)) {
    if (match.index > at) nodes.push(document.createTextNode(text.slice(at, match.index)));
    nodes.push(chip(match[0], describeToken(match[1], library)));
    at = match.index + match[0].length;
  }
  if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
  return nodes;
}
