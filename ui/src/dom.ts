type Child = Node | string | null | undefined | false;

// Properties that must be assigned, not set as attributes, to reflect live state.
const PROPERTIES = new Set(["value", "checked", "readOnly", "disabled", "selected"]);

/** Build an element. Text children are always text nodes: snippet data never becomes markup. */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, unknown> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value as EventListener);
    } else if (PROPERTIES.has(key)) {
      (element as unknown as Record<string, unknown>)[key] = value;
    } else if (key === "class") {
      element.className = String(value);
    } else {
      element.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) element.append(child);
  }
  return element;
}

const SVG = "http://www.w3.org/2000/svg";

/** A symbol from the design system sprite (icons.svg), decorative by default. */
export function icon(id: string, className = "tp-i"): SVGSVGElement {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}
