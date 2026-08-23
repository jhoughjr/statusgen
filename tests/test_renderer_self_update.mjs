// The page must not outlive its own code.
//
// A wall tab refetches board.json every minute but never board.js, so a
// renderer deploy reached every fresh visit and not one open tab. On
// 2026-08-23 four merged renderer changes drew "weird i see nothing changed"
// from the standing tab. The renderer now watches its own script URL on the
// refresh cycle and reloads the page when the served code differs from the
// running code's baseline.
//
// Run:  node tests/test_renderer_self_update.mjs      (from the statusgen root)

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
  removeAttribute(k) { delete this.attributes[k]; }
  append(...kids) { this.children.push(...kids); }
  appendChild(kid) { this.children.push(kid); return kid; }
  addEventListener() {}
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return this._text ?? ""; }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

const SCRIPT_URL = "https://x/_assets/board.js?v=abc";

// `files` is keyed by full URL for the script and by basename for the rest,
// and is mutable so a test can deploy a "new renderer" between ticks.
function load({ files, currentScript = { src: SCRIPT_URL } }) {
  const intervals = [];
  let reloads = 0;
  const doc = {
    createElement: (t) => new Node_(t),
    createTextNode: (v) => ({ nodeValue: String(v), textContent: String(v) }),
    getElementById: () => new Node_("div"),
    addEventListener: () => {},
    querySelector: () => null,
    // "loading" keeps the file's own DOMContentLoaded init from doubling the
    // explicit init() below — the listener stub never fires it.
    readyState: "loading",
    hidden: false,
    currentScript,
  };
  const sandbox = {
    document: doc,
    Node: Node_,
    console: { warn() {}, error() {}, log() {} },
    module: { exports: {} },
    location: { hash: "", pathname: "/b/", href: "https://x/b/", reload: () => { reloads++; } },
    history: { replaceState() {} },
    fetch: (url) => {
      const body = files[url] ?? files[String(url).split("/").pop()];
      if (body == null) return Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, text: () => Promise.resolve("") });
      return Promise.resolve({
        ok: true, status: 200,
        headers: { get: () => null },
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
  return { api: sandbox.module.exports, files, tick: () => intervals.forEach((fn) => fn()), reloads: () => reloads };
}

const settle = () => new Promise((r) => setTimeout(r, 0));
const BOARD = { title: "T", sections: [] };

await (async () => {
  const h = load({ files: { "board.json": BOARD, [SCRIPT_URL]: "renderer-v1" } });
  h.api.init();
  await settle(); await settle();
  h.tick();
  await settle(); await settle();
  assert.equal(h.reloads(), 0, "an unchanged renderer never reloads");
  console.log("✓ an unchanged renderer never reloads the page");
  passed++;

  // A deploy lands between ticks: the served script changes, the tab follows.
  h.files[SCRIPT_URL] = "renderer-v2";
  h.tick();
  await settle(); await settle();
  assert.equal(h.reloads(), 1, "the new code triggers exactly one reload");
  console.log("✓ a renderer deploy reloads the open tab on the next cycle");
  passed++;
})();

await (async () => {
  // The baseline seeds from the FIRST successful fetch — a boot mid-deploy
  // must not loop.
  const h = load({ files: { "board.json": BOARD, [SCRIPT_URL]: "renderer-v2" } });
  h.api.init();
  await settle(); await settle();
  h.tick(); h.tick();
  await settle(); await settle();
  assert.equal(h.reloads(), 0);
  console.log("✓ the first fetch seeds the baseline, so boot cannot loop");
  passed++;
})();

await (async () => {
  // The script URL failing (offline, gated) or absent must cost nothing.
  const h = load({ files: { "board.json": BOARD } });
  h.api.init();
  await settle(); await settle();
  h.tick();
  await settle(); await settle();
  assert.equal(h.reloads(), 0);
  console.log("✓ an unreachable script URL never reloads");
  passed++;

  const bare = load({ files: { "board.json": BOARD }, currentScript: null });
  bare.api.init();
  await settle(); await settle();
  bare.tick();
  await settle(); await settle();
  assert.equal(bare.reloads(), 0);
  console.log("✓ no currentScript at eval means the watch stays off");
  passed++;
})();

console.log(`\n${passed} passing`);
