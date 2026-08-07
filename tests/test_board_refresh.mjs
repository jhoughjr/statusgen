// The board page must keep up with the board.
//
// board.json used to be fetched exactly once, at boot. A tab left open — which
// is what a status board IS — was frozen at whatever it loaded, so every run
// that landed afterwards was invisible until someone pressed reload. Worse, the
// "CI — running now" console polls on its own, so half the page was live and
// half was dead: you would watch a run appear there, finish, and never arrive in
// the history two inches below it. That is indistinguishable from a build
// vanishing, and it was reported as exactly that, for days.
//
// Run:  node tests/test_board_refresh.mjs      (from the statusgen root)

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

// ---- minimal stubs -------------------------------------------------------

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
  get firstChild() { return this.children[0] ?? null; }
  removeChild(k) { this.children = this.children.filter((c) => c !== k); }
}

const BOARD = JSON.stringify({ title: "T", sections: [] });

function load({ responses }) {
  const root = new Node_("div");
  const intervals = [];
  const visibilityHandlers = [];
  let calls = 0;

  const doc = {
    createElement: (t) => new Node_(t),
    createTextNode: (v) => ({ nodeValue: v, textContent: v }),
    getElementById: () => root,
    addEventListener: (evt, fn) => { if (evt === "visibilitychange") visibilityHandlers.push(fn); },
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
    fetch: () => {
      const r = responses[Math.min(calls, responses.length - 1)];
      calls++;
      if (r instanceof Error) return Promise.reject(r);
      return Promise.resolve({
        ok: r.ok !== false,
        status: r.status ?? 200,
        headers: { get: () => r.lastModified ?? null },
        text: () => Promise.resolve(r.body ?? BOARD),
        json: () => Promise.resolve(JSON.parse(r.body ?? BOARD)),
      });
    },
    setTimeout, clearTimeout, clearInterval,
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};

  const src = fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8");
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);

  return {
    api: sandbox.module.exports,
    root,
    doc,
    tick: () => intervals.forEach((fn) => fn()),
    becomeVisible: () => visibilityHandlers.forEach((fn) => fn()),
    calls: () => calls,
  };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

// ---- tests ---------------------------------------------------------------

test("init is exported as a seam so this behaviour is reachable at all", () => {
  const h = load({ responses: [{}] });
  assert.equal(typeof h.api.init, "function");
});

const run = async () => {
  {
    // A tab left open is the normal case for a status board, not the edge case.
    const h = load({ responses: [{ body: BOARD }] });
    await settle();  // board.js self-inits on load
    const before = h.calls();
    h.tick();
    await settle();
    assert.ok(h.calls() > before, "the interval must re-fetch the board");
    console.log("✓ an open tab re-fetches the board on a timer");
    passed++;
  }

  {
    // Redrawing a page people scroll and expand things on, every minute, for
    // no reason, would make it unusable.
    const h = load({ responses: [{ body: BOARD }] });
    await settle();  // board.js self-inits on load
    const kids = h.root.children.length;
    h.tick();
    await settle();
    assert.equal(h.root.children.length, kids, "unchanged board must not redraw");
    console.log("✓ an unchanged board is not redrawn");
    passed++;
  }

  {
    // Assert the outcome, not the number of fetches: what matters is that new
    // content reaches the screen.
    const changed = JSON.stringify({
      title: "T2", sections: [{ kind: "cards", title: "Fresh", items: [] }],
    });
    const h = load({ responses: [{ body: BOARD }, { body: changed }] });
    await settle();  // board.js self-inits on load
    const before = h.root.children.length;
    h.tick();
    await settle();
    assert.notEqual(h.root.children.length, before, "a changed board must redraw");
    console.log("✓ a changed board is re-rendered");
    passed++;
  }

  {
    // A background tab is the worst offender — catch it up when looked at
    // rather than up to a minute later.
    const h = load({ responses: [{ body: BOARD }] });
    await settle();  // board.js self-inits on load
    const before = h.calls();
    h.becomeVisible();
    await settle();
    assert.ok(h.calls() > before, "becoming visible must re-check");
    console.log("✓ returning to the tab re-checks immediately");
    passed++;
  }

  {
    // Stale data beats replacing a working page with an error text because the
    // network blipped for one poll.
    const h = load({ responses: [{ body: BOARD }, new Error("offline")] });
    await settle();  // board.js self-inits on load
    const kids = h.root.children.length;
    h.tick();
    await settle();
    assert.equal(h.root.children.length, kids, "a failed refresh must leave the board up");
    console.log("✓ a failed refresh leaves the rendered board alone");
    passed++;
  }

  console.log(`\n${passed} passing`);
};

run();
