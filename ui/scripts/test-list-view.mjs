import assert from "node:assert/strict";
import { test } from "node:test";
import { listSections } from "../src/list-view.ts";

const item = (name, details = {}) => ({
  name, effectiveTrigger: name, preview: "", rich: false, keys: false, favorite: false, ...details,
});
const view = (order = "trigger", grouping = "none") => ({ order, grouping, language: "pt-BR" });
const names = (sections) => sections.flatMap(({ items }) => items.map(({ name }) => name));

test("orders by the effective trigger or full text, using the trigger to break text ties", () => {
  const items = [
    item("apelido", { effectiveTrigger: "zap-apelido", preview: "preview", sortText: "Ábaco" }),
    item("item10", { preview: "preview", sortText: "Branco" }),
    item("item2", { preview: "preview", sortText: "Branco" }),
  ];
  assert.deepEqual(names(listSections(items, "", view())), ["item2", "item10", "apelido"]);
  assert.deepEqual(names(listSections(items, "", view("text"))), ["apelido", "item2", "item10"]);
});

test("orders dated rows most recent first with unknown dates last", () => {
  const items = [
    item("a", { createdAt: null, lastUsed: 30 }),
    item("b", { createdAt: 10, lastUsed: null }),
    item("c", { createdAt: 20, lastUsed: 10 }),
    item("d", { createdAt: 20, lastUsed: 0 }),
  ];
  assert.deepEqual(names(listSections(items, "", view("created"))), ["c", "d", "b", "a"]);
  assert.deepEqual(names(listSections(items, "", view("used"))), ["a", "c", "d", "b"]);
});

test("searches prefixed triggers and full text across line breaks and ranks trigger matches first", () => {
  const items = [
    item("a", { preview: "First line", sortText: "First line\nmore\nOlá Mundo" }),
    item("b", { effectiveTrigger: "ola mundo velho" }),
    item("c", { effectiveTrigger: "novo ola mundo" }),
  ];
  assert.deepEqual(names(listSections(items, "OLA  MUNDO", view("created"))), ["b", "c", "a"]);
  assert.deepEqual(names(listSections(items, "missing", view())), []);
});

test("groups by stable identity and keeps the chosen sort within groups after search", () => {
  const items = [
    item("a", { sortText: "Lima", createdAt: 99 }),
    item("b", { group: "Ação", groupId: "1", sortText: "Lima", createdAt: 10 }),
    item("c", { group: "Ação", groupId: "2", sortText: "Lima", createdAt: 30 }),
    item("d", { group: "Ação", groupId: "1", sortText: "Lima", createdAt: 20 }),
    item("e", { group: "Zebra", groupId: "3", sortText: "Outra", createdAt: 99 }),
  ];
  const groups = listSections(items, "lima", view("created", "group"));
  assert.deepEqual(groups.map(({ title }) => title.kind), ["group", "group", "ungrouped"]);
  assert.deepEqual(groups.map(({ items }) => items.map(({ name }) => name)), [["c"], ["d", "b"], ["a"]]);
});

test("groups favorite status and gives combined types a single section", () => {
  const items = [
    item("a", { form: true, rich: true, favorite: true }),
    item("b", { rich: true, keys: true }),
    item("c", { rich: true, favorite: true }),
    item("d"),
  ];
  const favorites = listSections(items, "", view("trigger", "favorite"));
  assert.deepEqual(favorites.map(({ title }) => title.kind), ["favorite", "other"]);
  assert.deepEqual(names(favorites), ["a", "c", "b", "d"]);
  const types = listSections(items, "", view("trigger", "type"));
  assert.deepEqual(types.map(({ title }) => title.kind), ["plain", "rich", "form", "keys"]);
  assert.deepEqual(names(types), ["d", "c", "a", "b"]);
});

test("keeps legacy mapping order and ranks name matches before previews", () => {
  const mappings = [item("z", { preview: "Água" }), item("água2"), item("água1")];
  assert.deepEqual(names(listSections(mappings, "")), ["z", "água2", "água1"]);
  assert.deepEqual(names(listSections(mappings, "agua")), ["água2", "água1", "z"]);
});
