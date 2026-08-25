// Ages must be computed at RENDER time, never baked into board.json.
//
// The collector used to write "eca47d7 · 24m ago" as a tile's literal value.
// That is correct for as long as it takes to publish the file and wrong forever
// after. A board left open on a wall kept asserting a build had gone green 24
// minutes earlier — hours later — while the run history directly below it
// showed nothing since 10:46. The board contradicting ITSELF is worse than the
// board being stale: one of the two numbers has to be a lie and the reader
// cannot tell which. Reported as "the board is lying more as time goes on".
//
// Run:  node tests/test_live_ages.mjs      (from the statusgen root)

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
    readyState: "loading",   // keeps init() from self-running
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
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8"), sandbox);
  return sandbox.module.exports;
}

const api = load();
const NOW = Date.parse("2026-08-07T18:09:00Z");
const at = (iso) => api.fmtAge(iso, NOW);

test("fmtAge is exported at all", () => {
  assert.equal(typeof api.fmtAge, "function");
});

test("the reported case: a 10:46 CDT run reads as hours, not minutes", () => {
  // 2026-08-07T15:46:57Z is 10:46 CDT; the board claimed "24m ago" at 13:09.
  assert.equal(at("2026-08-07T15:46:57Z"), "2h ago");
});

test("buckets", () => {
  assert.equal(at("2026-08-07T18:08:30Z"), "just now");
  assert.equal(at("2026-08-07T17:45:00Z"), "24m ago");
  assert.equal(at("2026-08-07T12:09:00Z"), "6h ago");
  assert.equal(at("2026-08-05T18:09:00Z"), "2d ago");
});

test("a future timestamp reads as 'just now', not a build from the future", () => {
  // Clock skew between the publishing box and the viewer is ordinary.
  assert.equal(at("2026-08-07T18:20:00Z"), "just now");
});

test("garbage and absence produce nothing rather than NaN", () => {
  assert.equal(at("not a date"), "");
  assert.equal(at(""), "");
  assert.equal(at(undefined), "");
});

test("the same timestamp ages as the clock moves — the whole point", () => {
  const ts = "2026-08-07T15:46:57Z";
  const later = api.fmtAge(ts, NOW + 3 * 3600 * 1000);
  assert.notEqual(api.fmtAge(ts, NOW), later);
  assert.equal(later, "5h ago");
});

test("a tile with `since` renders its age beside the value", () => {
  // Relative to the REAL clock, because that is the point: the tile computes
  // its age when it renders, not when board.json was written.
  const twentyFourMinAgo = new Date(Date.now() - 24 * 60 * 1000).toISOString();
  const tile = api.buildStatTile({ n: "eca47d7", label: "Last green", since: twentyFourMinAgo });
  assert.match(tile.textContent, /eca47d7/);
  assert.match(tile.textContent, /24m ago/);
});

test("a tile without `since` renders no age at all", () => {
  const tile = api.buildStatTile({ n: "7,324", label: "Tests green" });
  assert.doesNotMatch(tile.textContent, /ago/);
});

// The build tile, merged 2026-08-25. Its `meta` line carries the commit the
// verdict was measured at, so the age now dates the COMMIT rather than the ✓.
// Everything above still governs when the age is computed; these pin where it
// lands.

test("a tile with `meta` renders the headline, the label and the evidence", () => {
  const tile = api.buildStatTile({
    n: "\u2713", label: "CI build \u00b7 dev", meta: "132dab0", tone: "go",
  });
  assert.match(tile.textContent, /\u2713/);
  assert.match(tile.textContent, /CI build \u00b7 dev/);
  assert.match(tile.textContent, /132dab0/);
});

test("the age attaches to the commit, not to the verdict", () => {
  // The failure this prevents: "\u2713 \u00b7 4d ago" reads as a tick that is four days
  // old, which is a claim about the tile's freshness. The tick is current; the
  // COMMIT is four days old, and the line naming the commit is where the age
  // belongs.
  const fourDaysAgo = new Date(Date.now() - 4 * 24 * 3600 * 1000).toISOString();
  const tile = api.buildStatTile({
    n: "\u2713", label: "CI build \u00b7 dev", meta: "132dab0", since: fourDaysAgo,
  });
  const headline = tile.children[0].textContent;
  const evidence = tile.children[2].textContent;
  assert.doesNotMatch(headline, /ago/);
  assert.match(evidence, /132dab0 \u00b7 4d ago/);
});

test("a `meta` with no `since` renders the evidence and no age", () => {
  const tile = api.buildStatTile({
    n: "\u2717", label: "CI build \u00b7 dev", meta: "no green in the window",
  });
  assert.match(tile.textContent, /no green in the window/);
  assert.doesNotMatch(tile.textContent, /ago/);
});

test("a red tile says the commit is the last GREEN one", () => {
  // A bare SHA under a \u2717 reads as the commit that failed, which is the
  // opposite of what it is. The collector spells it out; this pins that the
  // renderer passes the words through rather than reformatting them away.
  const tile = api.buildStatTile({
    n: "\u2717", label: "CI build \u00b7 dev", meta: "last green 132dab0", tone: "you",
  });
  assert.match(tile.textContent, /last green 132dab0/);
});

console.log(`\n${passed} passing`);
