// Every section says who wrote it (house#92): a collector-stamped section reads as generated with its age, a section
// with no stamp reads as written by hand with the day the board last changed by hand, and `asOf` wins over both.
//
// Run:  node tests/test_wrote_marks.mjs      (from the statusgen root)

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

let passed = 0;
const test = (name, fn) => {
  try { fn(); console.log(`✓ ${name}`); passed++; }
  catch (err) { console.error(`✗ ${name}\n  ${err.message}`); process.exitCode = 1; }
};

class Node_ {
  constructor(tag) { this.tagName = String(tag).toUpperCase(); this.children = []; this.attributes = {}; this.style = {}; this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false }; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  append(...kids) { this.children.push(...kids.filter(Boolean)); }
  appendChild(k) { this.children.push(k); return k; }
  addEventListener() {}
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return (this._text ?? "") + this.children.map((c) => c.textContent ?? c.nodeValue ?? c ?? "").join(""); }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

function load() {
  const doc = {
    createElement: (t) => new Node_(t),
    createTextNode: (v) => ({ nodeValue: String(v), textContent: String(v) }),
    getElementById: () => new Node_("div"), addEventListener: () => {}, querySelector: () => null, readyState: "loading", hidden: false,
  };
  const sandbox = {
    document: doc, Node: Node_, console: { warn() {}, error() {}, log() {} }, module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/" }, history: { replaceState() {} },
    fetch: () => Promise.reject(new Error("no network")), setTimeout, clearTimeout, setInterval, clearInterval, encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox; sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return sandbox.module.exports;
}
const api = load();

/** Every element whose class attribute holds `cls`, anywhere in the tree. */
function withClass(node, cls, out = []) {
  if (!node || typeof node !== "object") return out;
  if (String(node.attributes?.class ?? "").split(" ").includes(cls)) out.push(node);
  for (const kid of node.children ?? []) withClass(kid, cls, out);
  return out;
}
function render(board) { const root = new Node_("div"); api.renderBoard(board, root, null); return root; }

const recent = new Date(Date.now() - 12 * 60 * 1000).toISOString().replace(/\.\d+Z$/, "Z");

test("a section a collector stamped reads as generated, with the age of its last data", () => {
  const root = render({ title: "T", handChangedAt: "2026-07-08", sections: [{ kind: "cards", title: "Shipped", generatedAt: recent, items: [{ q: "x" }] }] });
  const marks = withClass(root, "gen");
  assert.equal(marks.length, 1);
  assert.match(marks[0].textContent, /^generated 12m ago$/);
  assert.equal(withClass(root, "hand").length, 0);
});

test("a section with no stamp reads as written by hand, with the day the board last changed by hand", () => {
  const root = render({ title: "T", handChangedAt: "2026-07-08", sections: [{ kind: "cards", title: "Notes", items: [{ q: "x" }] }] });
  const marks = withClass(root, "hand");
  assert.equal(marks.length, 1);
  assert.equal(marks[0].textContent, "by hand · 2026-07-08");
  assert.match(marks[0].attributes.title, /last changed by hand on 2026-07-08/);
});

test("the untitled hero stats row and the banner carry the mark too, since they have no heading", () => {
  const root = render({ title: "T", handChangedAt: "2026-07-08", sections: [
    { kind: "stats", items: [{ n: "1", label: "L" }] },
    { kind: "banner", text: "Google sign-in LIVE" },
  ] });
  assert.equal(withClass(root, "hand").length, 2);
  assert.equal(withClass(root, "wrote-line").length, 1);
});

test("a generated hero stats row says so", () => {
  const root = render({ title: "T", handChangedAt: "2026-07-08", sections: [{ kind: "stats", generatedAt: recent, items: [{ n: "200", label: "Answers" }] }] });
  assert.equal(withClass(root, "gen").length, 1);
  assert.equal(withClass(root, "hand").length, 0);
});

test("asOf wins over the by-hand mark, and a board with no hand date marks nothing by hand", () => {
  const withAsOf = render({ title: "T", handChangedAt: "2026-07-08", sections: [{ kind: "cards", title: "Notes", asOf: "2026-09-01", items: [{ q: "x" }] }] });
  assert.equal(withClass(withAsOf, "hand").length, 0);
  assert.equal(withClass(withAsOf, "as-of").length, 1);
  const noDate = render({ title: "T", sections: [{ kind: "cards", title: "Notes", items: [{ q: "x" }] }] });
  assert.equal(withClass(noDate, "hand").length, 0);
});

console.log(`${passed} passed`);
