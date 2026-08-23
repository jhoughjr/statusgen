// The viewer's own board.
//
// config.json is the canonical say over what a board shows. The ⚙ panel is the
// per-viewer layer on top: checkboxes over every titled section, stored in
// localStorage per board path, per browser. A viewer can hide more than the
// config hides and can reveal what it hides — and none of it is canonical:
// clearing site data, a private window, or another device come up on the
// board's declared default. Storage is treated as absent-by-default, because
// in some contexts the accessor itself throws.
//
// Run:  node tests/test_section_panel.mjs      (from the statusgen root)

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
    this._listeners = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  removeAttribute(k) { delete this.attributes[k]; }
  append(...kids) { this.children.push(...kids); }
  appendChild(kid) { this.children.push(kid); return kid; }
  addEventListener(type, fn) { (this._listeners[type] ??= []).push(fn); }
  fire(type) { (this._listeners[type] ?? []).forEach((fn) => fn()); }
  get checked() { return this._checked ?? ("checked" in this.attributes); }
  set checked(v) { this._checked = !!v; }
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() {
    return (this._text ?? "") + this.children.map((c) => c.textContent ?? c.nodeValue ?? "").join("");
  }
  set innerHTML(_v) { this.children = []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    size: () => m.size,
  };
}

function load({ files = {}, storage = fakeStorage() } = {}) {
  const root = new Node_("div");
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
        ok: true, status: 200,
        headers: { get: () => "Thu, 21 Aug 2026 00:00:00 GMT" },
        text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
      });
    },
    setTimeout, clearTimeout, clearInterval,
    setInterval: () => 0,
    encodeURIComponent, decodeURIComponent,
  };
  if (storage) sandbox.localStorage = storage;
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return { api: sandbox.module.exports, root, storage };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

const board = () => ({
  title: "T",
  sections: [
    { kind: "stats", items: [{ n: "1", label: "hero" }] },
    { kind: "cards", title: "Alpha", items: [{ q: "alpha-card" }] },
    { kind: "cards", title: "Beta", items: [{ q: "beta-card" }] },
  ],
});

// DOM helpers against the stub tree: header nav → gear button + panel.
const nav = (root) => {
  for (const c of root.children) {
    if (c.tagName !== "HEADER") continue;
    for (const k of c.children) if ((k.getAttribute("class") || "").includes("board-links")) return k;
  }
  return null;
};
const gearOf = (root) => nav(root).children.find((c) => (c.getAttribute("class") || "").includes("gear"));
const panelOf = (root) => nav(root).children.find((c) => (c.getAttribute("class") || "").includes("section-panel"));
const rowsOf = (root) => panelOf(root).children.filter((c) => (c.getAttribute("class") || "").includes("section-panel-row"));
const boxOf = (root, title) => rowsOf(root).find((r) => r.textContent.includes(title)).children[0];
const resetOf = (root) => panelOf(root).children.find((c) => (c.getAttribute("class") || "").includes("reset"));

// ---- the pure layer --------------------------------------------------------

const { effectiveHidden, togglePref } = load().api;

test("config hides by default and a viewer override flips either way", () => {
  const config = { hide: ["Beta"] };
  assert.deepEqual([...effectiveHidden(config, null)], ["Beta"]);
  assert.deepEqual([...effectiveHidden(config, { overrides: { Alpha: "hide" } })].sort(), ["Alpha", "Beta"]);
  assert.deepEqual([...effectiveHidden(config, { overrides: { Beta: "show" } })], []);
});

test("togglePref stores only disagreement with the board's default", () => {
  const config = { hide: ["Beta"] };
  const shape = (v) => JSON.stringify(v);
  // hiding a default-shown section is a disagreement
  assert.equal(shape(togglePref(null, "Alpha", false, config)), shape({ overrides: { Alpha: "hide" } }));
  // showing it again is the default, so the override evaporates
  assert.equal(shape(togglePref({ overrides: { Alpha: "hide" } }, "Alpha", true, config)), shape({ overrides: {} }));
  // revealing a config-hidden section is a disagreement the other way
  assert.equal(shape(togglePref(null, "Beta", true, config)), shape({ overrides: { Beta: "show" } }));
  // re-hiding it agrees with the config again
  assert.equal(shape(togglePref({ overrides: { Beta: "show" } }, "Beta", false, config)), shape({ overrides: {} }));
});

// ---- through init() --------------------------------------------------------

await (async () => {
  const h = load({ files: { "board.json": board(), "config.json": { hide: ["Beta"] } } });
  h.api.init();
  await settle(); await settle();

  assert.ok(gearOf(h.root), "the gear renders in the header nav");
  const rows = rowsOf(h.root);
  assert.equal(rows.length, 2, "every titled section is listed; the untitled hero is not");
  assert.equal(boxOf(h.root, "Alpha").checked, true, "a visible section starts checked");
  assert.equal(boxOf(h.root, "Beta").checked, false, "a config-hidden section starts unchecked");
  assert.equal(resetOf(h.root), undefined, "no reset row without overrides");
  console.log("✓ the panel lists titled sections with their effective visibility");
  passed++;

  // The viewer reveals what the config hides.
  const beta = boxOf(h.root, "Beta");
  beta.checked = true;
  beta.fire("change");
  await settle(); await settle();
  assert.ok(h.root.textContent.includes("beta-card"), "Beta renders for this viewer");
  assert.ok(h.storage.size() === 1, "the override is stored");
  assert.ok(resetOf(h.root), "the reset row appears once an override exists");
  console.log("✓ a viewer reveals a config-hidden section");
  passed++;

  // Reset returns to the board's declared default and clears storage.
  resetOf(h.root).fire("click");
  await settle(); await settle();
  assert.ok(!h.root.textContent.includes("beta-card"), "Beta hidden again");
  assert.equal(h.storage.size(), 0, "storage entry removed");
  console.log("✓ reset restores the declared default and empties storage");
  passed++;
})();

await (async () => {
  // Overrides persist across a fresh page load: same storage, new sandbox.
  const storage = fakeStorage();
  const a = load({ files: { "board.json": board() }, storage });
  a.api.init();
  await settle(); await settle();
  const alpha = boxOf(a.root, "Alpha");
  alpha.checked = false;
  alpha.fire("change");
  await settle(); await settle();

  const b = load({ files: { "board.json": board() }, storage });
  b.api.init();
  await settle(); await settle();
  assert.ok(!b.root.textContent.includes("alpha-card"), "the hidden section stays hidden on reload");
  console.log("✓ viewer prefs survive a reload via localStorage");
  passed++;
})();

await (async () => {
  // No localStorage at all — previews, blocked site data — must cost nothing.
  const h = load({ files: { "board.json": board() }, storage: null });
  h.api.init();
  await settle(); await settle();
  assert.ok(h.root.textContent.includes("alpha-card"), "the board renders without storage");
  assert.ok(gearOf(h.root), "the panel still offers itself");
  console.log("✓ a storageless context renders the declared default");
  passed++;
})();

console.log(`\n${passed} passing`);
