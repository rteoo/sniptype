/** A static snippet or an item from the selected legacy mapping type. */
export interface Item {
  name: string;
  effectiveTrigger: string;
  preview: string;
  rich: boolean;
  keys: boolean;
  favorite: boolean;
  group?: string | null;
  groupId?: string | null;
  enabled?: boolean;
  shadowed?: boolean;
  sortText?: string;
  createdAt?: number | null;
  lastUsed?: number | null;
  form?: boolean;
}

export type ListOrder = "trigger" | "text" | "created" | "used";
export type ListGrouping = "none" | "group" | "favorite" | "type";

export interface ListView {
  order: ListOrder;
  grouping: ListGrouping;
  language: string;
}

type ItemType = "plain" | "rich" | "form" | "keys";
type SectionKind = "group" | "ungrouped" | "favorite" | "other" | ItemType;
export interface SectionTitle { kind: SectionKind; label?: string }
interface Section { title: SectionTitle | null; items: Item[] }

export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function textValue(item: Item): string {
  return item.sortText ?? item.preview;
}

function compareRecent(a: number | null | undefined, b: number | null | undefined): number {
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  return b - a;
}

export function itemType(item: Item): ItemType {
  if (item.form) return "form";
  if (item.keys) return "keys";
  return item.rich ? "rich" : "plain";
}

function sectionKind(item: Item, grouping: ListGrouping): SectionKind {
  if (grouping === "group") return item.groupId ? "group" : "ungrouped";
  if (grouping === "favorite") return item.favorite ? "favorite" : "other";
  return itemType(item);
}

/** A single ordered projection backs both the visible list and keyboard search. */
export function listSections(items: Item[], query: string, view?: ListView): Section[] {
  const needle = fold(query.trim()).replace(/\s+/g, " ");
  if (!view && !needle) return [{ title: null, items }];

  const alphabetic = view && new Intl.Collator(view.language, { sensitivity: "base", numeric: true });
  const ranked: { item: Item; rank: number }[] = [];
  for (const item of items) {
    if (!needle) {
      ranked.push({ item, rank: 0 });
      continue;
    }
    const name = fold(item.name);
    const trigger = view ? fold(item.effectiveTrigger) : name;
    const rank = name.startsWith(needle) || trigger.startsWith(needle) ? 0
      : name.includes(needle) || trigger.includes(needle) ? 1
      : fold(textValue(item)).replace(/\s+/g, " ").includes(needle) ? 2 : -1;
    if (rank >= 0) ranked.push({ item, rank });
  }

  ranked.sort(({ item: a, rank: rankA }, { item: b, rank: rankB }) => {
    if (rankA !== rankB) return rankA - rankB;
    if (!view || !alphabetic) return 0;
    const byTrigger = () => alphabetic.compare(a.effectiveTrigger, b.effectiveTrigger)
      || alphabetic.compare(a.name, b.name);
    switch (view.order) {
      case "text": return alphabetic.compare(textValue(a), textValue(b)) || byTrigger();
      case "created": return compareRecent(a.createdAt, b.createdAt) || byTrigger();
      case "used": return compareRecent(a.lastUsed, b.lastUsed) || byTrigger();
      default: return byTrigger();
    }
  });
  const ordered = ranked.map(({ item }) => item);
  if (!view || !alphabetic || view.grouping === "none") return [{ title: null, items: ordered }];

  const sections = new Map<string, Section>();
  for (const item of ordered) {
    const kind = sectionKind(item, view.grouping);
    const key = kind === "group" ? `group:${item.groupId}` : kind;
    let section = sections.get(key);
    if (!section) {
      section = { title: { kind, label: kind === "group" ? item.group ?? undefined : undefined }, items: [] };
      sections.set(key, section);
    }
    section.items.push(item);
  }
  if (view.grouping === "group") {
    const grouped = [...sections.values()].filter((section) => section.title?.kind === "group");
    grouped.sort((a, b) => alphabetic.compare(a.title?.label ?? "", b.title?.label ?? ""));
    const ungrouped = sections.get("ungrouped");
    return ungrouped ? [...grouped, ungrouped] : grouped;
  }
  const sectionOrder = view.grouping === "favorite" ? ["favorite", "other"] : ["plain", "rich", "form", "keys"];
  return sectionOrder.flatMap((kind) => sections.get(kind) ?? []);
}
