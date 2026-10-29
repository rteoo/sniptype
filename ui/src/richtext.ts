// The formatting text editor: plain text plus style spans, as the app stores them
// (source/rich_text_support.py). The model is the text and one style mask per
// character; the DOM is only ever its rendering, so what is saved is what the
// model holds, never markup the browser invented.
//
// Typing and deleting go through the browser (so dead keys and other
// composition work), then the model is read back from the DOM and redrawn.
// Enter, paste, drop, undo and redo are handled here, because the browser's
// versions would add markup or would not know about the redraws.
import { h } from "./dom";

export type Style = "bold" | "italic" | "underline" | "code" | "strike";
export interface Span { tag: Style; start: number; end: number }
export interface RichValue { text: string; spans: Span[] }

// Same bits and order as rich_text_support.STYLE_BITS / STYLE_ORDER.
const BITS: Record<Style, number> = { bold: 1, italic: 2, underline: 4, code: 8, strike: 16 };
export const STYLES: Style[] = ["bold", "italic", "underline", "code", "strike"];

interface Snapshot { text: string; masks: number[]; start: number; end: number }

export interface RichEditor {
  element: HTMLElement;
  value(): RichValue;
  /** Turn a style on over the selection, or off when all of it already has it. False without a selection. */
  toggle(style: Style): boolean;
  /** Remove every style from the selection, or from the whole text without one. */
  clear(): void;
  setReadOnly(readOnly: boolean): void;
  focus(): void;
}

function masksFrom(text: string, spans: Span[]): number[] {
  const masks = new Array<number>(text.length).fill(0);
  for (const span of spans) {
    const bit = BITS[span.tag];
    if (!bit) continue;
    for (let i = Math.max(0, span.start); i < Math.min(span.end, text.length); i += 1) masks[i] |= bit;
  }
  return masks;
}

/** Spans in the app's normalized order: (start, end, tag). */
export function spansFrom(masks: number[]): Span[] {
  const spans: Span[] = [];
  for (const tag of STYLES) {
    let start = -1;
    for (let i = 0; i <= masks.length; i += 1) {
      const on = i < masks.length && (masks[i] & BITS[tag]) !== 0;
      if (on && start < 0) start = i;
      if (!on && start >= 0) {
        spans.push({ tag, start, end: i });
        start = -1;
      }
    }
  }
  return spans.sort((a, b) => a.start - b.start || a.end - b.end || a.tag.localeCompare(b.tag));
}

/** The text a DOM subtree shows: text nodes as they are, a <br> as a line break (the end marker excluded). */
function readText(root: Node): string {
  let text = "";
  const walk = (node: Node) => {
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) text += (child as Text).data;
      else if (child instanceof HTMLBRElement) {
        if (!child.hasAttribute("data-end")) text += "\n";
      } else if (child instanceof HTMLElement) {
        // A block the browser may wrap a new line in starts on its own line.
        if ((child.tagName === "DIV" || child.tagName === "P") && text && !text.endsWith("\n")) text += "\n";
        walk(child);
      }
    }
  };
  walk(root);
  return text;
}

export function createRichEditor(options: {
  id: string; value: RichValue; label: string; describedBy?: string; readOnly?: boolean; onChange: () => void;
}): RichEditor {
  let text = options.value.text;
  let masks = masksFrom(text, options.value.spans);
  const undo: Snapshot[] = [];
  const redo: Snapshot[] = [];
  let lastEdit = 0;

  const element = h("div", {
    id: options.id, class: "field rich", role: "textbox", "aria-multiline": "true", "aria-label": options.label,
    "aria-describedby": options.describedBy,
    spellcheck: "false",
  });

  const offsetOf = (node: Node, offset: number): number => {
    const range = document.createRange();
    range.setStart(element, 0);
    range.setEnd(node, offset);
    return readText(range.cloneContents()).length;
  };

  const selection = (): [number, number] => {
    const current = window.getSelection();
    if (!current || !current.rangeCount || !element.contains(current.anchorNode)) return [text.length, text.length];
    const range = current.getRangeAt(0);
    const start = offsetOf(range.startContainer, range.startOffset);
    const end = offsetOf(range.endContainer, range.endOffset);
    return [Math.min(start, end), Math.max(start, end)];
  };

  const positionOf = (offset: number): [Node, number] => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let remaining = offset;
    let last: Text | null = null;
    for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
      if (remaining <= node.data.length) return [node, remaining];
      remaining -= node.data.length;
      last = node;
    }
    return last ? [last, last.data.length] : [element, 0];
  };

  const select = (start: number, end: number) => {
    const current = window.getSelection();
    if (!current) return;
    const range = document.createRange();
    range.setStart(...positionOf(start));
    range.setEnd(...positionOf(end));
    current.removeAllRanges();
    current.addRange(range);
  };

  const render = () => {
    const runs: Node[] = [];
    let i = 0;
    while (i < text.length) {
      const mask = masks[i];
      let j = i + 1;
      while (j < text.length && masks[j] === mask) j += 1;
      const node = document.createTextNode(text.slice(i, j));
      if (mask) {
        const span = document.createElement("span");
        span.className = STYLES.filter((style) => mask & BITS[style]).map((style) => `rt-${style}`).join(" ");
        span.append(node);
        runs.push(span);
      } else {
        runs.push(node);
      }
      i = j;
    }
    // A trailing line break needs a marker to show its empty last line, and an empty editor a place for the caret.
    const end = document.createElement("br");
    end.setAttribute("data-end", "");
    element.replaceChildren(...runs, end);
  };

  const remember = (kind: "typing" | "other") => {
    const now = Date.now();
    const [start, end] = selection();
    // Typing within a second extends the same undo step.
    if (kind === "other" || now - lastEdit > 1000 || !undo.length) {
      undo.push({ text, masks: [...masks], start, end });
      if (undo.length > 200) undo.shift();
    }
    lastEdit = kind === "typing" ? now : 0;
    redo.length = 0;
  };

  // New characters take the styles both neighbours share, as the classic editor's text widget does.
  const inherited = (at: number, after: number) =>
    at > 0 && after < masks.length ? masks[at - 1] & masks[after] : 0;

  const replace = (start: number, end: number, inserted: string) => {
    remember("other");
    const mask = inherited(start, end);
    text = text.slice(0, start) + inserted + text.slice(end);
    masks = [...masks.slice(0, start), ...new Array<number>(inserted.length).fill(mask), ...masks.slice(end)];
    render();
    select(start + inserted.length, start + inserted.length);
    options.onChange();
  };

  /** Read what the browser just typed or deleted back into the model, then redraw it. */
  const sync = () => {
    const next = readText(element);
    if (next === text) return;
    const [caret] = selection();
    let prefix = 0;
    while (prefix < text.length && prefix < next.length && text[prefix] === next[prefix]) prefix += 1;
    let suffix = 0;
    while (suffix < text.length - prefix && suffix < next.length - prefix
      && text[text.length - 1 - suffix] === next[next.length - 1 - suffix]) suffix += 1;
    // Where a run of equal characters makes the edit ambiguous, the caret says where it happened.
    suffix = Math.min(suffix, Math.max(0, next.length - caret));
    prefix = Math.min(prefix, text.length - suffix, next.length - suffix);
    const removedEnd = text.length - suffix;
    const insertedLength = next.length - suffix - prefix;
    remember(insertedLength > 0 && removedEnd === prefix ? "typing" : "other");
    const mask = inherited(prefix, removedEnd);
    masks = [...masks.slice(0, prefix), ...new Array<number>(insertedLength).fill(mask), ...masks.slice(removedEnd)];
    text = next;
    render();
    select(caret, caret);
    options.onChange();
  };

  const restore = (from: Snapshot[], to: Snapshot[]) => {
    const snapshot = from.pop();
    if (!snapshot) return;
    const [start, end] = selection();
    to.push({ text, masks: [...masks], start, end });
    ({ text, masks } = snapshot);
    lastEdit = 0;
    render();
    select(snapshot.start, snapshot.end);
    options.onChange();
  };

  let composing = false;
  element.addEventListener("compositionstart", () => { composing = true; });
  element.addEventListener("compositionend", () => {
    composing = false;
    sync();
  });
  element.addEventListener("input", () => {
    if (!composing) sync();
  });
  element.addEventListener("beforeinput", (event) => {
    const [start, end] = selection();
    switch (event.inputType) {
      case "insertParagraph":
      case "insertLineBreak":
        event.preventDefault();
        replace(start, end, "\n");
        break;
      case "insertFromPaste":
      case "insertFromDrop":
      case "insertReplacementText": {
        const pasted = event.dataTransfer?.getData("text/plain") ?? event.data ?? "";
        event.preventDefault();
        replace(start, end, pasted.replace(/\r\n?/g, "\n"));
        break;
      }
      case "historyUndo":
        event.preventDefault();
        restore(undo, redo);
        break;
      case "historyRedo":
        event.preventDefault();
        restore(redo, undo);
        break;
      default:
        if (event.inputType.startsWith("format")) event.preventDefault();
    }
  });
  element.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || element.contentEditable === "false") return;
    const key = event.key.toLowerCase();
    const style = ({ b: "bold", i: "italic", u: "underline" } as Record<string, Style>)[key];
    if (style) {
      event.preventDefault();
      toggle(style);
    } else if (key === "z" && !event.shiftKey) {
      event.preventDefault();
      restore(undo, redo);
    } else if (key === "y" || (key === "z" && event.shiftKey)) {
      event.preventDefault();
      restore(redo, undo);
    }
  });

  const toggle = (style: Style): boolean => {
    const [start, end] = selection();
    if (end <= start) return false;
    remember("other");
    const bit = BITS[style];
    const enable = masks.slice(start, end).some((mask) => (mask & bit) === 0);
    for (let i = start; i < end; i += 1) masks[i] = enable ? masks[i] | bit : masks[i] & ~bit;
    render();
    select(start, end);
    options.onChange();
    return true;
  };

  render();
  const editor: RichEditor = {
    element,
    value: () => ({ text, spans: spansFrom(masks) }),
    toggle,
    clear: () => {
      let [start, end] = selection();
      if (end <= start) [start, end] = [0, text.length];
      if (!masks.slice(start, end).some(Boolean)) return;
      remember("other");
      for (let i = start; i < end; i += 1) masks[i] = 0;
      render();
      select(start, end);
      options.onChange();
    },
    setReadOnly: (readOnly) => {
      element.contentEditable = readOnly ? "false" : "plaintext-only";
      element.setAttribute("aria-readonly", String(readOnly));
    },
    focus: () => element.focus(),
  };
  editor.setReadOnly(!!options.readOnly);
  return editor;
}
