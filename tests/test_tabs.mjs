// Tests for renderer behaviour that has no Python side: tab grouping, the
// `asOf` staleness chip, and barchart fills/value labels.
//
// board.js ships as a plain <script> for a browser, so there's no module to
// import. This evaluates it in a vm against a stub DOM — enough of one to let
// the renderer build its tree — and reads the test seam it exports.
//
// Run:  node tests/test_tabs.mjs      (from the statusgen root)

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// ---- stub DOM ------------------------------------------------------------
// Only what board.js touches: element creation, attributes, text, children,
// classList, hidden, and event listeners.

class StubNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.attributes = {};
    this.children = [];
    this.listeners = {};
    this._hidden = false;
    this.style = {};   // charts set width/background inline
    this.classList = {
      _set: new Set(),
      add: (...c) => c.forEach((x) => this.classList._set.add(x)),
      remove: (...c) => c.forEach((x) => this.classList._set.delete(x)),
      toggle: (c, on) => (on ? this.classList._set.add(c) : this.classList._set.delete(c)),
      contains: (c) => this.classList._set.has(c),
    };
  }
  get hidden() { return this._hidden; }
  set hidden(v) { this._hidden = Boolean(v); }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === "class") String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList._set.add(c));
    if (k === "hidden") this._hidden = true;
  }
  getAttribute(k) { return this.attributes[k] ?? null; }
  appendChild(n) { this.children.push(n); return n; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(n)); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn()); }
  set innerHTML(_) { this.children = []; }
  querySelector() { return null; }
  // Depth-first text, for asserting on rendered labels.
  get text() {
    if (this.nodeValue != null) return this.nodeValue;
    return this.children.map((c) => c.text ?? "").join("");
  }
  // Every descendant carrying a class, for locating rendered bits.
  find(cls) {
    const out = [];
    const walk = (n) => {
      if (n.classList?.contains?.(cls)) out.push(n);
      (n.children || []).forEach(walk);
    };
    walk(this);
    return out;
  }
}

// Extends StubNode so a single `Node` in the sandbox satisfies the renderer's
// `child instanceof Node` check for both elements and text.
class StubText extends StubNode {
  constructor(v) { super("#text"); this.nodeValue = String(v); }
  get text() { return this.nodeValue; }
}

function makeSandbox({ hash = "" } = {}) {
  const doc = {
    readyState: "loading", // keeps init() from auto-running
    title: "",
    body: new StubNode("body"),
    createElement: (t) => new StubNode(t),
    // Same node type for SVG: the renderer only ever setAttribute/appends on
    // these, so one stub covers both namespaces.
    createElementNS: (_ns, t) => new StubNode(t),
    createTextNode: (v) => new StubText(v),
    getElementById: () => null,
    addEventListener: () => {},
    querySelector: () => null,
  };
  const sandbox = {
    document: doc,
    Node: StubNode,
    console,
    module: { exports: {} },
    location: { hash, pathname: "/clauffice/", href: "https://x/clauffice/" },
    history: { replaceState: () => {} },
    fetch: () => Promise.reject(new Error("no network in tests")),
    setTimeout, clearTimeout, setInterval, clearInterval,
    encodeURIComponent, decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  return sandbox;
}

function load(opts) {
  const sandbox = makeSandbox(opts);
  const src = fs.readFileSync(path.join(ROOT, "renderer", "board.js"), "utf8");
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  return { api: sandbox.module.exports, sandbox };
}

// ---- fixtures ------------------------------------------------------------

const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

function board(extra = {}) {
  return {
    title: "Clauffice",
    sections: [
      { kind: "banner", tone: "go", text: "headline" },        // untitled
      { kind: "stats", title: "Test results", items: [{ n: "1", label: "Passed" }] },
      { kind: "stats", title: "Backlog", items: [{ n: "2", label: "Open" }] },
      { kind: "stats", title: "Orphan", items: [{ n: "3", label: "Nobody" }] },
    ],
    ...extra,
  };
}

// Renders a one-section compare board and hands back the tree to assert on.
function compare(columns) {
  const { api } = load();
  const root = new StubNode("div");
  api.renderBoard({
    title: "b",
    sections: [{ kind: "compare", title: "Compare", columns }],
  }, root, null);
  return root;
}

// Renders a one-section barchart board and hands back the tree to assert on.
function bars(series, extra = {}) {
  const { api } = load();
  const root = new StubNode("div");
  api.renderBoard({
    title: "b",
    sections: [{ kind: "barchart", title: "Chart", series, ...extra }],
  }, root, null);
  return root;
}

const TABS = [
  { id: "now", label: "Now", sections: ["Test results"] },
  { id: "work", label: "Work", sections: ["Backlog"] },
  { id: "ghost", label: "Ghost", sections: ["Never seeded"] },
];

// ---- tests ---------------------------------------------------------------

const tests = {
  "no tabs key leaves every section pinned (old boards unchanged)"() {
    const { api } = load();
    const { pinned, groups } = api.partitionSections(board());
    assert.equal(groups.length, 0);
    assert.equal(pinned.length, 4);
  },

  "tabs claim their sections by title"() {
    const { api } = load();
    const { groups } = api.partitionSections(board({ tabs: TABS }));
    // Array.from: `groups` is built inside the vm realm, so its arrays fail a
    // strict deep-equal against test-realm ones on prototype identity alone.
    assert.deepEqual(Array.from(groups, (g) => g.tab.id), ["now", "work"]);
    assert.deepEqual(Array.from(groups[0].sections, (s) => s.title), ["Test results"]);
  },

  "a tab claiming nothing present is dropped, not rendered empty"() {
    const { api } = load();
    const { groups } = api.partitionSections(board({ tabs: TABS }));
    assert.ok(!groups.some((g) => g.tab.id === "ghost"));
  },

  "unclaimed and untitled sections stay pinned above the bar"() {
    const { api } = load();
    const { pinned } = api.partitionSections(board({ tabs: TABS }));
    // The banner (no title) and the section no tab named.
    assert.deepEqual(Array.from(pinned, (s) => s.title ?? "(untitled)"), ["(untitled)", "Orphan"]);
  },

  "a title claimed twice sticks with the first tab"() {
    const { api } = load();
    const tabs = [
      { id: "a", label: "A", sections: ["Backlog"] },
      { id: "b", label: "B", sections: ["Backlog"] },
    ];
    const { groups } = api.partitionSections(board({ tabs }));
    assert.deepEqual(Array.from(groups, (g) => g.tab.id), ["a"]);
  },

  "renders one tab button per group, first selected by default"() {
    const { api, sandbox } = load();
    const root = new StubNode("div");
    api.renderBoard(board({ tabs: TABS }), root, null);
    const buttons = root.find("tab");
    assert.equal(buttons.length, 2);
    assert.equal(buttons[0].getAttribute("aria-selected"), "true");
    assert.equal(buttons[1].getAttribute("aria-selected"), "false");
    const panels = root.find("tab-panel");
    assert.equal(panels[0].hidden, false);
    assert.equal(panels[1].hidden, true);
    assert.equal(sandbox.document.title, "Clauffice");
  },

  "the URL hash picks the open tab"() {
    const { api } = load({ hash: "#work" });
    const root = new StubNode("div");
    api.renderBoard(board({ tabs: TABS }), root, null);
    const buttons = root.find("tab");
    assert.equal(buttons[1].getAttribute("aria-selected"), "true");
    assert.equal(root.find("tab-panel")[1].hidden, false);
  },

  "an unknown hash falls back to the first tab"() {
    const { api } = load({ hash: "#nope" });
    const root = new StubNode("div");
    api.renderBoard(board({ tabs: TABS }), root, null);
    assert.equal(root.find("tab")[0].getAttribute("aria-selected"), "true");
  },

  "clicking a tab switches the visible panel"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard(board({ tabs: TABS }), root, null);
    root.find("tab")[1].click();
    assert.equal(root.find("tab-panel")[0].hidden, true);
    assert.equal(root.find("tab-panel")[1].hidden, false);
  },

  "a fresh asOf renders quietly, a stale one warns"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({
      title: "b",
      staleAfterDays: 7,
      sections: [
        { kind: "stats", title: "Fresh", asOf: daysAgo(2), items: [{ n: "1", label: "x" }] },
        { kind: "stats", title: "Old", asOf: daysAgo(30), items: [{ n: "1", label: "x" }] },
      ],
    }, root, null);
    const chips = root.find("as-of");
    assert.equal(chips.length, 2);
    assert.ok(chips[0].text.startsWith("as of "), chips[0].text);
    assert.ok(!chips[0].classList.contains("stale"));
    assert.ok(chips[1].text.includes("30d old"), chips[1].text);
    assert.ok(chips[1].classList.contains("stale"));
  },

  "staleAfterDays is honoured per board"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({
      title: "b",
      staleAfterDays: 60,
      sections: [{ kind: "stats", title: "Old", asOf: daysAgo(30), items: [{ n: "1", label: "x" }] }],
    }, root, null);
    assert.ok(!root.find("as-of")[0].classList.contains("stale"));
  },

  "a tile with href renders as a link, without one stays a div"() {
    const { api } = load();
    const plain = api.buildStatTile({ n: "1", label: "Passed" });
    const linked = api.buildStatTile({ n: "1", label: "Passed", href: "tests/" });
    assert.equal(plain.tagName, "DIV");
    assert.equal(plain.getAttribute("href"), null);
    assert.equal(linked.tagName, "A");
    assert.equal(linked.getAttribute("href"), "tests/");
    assert.ok(linked.classList.contains("linked"));
    assert.ok(!plain.classList.contains("linked"));
  },

  "a linked tile keeps its tone and stale flag"() {
    const { api } = load();
    const tile = api.buildStatTile({ n: "5", label: "E2E failed", tone: "err", stale: true, href: "tests/" });
    assert.equal(tile.tagName, "A");
    assert.ok(tile.classList.contains("err"));
    assert.ok(tile.classList.contains("stale"));
    assert.ok(tile.text.includes("⚠"));
  },

  "compare tiles honour href too"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({
      title: "b",
      sections: [{ kind: "compare", title: "C", columns: [
        { title: "L", items: [{ n: "1", label: "Tests green", href: "tests/" }] },
      ] }],
    }, root, null);
    const linked = root.find("linked");
    assert.equal(linked.length, 1);
    assert.equal(linked[0].getAttribute("href"), "tests/");
  },

  "a section with no asOf gets no chip"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard(board(), root, null);
    assert.equal(root.find("as-of").length, 0);
  },

  "a malformed asOf is ignored rather than rendering NaN"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({
      title: "b",
      sections: [{ kind: "stats", title: "Bad", asOf: "last tuesday", items: [{ n: "1", label: "x" }] }],
    }, root, null);
    assert.equal(root.find("as-of").length, 0);
  },

  // ---- barchart ----------------------------------------------------------

  "valueText labels the bar while value still sizes it"() {
    const root = bars([
      { label: "fc44010", value: 5.6, valueText: "5m36s", fill: "go" },
      { label: "4d6a3bb", value: 31.1, valueText: "31m06s", fill: "go" },
    ]);
    assert.deepEqual(root.find("bar-val").map((n) => n.text), ["5m36s", "31m06s"]);
    // Widths come from the numbers, so the longest build is the full bar and
    // the short one is proportional — not two equal bars with different text.
    const widths = root.find("bar-fill").map((n) => n.style.width);
    assert.equal(widths[1], "100.00%");
    assert.equal(widths[0], "18.01%");
  },

  "a bar with no valueText still prints its number"() {
    const root = bars([{ label: "App source", value: 40362, fill: "code" }]);
    assert.equal(root.find("bar-val")[0].text, "40,362");
  },

  "a tone may fill a bar, so outcome charts match the tiles"() {
    const root = bars([
      { label: "passed", value: 1, fill: "go" },
      { label: "failed", value: 1, fill: "you" },
    ]);
    assert.deepEqual(root.find("bar-fill").map((n) => n.style.background),
      ["var(--go)", "var(--you)"]);
  },

  "the structural fills keep their existing colors"() {
    const root = bars([
      { label: "hand", value: 1, fill: "code" },
      { label: "gen", value: 1, fill: "gen" },
    ]);
    assert.deepEqual(root.find("bar-fill").map((n) => n.style.background),
      ["var(--accent)", "var(--done)"]);
  },

  "an unknown fill falls back to a neutral rather than to nothing"() {
    const root = bars([{ label: "x", value: 1, fill: "chartreuse" }]);
    assert.equal(root.find("bar-fill")[0].style.background, "var(--ink-faint)");
  },

  // ---- compare column stack logos ----------------------------------------

  "a column's logo renders as an inline svg, labelled for screen readers"() {
    const root = compare([{ title: "MWServer — server", logo: "swift", items: [] }]);
    const logo = root.find("stack-logo");
    assert.equal(logo.length, 1);
    assert.equal(logo[0].tagName, "SVG");
    assert.equal(logo[0].getAttribute("aria-label"), "Swift");
    assert.equal(logo[0].getAttribute("role"), "img");
  },

  "each known mark draws its own brand colour"() {
    const fill = (name) => compare([{ title: "T", logo: name, items: [] }])
      .find("stack-logo")[0].children[0].getAttribute("fill");
    assert.equal(fill("swift"), "#F05138");
    assert.equal(fill("ts"), "#3178C6");
    assert.equal(fill("js"), "#F7DF1E");
  },

  "the lettered marks carry their letters"() {
    const letters = (name) => compare([{ title: "T", logo: name, items: [] }])
      .find("stack-logo")[0].text;
    assert.equal(letters("ts"), "TS");
    assert.equal(letters("js"), "JS");
  },

  // The board is served behind a gate that blocks outbound requests, so a mark
  // that needed fetching would be a broken box for every reader.
  "logos are self-contained — nothing is fetched"() {
    const root = compare([{ title: "T", logo: "swift", items: [] }]);
    const svg = root.find("stack-logo")[0];
    const walk = (n) => [n, ...(n.children || []).flatMap(walk)];
    for (const node of walk(svg)) {
      assert.equal(node.getAttribute("src"), null);
      assert.equal(node.getAttribute("href"), null);
    }
  },

  "an unknown logo name falls back to the emoji icon, not to a gap"() {
    const root = compare([{ title: "T", logo: "cobol", icon: "🖥️", items: [] }]);
    assert.equal(root.find("stack-logo").length, 0);
    assert.equal(root.find("sec-icon").length, 1);
  },

  "a logo replaces the emoji rather than sitting beside it"() {
    const root = compare([{ title: "T", logo: "swift", icon: "🖥️", items: [] }]);
    assert.equal(root.find("stack-logo").length, 1);
    assert.equal(root.find("sec-icon").length, 0);
  },

  "a section heading takes a stack mark"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({ title: "b", sections: [
      { kind: "stats", title: "Test results", logo: "ts",
        items: [{ n: "6605", label: "Passed" }] },
    ] }, root, null);
    const logo = root.find("stack-logo");
    assert.equal(logo.length, 1);
    assert.equal(logo[0].getAttribute("aria-label"), "TypeScript");
  },

  "a heading logo replaces the emoji, and an unknown one falls back to it"() {
    const heading = (extra) => {
      const { api } = load();
      const root = new StubNode("div");
      api.renderBoard({ title: "b", sections: [
        { kind: "stats", title: "T", icon: "\u2705", items: [], ...extra },
      ] }, root, null);
      return root;
    };
    assert.equal(heading({ logo: "swift" }).find("sec-icon").length, 0);
    assert.equal(heading({ logo: "fortran" }).find("sec-icon").length, 1);
    assert.equal(heading({}).find("sec-icon").length, 1);
  },

  // One merged, chronological feed only works if each row says whose run it is.
  "console rows carry their own stack mark"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({ title: "b", sections: [
      { kind: "console", title: "CI", lines: [
        { status: "success", text: "Phoenix \u00b7 dev", logo: "ts" },
        { status: "failure", text: "MWServer \u00b7 dev", logo: "swift" },
        { status: "success", text: "Unmarked \u00b7 dev" },
      ] },
    ] }, root, null);
    assert.deepEqual(root.find("stack-logo").map((n) => n.getAttribute("aria-label")),
      ["TypeScript", "Swift"]);
    assert.equal(root.find("console-line").length, 3);   // unmarked row still renders
  },

  "a tab can be marked with a stack logo"() {
    const { api } = load();
    const root = new StubNode("div");
    api.renderBoard({
      title: "b",
      tabs: [{ id: "client", label: "Client", logo: "ts", sections: ["T"] }],
      sections: [{ kind: "stats", title: "T", items: [{ n: "1", label: "x" }] }],
    }, root, null);
    const marks = root.find("stack-logo");
    assert.equal(marks.length, 1);
    assert.equal(marks[0].getAttribute("aria-label"), "TypeScript");
  },

  "a column with neither still renders its title and tiles"() {
    const root = compare([{ title: "Plain", items: [{ n: "1", label: "x" }] }]);
    assert.equal(root.find("stack-logo").length, 0);
    assert.match(root.find("compare-head")[0].text, /Plain/);
    assert.equal(root.find("stat").length > 0, true);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
  try {
    fn();
    console.log(`✓ ${name}`);
  } catch (err) {
    failed++;
    console.error(`✗ ${name}\n  ${err.message}`);
  }
}
console.log(failed ? `\n${failed} failing` : `\n${Object.keys(tests).length} passing`);
process.exit(failed ? 1 : 0);
