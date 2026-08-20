// The board asserts its own freshness.
//
// On 2026-08-20 the site served a nine-hour-old board for a whole morning.
// Every tile aged honestly at render time, so the freeze read as "nothing has
// built for days" rather than "delivery is broken" - the one failure the board
// could not describe was its own. staleBanner() closes that: past a board's
// `staleAfterMinutes`, the header carries a warning that the board itself is
// frozen. The tab refetches every 60s, so an open board crosses the threshold
// without a reload.
//
// Run:  node tests/test_stale_banner.mjs      (from the statusgen root)

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
    document: doc,
    Node: Node_,
    console: { warn() {}, error() {}, log() {} },
    module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/" },
    history: { replaceState() {} },
    fetch: () => Promise.reject(new Error("no network")),
    setTimeout, clearTimeout, setInterval, clearInterval,
    encodeURIComponent, decodeURIComponent,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return sandbox.module.exports;
}

const { staleBanner } = load();
const NOW = Date.parse("2026-08-20T14:00:00Z");
const gen = (iso) => iso;

test("past the threshold the board confesses its age", () => {
  const b = staleBanner({ staleAfterMinutes: 60 }, gen("2026-08-20T05:16:00Z"), NOW);
  assert.ok(b, "expected a banner");
  assert.match(b.textContent, /8h 44m old/);
  assert.match(b.textContent, /nothing has deployed/);
  assert.equal(b.getAttribute("role"), "alert");
});

test("inside the threshold there is no banner", () => {
  assert.equal(staleBanner({ staleAfterMinutes: 60 }, gen("2026-08-20T13:30:00Z"), NOW), null);
});

test("a board that does not opt in never warns", () => {
  assert.equal(staleBanner({}, gen("2026-08-01T00:00:00Z"), NOW), null);
  assert.equal(staleBanner({ staleAfterMinutes: 0 }, gen("2026-08-01T00:00:00Z"), NOW), null);
  assert.equal(staleBanner({ staleAfterMinutes: "nope" }, gen("2026-08-01T00:00:00Z"), NOW), null);
});

test("no generated stamp means no claim either way", () => {
  assert.equal(staleBanner({ staleAfterMinutes: 60 }, "", NOW), null);
  assert.equal(staleBanner({ staleAfterMinutes: 60 }, "garbage", NOW), null);
});

test("a sub-hour age reads in minutes", () => {
  const b = staleBanner({ staleAfterMinutes: 30 }, gen("2026-08-20T13:15:00Z"), NOW);
  assert.match(b.textContent, /45m old/);
});

console.log(`${passed} passed`);
