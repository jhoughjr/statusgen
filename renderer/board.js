// statusgen shared board renderer — served at /_assets/board.js
//
// Reads BOARD_SRC (default "board.json"), fetches it, and renders the
// board's header + sections into the container element on the page
// (id="board-root", falling back to <body>). All text is inserted via
// DOM APIs (textContent / createTextNode) so board data can never be
// interpreted as markup — see `el()` below.

(function () {
  "use strict";

  // ---- tiny DOM helpers -----------------------------------------------

  // el(tag, attrs, children) — children may be a string, a Node, or an
  // array of either. Strings are always inserted as text nodes (escaped).
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value == null) continue;
        node.setAttribute(key, value);
      }
    }
    if (children != null) {
      const list = Array.isArray(children) ? children : [children];
      for (const child of list) appendChild(node, child);
    }
    return node;
  }

  function appendChild(node, child) {
    if (child == null) return;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  function fmtNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString() : String(v ?? "");
  }

  // Formats the board.json's HTTP Last-Modified (i.e. when it was last
  // deployed) into a readable "generated at" stamp. Returns "" if absent.
  function fmtGenerated(lastModified) {
    if (!lastModified) return "";
    const t = Date.parse(lastModified);
    if (Number.isNaN(t)) return "";
    return new Date(t).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  // Maps a barchart series/legend `fill` token to the CSS variable that
  // colors it. Keep in sync with the .bar-fill.<fill> rules in board.css.
  const FILL_VAR = { code: "var(--accent)", gen: "var(--done)" };

  // Maps a pie slice `tone` to the CSS variable that colors it. Same
  // go/you/srv/wip/done palette as stats tiles and pills — keep in sync
  // with the --go/--you/--srv/--wip/--done custom properties in board.css.
  const TONE_VAR = {
    go: "var(--go)",
    you: "var(--you)",
    srv: "var(--srv)",
    wip: "var(--wip)",
    done: "var(--done)",
  };

  const SVG_NS = "http://www.w3.org/2000/svg";

  // svgEl(tag, attrs) — SVG counterpart to el() above. Uses
  // createElementNS/setAttribute only (never innerHTML), so pie data can't
  // be interpreted as markup either.
  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value == null) continue;
        node.setAttribute(key, value);
      }
    }
    return node;
  }

  // ---- section renderers ------------------------------------------------
  // Each takes a section object and returns the DOM node to append.

  function buildHeading(section) {
    const h2 = el("h2");
    if (section.icon) h2.append(el("span", { class: "sec-icon", "aria-hidden": "true" }, section.icon));
    h2.append(document.createTextNode(section.title || ""));
    if (section.count) h2.append(el("span", { class: "count" }, section.count));
    if (section.desc) h2.append(el("span", { class: "desc" }, ` — ${section.desc}`));
    return h2;
  }

  function renderPill(pill) {
    const text = pill && (pill.pill ?? pill.text) || "";
    const tone = pill && pill.tone ? ` ${pill.tone}` : "";
    return el("span", { class: `pill${tone}` }, text);
  }

  // stats — the tile row. Sits directly under the header stamp, no
  // heading or card wrapper.
  function renderStats(section) {
    const wrap = el("div", { class: "stats" });
    for (const item of section.items || []) {
      const tone = item.tone ? ` ${item.tone}` : "";
      const stat = el("div", { class: `stat${tone}` });
      stat.append(el("div", { class: "n" }, item.n ?? ""));
      stat.append(el("div", { class: "l" }, item.label ?? ""));
      wrap.append(stat);
    }
    // A titled stats section renders as a normal labeled block (e.g. a "Server"
    // row that mirrors the hero tiles, for side-by-side comparison); the
    // untitled hero row stays wrapper-free directly under the stamp.
    if (section.title || section.icon) {
      return el("section", { class: "block" }, [buildHeading(section), wrap]);
    }
    return wrap;
  }

  // banner — a full-width note.
  function renderBanner(section) {
    const tone = section.tone || "none";
    const banner = el("div", { class: `banner ${tone}` }, section.text || "");
    return el("section", { class: "block" }, [banner]);
  }

  // barchart — horizontal magnitude bars. Bar widths are value / max(values).
  function renderBarchart(section) {
    const card = el("div", { class: "chartcard" });

    if (Array.isArray(section.legend) && section.legend.length) {
      const legend = el("div", { class: "legend" });
      for (const item of section.legend) {
        const swatch = el("i");
        swatch.style.background = FILL_VAR[item.fill] || "var(--ink-faint)";
        legend.append(el("span", null, [swatch, ` ${item.label ?? ""}`]));
      }
      card.append(legend);
    }

    const series = Array.isArray(section.series) ? section.series : [];
    const max = Math.max(1, ...series.map((s) => Number(s.value) || 0));
    const bars = el("div", { class: "bars" });
    for (const s of series) {
      const value = Number(s.value) || 0;
      const pct = (value / max) * 100;
      const row = el("div", { class: "bar-row", title: `${s.label}: ${fmtNum(s.value)}` });
      row.append(el("div", { class: "bar-label" }, s.label ?? ""));
      const fill = el("div", { class: `bar-fill ${s.fill || ""}`.trim() });
      fill.style.width = `${pct.toFixed(2)}%`;
      row.append(el("div", { class: "bar-track" }, fill));
      row.append(el("div", { class: "bar-val" }, fmtNum(s.value)));
      bars.append(row);
    }
    card.append(bars);

    if (section.note) card.append(el("p", { class: "chart-note" }, section.note));

    return el("section", { class: "block" }, [buildHeading(section), card]);
  }

  // pie — a donut chart. Each slice is a stroke-dasharray segment of one
  // circle (not <path> arcs), which makes a single slice a full ring for
  // free and keeps the math simple. Colored by tone via TONE_VAR, with a
  // label/value/percentage legend alongside.
  function renderPie(section) {
    const card = el("div", { class: "chartcard" });
    const slices = Array.isArray(section.slices) ? section.slices : [];
    const total = slices.reduce((sum, s) => sum + Math.max(0, Number(s.value) || 0), 0);

    if (!slices.length || total <= 0) {
      card.append(el("div", { class: "empty" }, "No data."));
      if (section.note) card.append(el("p", { class: "chart-note" }, section.note));
      return el("section", { class: "block" }, [buildHeading(section), card]);
    }

    const size = 160;
    const r = 60;
    const thickness = 26;
    const cx = size / 2;
    const cy = size / 2;
    const circumference = 2 * Math.PI * r;

    const svg = svgEl("svg", {
      viewBox: `0 0 ${size} ${size}`,
      class: "pie-svg",
      role: "img",
      "aria-label": section.title ? `${section.title} donut chart` : "donut chart",
    });
    // Rotate so the first slice starts at 12 o'clock instead of 3 o'clock.
    const group = svgEl("g", { transform: `rotate(-90 ${cx} ${cy})` });

    let offset = 0;
    for (const s of slices) {
      const value = Math.max(0, Number(s.value) || 0);
      const len = (value / total) * circumference;
      group.append(
        svgEl("circle", {
          cx,
          cy,
          r,
          fill: "none",
          stroke: TONE_VAR[s.tone] || "var(--ink-faint)",
          "stroke-width": thickness,
          "stroke-dasharray": `${len.toFixed(3)} ${(circumference - len).toFixed(3)}`,
          "stroke-dashoffset": `${(-offset).toFixed(3)}`,
        })
      );
      offset += len;
    }
    svg.append(group);

    const legend = el("ul", { class: "pie-legend" });
    for (const s of slices) {
      const value = Math.max(0, Number(s.value) || 0);
      const pct = (value / total) * 100;
      const swatch = el("i");
      swatch.style.background = TONE_VAR[s.tone] || "var(--ink-faint)";
      legend.append(
        el("li", null, [
          swatch,
          el("span", { class: "pie-legend-label" }, s.label ?? ""),
          el("span", { class: "pie-legend-val" }, `${fmtNum(s.value)} (${pct.toFixed(1)}%)`),
        ])
      );
    }

    const wrap = el("div", { class: "pie" }, [svg, legend]);
    card.append(wrap);
    if (section.note) card.append(el("p", { class: "chart-note" }, section.note));

    return el("section", { class: "block" }, [buildHeading(section), card]);
  }

  // table — columns + rows; a cell is a string or { pill, tone }.
  function renderTable(section) {
    const columns = Array.isArray(section.columns) ? section.columns : [];
    const rows = Array.isArray(section.rows) ? section.rows : [];

    const headRow = el(
      "tr",
      null,
      columns.map((c) => el("th", null, c))
    );
    const thead = el("thead", null, headRow);

    const tbody = el("tbody");
    for (const row of rows) {
      const tr = el("tr");
      row.forEach((cell, i) => {
        if (cell && typeof cell === "object" && "pill" in cell) {
          tr.append(el("td", null, renderPill(cell)));
        } else {
          tr.append(el("td", i === 0 ? null : { class: "scope" }, cell ?? ""));
        }
      });
      tbody.append(tr);
    }

    const table = el("table", null, [thead, tbody]);
    const cardWrap = el("div", { class: "card tablewrap" }, table);
    return el("section", { class: "block" }, [buildHeading(section), cardWrap]);
  }

  // cards — id / question / note / pill rows.
  function renderCards(section) {
    const items = Array.isArray(section.items) ? section.items : [];
    const card = el("div", { class: "card" });

    if (!items.length) {
      card.append(el("div", { class: "empty" }, "Nothing tracked yet."));
    } else {
      for (const item of items) {
        // Optional item.href renders the title as a link.
        const qContent = item.href
          ? el("a", { class: "qlink", href: item.href, target: "_blank", rel: "noopener" }, item.q ?? "")
          : item.q ?? "";
        const body = el("div", { class: "body" }, el("div", { class: "q" }, qContent));
        if (item.note) body.append(el("div", { class: "note" }, item.note));
        if (item.meta) body.append(el("div", { class: "meta" }, item.meta));

        const pillSlot = el("div", null, item.pill ? renderPill(item.pill) : null);
        const row = el("div", { class: "row" }, [el("div", { class: "id" }, item.id ?? ""), body, pillSlot]);
        card.append(row);
      }
    }

    return el("section", { class: "block" }, [buildHeading(section), card]);
  }

  // split — two columns of checklist items. column.style is "check" | "pend".
  function renderSplit(section) {
    const columns = Array.isArray(section.columns) ? section.columns : [];
    const split = el("div", { class: "split" });

    for (const colData of columns) {
      const style = colData.style ? ` ${colData.style}` : "";
      const col = el("div", { class: `col${style}` });
      if (colData.h3) col.append(el("h3", null, colData.h3));

      const ul = el("ul");
      for (const item of colData.items || []) {
        const li = el("li", null, item.text ?? "");
        if (item.who) {
          li.append(el("br"));
          li.append(el("span", { class: "who" }, item.who));
        }
        ul.append(li);
      }
      col.append(ul);
      split.append(col);
    }

    return el("section", { class: "block" }, [buildHeading(section), split]);
  }

  // compare — two (or more) columns, each a labeled group of stat tiles, for
  // side-by-side comparison (e.g. Phoenix client vs MWServer server). Reuses the
  // .stats/.stat tile styling so each side matches the hero tiles.
  function renderCompare(section) {
    const cols = Array.isArray(section.columns) ? section.columns : [];
    const wrap = el("div", { class: "compare" });
    for (const c of cols) {
      const col = el("div", { class: "compare-col" });
      const head = el("div", { class: "compare-head" });
      if (c.icon) head.append(el("span", { class: "sec-icon", "aria-hidden": "true" }, c.icon));
      head.append(document.createTextNode(c.title || ""));
      col.append(head);
      const tiles = el("div", { class: "stats" });
      for (const item of c.items || []) {
        const tone = item.tone ? ` ${item.tone}` : "";
        const stat = el("div", { class: `stat${tone}` });
        stat.append(el("div", { class: "n" }, item.n ?? ""));
        stat.append(el("div", { class: "l" }, item.label ?? ""));
        tiles.append(stat);
      }
      col.append(tiles);
      wrap.append(col);
    }
    return el("section", { class: "block" }, [buildHeading(section), wrap]);
  }

  // console — a terminal-styled log block (dark, monospace). Each line is a
  // status dot (tone-colored) + a status word + text + right-aligned meta.
  // Used for CI runs. Reads section.lines: {text, meta, status, tone}.
  function renderConsole(section) {
    const term = el("div", { class: "console" });
    for (const ln of section.lines || section.items || []) {
      const tone = ln.tone ? ` ${ln.tone}` : "";
      const line = el("div", { class: "console-line" });
      line.append(el("span", { class: `console-dot${tone}`, "aria-hidden": "true" }));
      line.append(el("span", { class: "console-status" }, ln.status ?? (ln.pill && ln.pill.text) ?? ""));
      line.append(el("span", { class: "console-text" }, ln.text ?? ln.q ?? ""));
      if (ln.meta || ln.note) line.append(el("span", { class: "console-meta" }, ln.meta ?? ln.note));
      term.append(line);
    }
    return el("section", { class: "block" }, [buildHeading(section), term]);
  }

  const RENDERERS = {
    stats: renderStats,
    compare: renderCompare,
    console: renderConsole,
    banner: renderBanner,
    barchart: renderBarchart,
    pie: renderPie,
    table: renderTable,
    cards: renderCards,
    split: renderSplit,
  };

  // ---- header + top-level render -----------------------------------------

  function renderHeader(data, generatedAt) {
    const header = el("header", { class: "top" });
    if (data.eyebrow) header.append(el("p", { class: "eyebrow" }, data.eyebrow));
    header.append(el("h1", null, data.title || "Status"));
    if (data.stamp) header.append(el("div", { class: "stamp mono" }, data.stamp));
    const gen = fmtGenerated(generatedAt);
    if (gen) header.append(el("div", { class: "stamp mono generated" }, `Generated ${gen}`));
    return header;
  }

  function renderBoard(data, container, generatedAt) {
    if (data.title) document.title = data.title;

    container.innerHTML = "";
    container.append(renderHeader(data, generatedAt));

    for (const section of Array.isArray(data.sections) ? data.sections : []) {
      const renderFn = RENDERERS[section.kind];
      if (!renderFn) {
        console.warn(`statusgen: unknown section kind "${section.kind}"`);
        continue;
      }
      try {
        container.append(renderFn(section));
      } catch (err) {
        console.error(`statusgen: failed to render section kind "${section.kind}"`, err);
      }
    }
  }

  function showError(container, message) {
    container.innerHTML = "";
    container.append(el("p", { class: "board-error" }, message));
  }

  function init() {
    const container = document.getElementById("board-root") || document.body;
    const src = window.BOARD_SRC || "board.json";

    fetch(src, { cache: "no-cache" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const generatedAt = res.headers.get("Last-Modified");
        return res.json().then((data) => ({ data, generatedAt }));
      })
      .then(({ data, generatedAt }) => renderBoard(data, container, generatedAt))
      .catch((err) => showError(container, `Couldn't load ${src}: ${err.message}`));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
