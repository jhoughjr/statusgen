// `collapsible` must work on EVERY section kind, not just tables.
//
// buildBlock implements the <details>/<summary> collapse, and for a while only
// renderTable returned through it. Every other renderer hand-built
// `section > [heading, content]` and silently dropped the flag — so setting
// collapsible on a `cards` section did nothing at all. That reads as the
// feature being broken rather than unimplemented, and it was reported that way:
// "the board doesn't have the collapse work".
//
// Run:  node tests/test_collapsible_sections.mjs      (from the statusgen root)

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

let passed = 0;
const test = (name, fn) => {
  try {
    fn();
    console.log(`✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`✗ ${name}\n  ${err.message}`);
    process.exitCode = 1;
  }
};

class Node_ {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  append(...kids) { this.children.push(...kids.filter(Boolean)); }
  appendChild(k) { this.children.push(k); return k; }
  addEventListener() {}
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() {
    return (this._text ?? "") + this.children.map((c) => c.textContent ?? c.nodeValue ?? "").join("");
  }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

function load() {
  const doc = {
    createElement: (t) => new Node_(t),
    createTextNode: (v) => ({ nodeValue: String(v), textContent: String(v) }),
    getElementById: () => new Node_("div"),
    addEventListener: () => {},
    querySelector: () => null,
    readyState: "loading",
    hidden: false,
  };
  const sandbox = {
    document: doc, Node: Node_,
    console: { warn() {}, error() {}, log() {} },
    module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/" },
    history: { replaceState() {} },
    fetch: () => Promise.reject(new Error("no network")),
    setTimeout, clearTimeout, setInterval, clearInterval,
    encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return sandbox.module.exports;
}

const api = load();

/** Find a <details> anywhere in a rendered tree. */
function findDetails(node) {
  if (!node || typeof node !== "object") return null;
  if (node.tagName === "DETAILS") return node;
  for (const kid of node.children ?? []) {
    const hit = findDetails(kid);
    if (hit) return hit;
  }
  return null;
}

function renderOne(section) {
  const root = new Node_("div");
  api.renderBoard({ title: "T", sections: [section] }, root, null);
  return root;
}

// The two the report was about, plus a representative sample of the rest.
const SECTIONS = {
  cards: { kind: "cards", title: "Still open", items: [{ q: "a thing", note: "n" }] },
  // Columns are plain strings and rows are ARRAYS — renderTable does
  // row.forEach, so an object row throws and the section is skipped.
  table: { kind: "table", title: "E2E suites", columns: ["Suite"], rows: [["a"]] },
  console: {
    kind: "console", title: "CI — recent runs",
    lines: [{ status: "success", text: "x", tone: "go" }],
  },
  stats: { kind: "stats", title: "Test results", items: [{ n: "1", label: "L" }] },
  compare: {
    kind: "compare", title: "Phoenix ⟷ MWServer",
    columns: [{ title: "Phoenix", items: [{ n: "1", label: "L" }] }],
  },
};

for (const [kind, section] of Object.entries(SECTIONS)) {
  test(`${kind}: collapsible renders a <details>`, () => {
    const tree = renderOne({ ...section, collapsible: true });
    assert.ok(findDetails(tree), `${kind} ignored collapsible`);
  });

  test(`${kind}: without the flag it stays a plain block`, () => {
    const tree = renderOne(section);
    assert.equal(findDetails(tree), null, `${kind} collapsed when it was not asked to`);
  });
}

test("collapsed: true starts shut", () => {
  const tree = renderOne({ ...SECTIONS.cards, collapsible: true, collapsed: true });
  assert.equal(findDetails(tree).getAttribute("open"), null);
});

test("collapsed absent starts open — a section nobody opens is a section nobody reads", () => {
  const tree = renderOne({ ...SECTIONS.cards, collapsible: true });
  assert.equal(findDetails(tree).getAttribute("open"), "");
});

test("the summary still states the headline while shut", () => {
  const tree = renderOne({
    ...SECTIONS.cards, collapsible: true, collapsed: true,
    count: "2 e2e failing", pill: { text: "neither is ours", tone: "err" },
  });
  const text = findDetails(tree).textContent;
  assert.match(text, /Still open/);
  assert.match(text, /2 e2e failing/);
});

console.log(`\n${passed} passing`);
