// Fail the build when a t("…") id has no English entry, or an entry is unused —
// the TypeScript counterpart of source/tests/test_i18n.py.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const src = new URL("../src/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const catalogSource = readFileSync(join(src, "i18n.ts"), "utf8");
const catalogBody = catalogSource.slice(catalogSource.indexOf("const EN_US"), catalogSource.indexOf("};"));
const keys = new Set([...catalogBody.matchAll(/^\s*"((?:[^"\\]|\\.)*)":/gm)].map((m) => JSON.parse(`"${m[1]}"`)));

const used = new Set();
for (const file of readdirSync(src).filter((name) => name.endsWith(".ts") && name !== "i18n.ts")) {
  const code = readFileSync(join(src, file), "utf8");
  for (const match of code.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) used.add(JSON.parse(`"${match[1]}"`));
}

const missing = [...used].filter((id) => !keys.has(id));
const unused = [...keys].filter((id) => !used.has(id));
for (const id of missing) console.error(`i18n: missing en-US entry: ${JSON.stringify(id)}`);
for (const id of unused) console.error(`i18n: unused en-US entry: ${JSON.stringify(id)}`);
if (missing.length || unused.length) process.exit(1);
console.log(`i18n: ${used.size} messages, all translated`);
