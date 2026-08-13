/**
 * Remove CSS rules whose selectors no longer appear in any component.
 *
 * Run with the class names to drop. Only top-level rules whose every selector
 * is covered by the drop list are removed, so a shared rule such as
 * `.a, .b { … }` survives unless both names are listed.
 */

import { readFileSync, writeFileSync } from "node:fs";

const [file, ...classes] = process.argv.slice(2);
if (!file || classes.length === 0) {
  console.error("usage: prune-css.mjs <file.css> <class> [class...]");
  process.exit(1);
}

const drop = new Set(classes);
const source = readFileSync(file, "utf8");

/** Split the sheet into top-level chunks: rules, at-rules, comments, blank runs. */
function topLevelRules(text) {
  const chunks = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        chunks.push({ start, end: i + 1, text: text.slice(start, i + 1) });
        start = i + 1;
      }
    }
  }
  if (start < text.length) chunks.push({ start, end: text.length, text: text.slice(start) });
  return chunks;
}

/** Every class name used by a selector list. */
function classesIn(selector) {
  return [...selector.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]);
}

let removed = 0;
const kept = [];
for (const chunk of topLevelRules(source)) {
  const brace = chunk.text.indexOf("{");
  if (brace === -1) {
    kept.push(chunk.text);
    continue;
  }
  const prelude = chunk.text.slice(0, brace);
  const selector = prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
  if (selector.startsWith("@") || selector.startsWith(":root") || selector === "") {
    kept.push(chunk.text);
    continue;
  }
  const used = classesIn(selector);
  if (used.length > 0 && used.every((name) => drop.has(name))) {
    // Keep any comment that preceded the rule on its own lines.
    const comment = prelude.match(/^[\s\S]*\*\//);
    if (comment) kept.push(comment[0]);
    removed += 1;
    continue;
  }
  kept.push(chunk.text);
}

writeFileSync(file, kept.join("").replace(/\n{3,}/g, "\n\n"));
console.log(`removed ${removed} rules`);
