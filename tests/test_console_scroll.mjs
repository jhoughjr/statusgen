// The runs console keeps a short block's height and scrolls the record.
//
// The section used to show a sliding window of the last few runs per repo, so
// a day's builds could scroll out of it and read as never having happened. It
// now carries every run on record. Rendered at full height that would push
// every section below it off the page, so the block is capped at `scroll` rows
// and scrolls the rest.
//
// The height is computed from the row metrics rather than a fixed rem, so it
// still shows that many rows if the console's type ever changes. `1.75em` is
// the console line-height and `1.7rem` is its padding, both from board.css.
//
// Run:  node tests/test_console_scroll.mjs      (from the statusgen root)

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
  append(...kids) { this.children.push(...kids); }
  appendChild(kid) { this.children.push(kid); return kid; }
  addEventListener() {}
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return this._text ?? ""; }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

function load() {
  const root = new Node_("div");
  const sandbox = {
    document: {
      createElement: (t) => new Node_(t),
      createTextNode: (v) => ({ nodeValue: String(v), textContent: String(v) }),
      getElementById: () => root,
      addEventListener: () => {},
      querySelector: () => null,
      readyState: "complete",
      hidden: false,
    },
    Node: Node_,
    console: { warn() {}, error() {}, log() {} },
    module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/" },
    history: { replaceState() {} },
    fetch: () => Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, text: () => Promise.resolve("") }),
    setTimeout, clearTimeout, clearInterval,
    setInterval: () => 0,
    encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return sandbox.module.exports;
}

const { consoleScrollHeight } = load();

test("a row count becomes a height in the console's own units", () => {
  assert.equal(consoleScrollHeight(10), "calc(10 * 1.75em + 1.7rem)");
});

test("a console with no scroll set is left at its full height", () => {
  // The field is optional, and every console that had no cap keeps none.
  for (const absent of [undefined, null, 0, ""]) {
    assert.equal(consoleScrollHeight(absent), null, `for ${JSON.stringify(absent)}`);
  }
});

test("a nonsense row count caps nothing rather than collapsing the block", () => {
  // A height of 0 or NaN would render an invisible console. Showing an
  // uncapped block is the recoverable way to be wrong.
  for (const bad of ["abc", -4, NaN, Infinity, {}]) {
    assert.equal(consoleScrollHeight(bad), null, `for ${String(bad)}`);
  }
});

test("a numeric string works, since JSON boards are hand-edited too", () => {
  assert.equal(consoleScrollHeight("12"), "calc(12 * 1.75em + 1.7rem)");
});

test("the metrics match board.css, or the block shows the wrong row count", () => {
  const css = fs.readFileSync(path.join(ROOT, "renderer", "board.css"), "utf8");
  const rule = css.split("\n").find((l) => l.startsWith(".console {"));
  assert.ok(rule.includes("line-height: 1.75"), "line-height drifted from 1.75em");
  assert.ok(rule.includes("padding: 0.85rem 1rem"), "padding drifted from 0.85rem");
});

console.log(`\n${passed} passing`);
