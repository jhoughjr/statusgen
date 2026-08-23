// The settings that must outlive regeneration.
//
// Everything in board.json is derived data the pipeline rewrites wholesale. The
// clauffice `staleAfterMinutes` proved it: hand-set on 2026-08-20, gone by the
// next scheduled run, and the stale banner it armed was silently disarmed for
// three days. config.json is the sibling file no collector touches — the
// renderer reads it on the same 60s cycle and applies it over the board:
// settings (staleAfterMinutes), visibility (hide), and running order (order),
// all keyed by section title, same as tabs.
//
// Run:  node tests/test_board_config.mjs      (from the statusgen root)

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
  get textContent() {
    return (this._text ?? "") + this.children.map((c) => c.textContent ?? c.nodeValue ?? "").join("");
  }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

// A fetch stub keyed by URL suffix, because the config ride-along means one
// load is now two requests and a call-counting stub cannot tell them apart.
function load({ files = {} } = {}) {
  const root = new Node_("div");
  const intervals = [];
  const doc = {
    createElement: (t) => new Node_(t),
    createTextNode: (v) => ({ nodeValue: String(v), textContent: String(v) }),
    getElementById: () => root,
    addEventListener: () => {},
    querySelector: () => null,
    readyState: "complete",
    hidden: false,
  };
  const sandbox = {
    document: doc,
    Node: Node_,
    console: { warn() {}, error() {}, log() {} },
    module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/" },
    history: { replaceState() {} },
    fetch: (url) => {
      const name = String(url).split("/").pop();
      const body = files[name];
      if (body == null) return Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, text: () => Promise.resolve("") });
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => "Thu, 21 Aug 2026 00:00:00 GMT" },
        text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
      });
    },
    setTimeout, clearTimeout, clearInterval,
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return { api: sandbox.module.exports, root, files, tick: () => intervals.forEach((fn) => fn()) };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

const { applyConfig } = load().api;

const board = () => ({
  title: "T",
  staleAfterMinutes: 30,
  sections: [
    { kind: "stats", items: [{ n: "1", label: "hero" }] },
    { kind: "cards", title: "Alpha", items: [{ q: "a" }] },
    { kind: "cards", title: "Beta", items: [{ q: "b" }] },
    { kind: "cards", title: "Gamma", items: [{ q: "g" }] },
  ],
});

const titles = (data) => data.sections.map((s) => s.title ?? "(hero)");

test("no config means the board passes through untouched", () => {
  const b = board();
  assert.equal(applyConfig(b, null), b);
  assert.equal(applyConfig(b, undefined), b);
});

test("hide drops a section by title and cannot touch an untitled one", () => {
  const out = applyConfig(board(), { hide: ["Beta", "(hero)", "not-present"] });
  assert.deepEqual(titles(out), ["(hero)", "Alpha", "Gamma"]);
});

test("order rearranges only the sections it names, in the slots they occupy", () => {
  const out = applyConfig(board(), { order: ["Gamma", "Alpha"] });
  // The untitled hero row keeps slot 0. Beta is unlisted and keeps its slot too.
  assert.deepEqual(titles(out), ["(hero)", "Gamma", "Beta", "Alpha"]);
});

test("hide and order compose", () => {
  const out = applyConfig(board(), { hide: ["Beta"], order: ["Gamma", "Alpha"] });
  assert.deepEqual(titles(out), ["(hero)", "Gamma", "Alpha"]);
});

test("config staleAfterMinutes wins over the derived board's", () => {
  assert.equal(applyConfig(board(), { staleAfterMinutes: 60 }).staleAfterMinutes, 60);
  assert.equal(applyConfig(board(), {}).staleAfterMinutes, 30);
  assert.equal(applyConfig(board(), { staleAfterMinutes: "nope" }).staleAfterMinutes, 30);
});

test("a config full of garbage changes nothing and throws nothing", () => {
  const out = applyConfig(board(), { hide: "Beta", order: 7, wat: true });
  assert.deepEqual(titles(out), ["(hero)", "Alpha", "Beta", "Gamma"]);
});

test("the original board object is never mutated", () => {
  const b = board();
  applyConfig(b, { hide: ["Alpha"], order: ["Gamma", "Beta"] });
  assert.deepEqual(titles(b), ["(hero)", "Alpha", "Beta", "Gamma"]);
});

// ---- through init(): the config rides the board's own fetch cycle ----------

await (async () => {
  const h = load({ files: {
    "board.json": board(),
    "config.json": { hide: ["Beta"], staleAfterMinutes: 60 },
  } });
  h.api.init();
  await settle(); await settle();
  const text = h.root.textContent;
  assert.ok(text.includes("Alpha"), "Alpha renders");
  assert.ok(!text.includes("Beta"), "Beta is hidden by config");
  console.log("✓ init applies the sibling config.json");
  passed++;

  // An edit to config.json alone re-renders on the next cycle: the change
  // detector keys on both payloads, not just board.json.
  h.files["config.json"] = { hide: ["Alpha"] };
  h.tick();
  await settle(); await settle();
  const after = h.root.textContent;
  assert.ok(after.includes("Beta"), "Beta is back");
  assert.ok(!after.includes("Alpha"), "Alpha is hidden now");
  console.log("✓ a config-only change lands on the refresh cycle");
  passed++;
})();

await (async () => {
  const h = load({ files: { "board.json": board() } });
  h.api.init();
  await settle(); await settle();
  assert.ok(h.root.textContent.includes("Beta"), "no config file, full board");
  console.log("✓ a missing config.json costs nothing");
  passed++;
})();

await (async () => {
  const h = load({ files: { "board.json": board(), "config.json": "{not json" } });
  h.api.init();
  await settle(); await settle();
  assert.ok(h.root.textContent.includes("Beta"), "unparseable config is ignored");
  console.log("✓ an unparseable config.json is ignored, never fatal");
  passed++;
})();

console.log(`\n${passed} passing`);
