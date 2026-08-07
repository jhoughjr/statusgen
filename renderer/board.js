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

  // Formats a machine-readable timestamp (collectors emit UTC ISO-8601, e.g.
  // "2026-07-13T21:42:00Z") into the VIEWER's local time. Collect in UTC,
  // display in locale. Returns "" if absent/unparseable so callers fall back.
  function fmtTime(ts) {
    if (!ts) return "";
    const t = Date.parse(ts);
    if (Number.isNaN(t)) return "";
    return new Date(t).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  // Maps a barchart series/legend `fill` token to the CSS variable that
  // colors it. Keep in sync with the .bar-fill.<fill> rules in board.css.
  const FILL_VAR = { code: "var(--accent)", gen: "var(--done)" };

  // Maps a pie slice `tone` to the CSS variable that colors it. Same
  // go/you/srv/wip/done/err palette as stats tiles and pills — keep in sync
  // with the --go/--you/--srv/--wip/--done/--err custom properties in board.css.
  const TONE_VAR = {
    go: "var(--go)",
    you: "var(--you)",
    srv: "var(--srv)",
    wip: "var(--wip)",
    done: "var(--done)",
    err: "var(--err)",
  };

  // A barchart `fill` may name either vocabulary: the two structural fills
  // above, or any tone. Charts whose bars mean an *outcome* (a build that
  // passed or failed) want the same green/amber the tiles use, and inventing a
  // parallel set of fill names for them would leave two palettes to keep in
  // step. Unknown tokens fall back to a neutral rather than to no color.
  function fillVar(name) {
    return FILL_VAR[name] || TONE_VAR[name] || "var(--ink-faint)";
  }

  const SVG_NS = "http://www.w3.org/2000/svg";

  // Brand marks for the stack a compare column stands for. Drawn inline rather
  // than fetched: the site is served behind a gate with no external requests,
  // and an <img> to a CDN would be a broken box for exactly the readers who
  // matter. Each is a 24×24 tile — a rounded rect plus either a path or two
  // letters — because that is what these marks natively are.
  const LOGOS = {
    swift: {
      label: "Swift", bg: "#F05138", radius: 5.4, ink: "#fff",
      path: "M17.1 16.9c-2.4 1.4-5.7 1.5-9 .1-2.7-1.1-4.9-3-6.5-5.2 .8 .6 1.7 "
          + "1.2 2.6 1.6 3.9 1.9 7.9 1.8 10.6 0-3.9-3-7.2-6.9-9.7-10.1 .7 .7 "
          + "1.4 1.3 2.2 1.9 4.8 3.9 7.5 6.1 9.3 7.3 .6-1.6 .3-3.9-1-6.2 2.1 "
          + "2.4 3.3 5.5 2.8 8.1 0 .1 0 .2 0 .2 1 1.2 .7 2.5 .6 2.3-.5-1-1.4"
          + "-1.3-2.4-1.1z",
    },
    ts: { label: "TypeScript", bg: "#3178C6", radius: 2.2, ink: "#fff", text: "TS" },
    js: { label: "JavaScript", bg: "#F7DF1E", radius: 2.2, ink: "#000", text: "JS" },
  };

  // An unknown name returns null so the caller can fall back to the emoji icon
  // — a board naming a mark this renderer doesn't carry should look ordinary,
  // not broken.
  function buildLogo(name) {
    const spec = LOGOS[name];
    if (!spec) return null;
    const svg = svgEl("svg", {
      class: "stack-logo", viewBox: "0 0 24 24",
      role: "img", "aria-label": spec.label,
    });
    svg.append(svgEl("rect", { width: 24, height: 24, rx: spec.radius, fill: spec.bg }));
    if (spec.path) {
      svg.append(svgEl("path", { d: spec.path, fill: spec.ink }));
    }
    if (spec.text) {
      const text = svgEl("text", {
        x: 21.4, y: 20.4, "text-anchor": "end", fill: spec.ink,
        "font-family": "Helvetica,Arial,sans-serif",
        "font-weight": 700, "font-size": 11.4,
      });
      text.append(document.createTextNode(spec.text));
      svg.append(text);
    }
    return svg;
  }

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

  // How old a hand-written section's `asOf` date may get before its chip
  // turns into a warning. Board-level (`staleAfterDays`), set in renderBoard.
  let staleAfterDays = 7;

  // `asOf` (YYYY-MM-DD) marks a section whose content is hand-written: the
  // date a human last verified it. Collector-owned sections don't carry it —
  // they're refreshed every push and can't drift. Past staleAfterDays the
  // chip becomes a warning, because an editorial card that quietly stopped
  // being true otherwise reads exactly like one that's still current.
  function buildAsOf(asOf) {
    if (!asOf) return null;
    const t = Date.parse(`${asOf}T00:00:00Z`);
    if (Number.isNaN(t)) return null;
    const days = Math.floor((Date.now() - t) / 86400000);
    const stale = days > staleAfterDays;
    return el("span", {
      class: `as-of${stale ? " stale" : ""}`,
      title: `Hand-written — last verified ${asOf}`,
    }, stale ? `⚠ ${days}d old` : `as of ${asOf}`);
  }

  function buildHeading(section) {
    const h2 = el("h2");
    // A stack mark where the section belongs to one side of the board. Most of
    // this board's sections are about ONE repo, and until they said so it read
    // as if they were about all of it.
    const logo = section.logo ? buildLogo(section.logo) : null;
    if (logo) h2.append(logo);
    else if (section.icon) h2.append(el("span", { class: "sec-icon", "aria-hidden": "true" }, section.icon));
    // Optional section.href turns the title into a link (e.g. "see the full log").
    const title = section.title || "";
    h2.append(section.href
      ? el("a", { class: "sec-link", href: section.href }, title)
      : document.createTextNode(title));
    if (section.count) h2.append(el("span", { class: "count" }, section.count));
    // Optional section.pill — same {pill|text, tone} shape as a table/cards
    // cell — puts a single colored verdict on the heading itself, so a
    // section's overall state (e.g. "all green" vs "2 failing") reads even
    // when its rows are collapsed underneath (see buildBlock below).
    if (section.pill) h2.append(renderPill(section.pill));
    if (section.desc) h2.append(el("span", { class: "desc" }, ` — ${section.desc}`));
    const asOf = buildAsOf(section.asOf);
    if (asOf) h2.append(asOf);
    return h2;
  }

  function renderPill(pill) {
    const text = pill && (pill.pill ?? pill.text) || "";
    const tone = pill && pill.tone ? ` ${pill.tone}` : "";
    return el("span", { class: `pill${tone}` }, text);
  }

  // Wraps a section's heading + content in the standard block shell. A
  // section carrying `collapsible: true` renders as a native
  // <details>/<summary> instead of a plain heading — dependency-free
  // disclosure (the browser's own widget, restyled; no framework, no click
  // handler to wire up). The heading — title, count, an optional status
  // `pill`, desc — becomes the <summary> line, so a collapsed section states
  // exactly what an expanded one does; only the rows underneath are hidden,
  // never the signal. Starts open unless the section sets `collapsed: true`.
  function buildBlock(section, content) {
    const heading = buildHeading(section);
    if (!section.collapsible) {
      return el("section", { class: "block" }, [heading, content]);
    }
    const details = el(
      "details",
      { class: "collapsible", open: section.collapsed ? null : "" },
      [el("summary", null, heading), content]
    );
    return el("section", { class: "block" }, details);
  }

  // buildStatTile — one number tile, shared by `stats` rows and `compare`
  // columns so both get the same tone, stale flag, and link behaviour.
  //
  // `href` makes the whole tile a link: a number on a board is the start of a
  // question ("6,591 passed — which ones? since when?"), and the tile is where
  // the reader's eye already is. Rendered as an <a> rather than a click
  // handler so it keyboard-focuses and middle-clicks like any other link.
  function buildStatTile(item) {
    const tone = item.tone ? ` ${item.tone}` : "";
    // A stale tile shows numbers the collector couldn't refresh (a red CI
    // streak leaves them behind HEAD). Mark it so a frozen figure reads as
    // frozen, not current.
    const stale = item.stale ? " stale" : "";
    const link = item.href ? " linked" : "";
    const attrs = { class: `stat${tone}${stale}${link}` };
    if (item.stale) attrs.title = "Stale — CI hasn't reported a fresh green build; number is behind HEAD";
    if (item.href) attrs.href = item.href;
    const stat = el(item.href ? "a" : "div", attrs);
    const n = el("div", { class: "n" }, item.ts ? fmtTime(item.ts) : (item.n ?? ""));
    if (item.stale) n.append(el("span", { class: "stale-flag", "aria-label": "stale" }, " ⚠"));
    stat.append(n);
    stat.append(el("div", { class: "l" }, item.label ?? ""));
    return stat;
  }

  // stats — the tile row. Sits directly under the header stamp, no
  // heading or card wrapper.
  function renderStats(section) {
    const wrap = el("div", { class: "stats" });
    for (const item of section.items || []) wrap.append(buildStatTile(item));
    // A titled stats section renders as a normal labeled block (e.g. a "Server"
    // row that mirrors the hero tiles, for side-by-side comparison); the
    // untitled hero row stays wrapper-free directly under the stamp.
    if (section.title || section.icon) {
      return el("section", { class: "block" }, [buildHeading(section), wrap]);
    }
    return wrap;
  }

  // banner — a full-width note (the board's summary). Not plain text: when the
  // section carries a `links` map, #N references become PR links. The word
  // before the ref picks the repo ("MWServer #168" → links.MWServer); a bare
  // "#171" falls to links[""] — each value is a base URL the number appends to.
  function linkifyRefs(text, links) {
    const nodes = [];
    const re = /(^|[\s(·—])((?:[A-Za-z][\w.-]*)\s+)?#(\d+)\b/g;
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      const prefixWord = m[2] ? m[2].trim() : "";
      const base = prefixWord && links[prefixWord] != null ? links[prefixWord] : links[""];
      // A prefixed ref whose word names an unknown repo (e.g. "ruling-#8")
      // stays plain unless the bare default would claim it — only claim the
      // number itself, never the word, so "MWServer #168" keeps "MWServer "
      // as text and links just "#168".
      if (base == null) continue;
      const refStart = m.index + m[1].length + (m[2] ? m[2].length : 0);
      nodes.push(text.slice(last, refStart));
      nodes.push(el("a", { href: base + m[3], target: "_blank", rel: "noopener" }, `#${m[3]}`));
      last = refStart + 1 + m[3].length;
    }
    nodes.push(text.slice(last));
    return nodes;
  }

  function renderBanner(section) {
    const tone = section.tone || "none";
    const content = section.links && typeof section.links === "object"
      ? linkifyRefs(section.text || "", section.links)
      : section.text || "";
    const banner = el("div", { class: `banner ${tone}` }, content);
    return el("section", { class: "block" }, [banner]);
  }

  // barchart — horizontal magnitude bars. Bar widths are value / max(values).
  function renderBarchart(section) {
    const card = el("div", { class: "chartcard" });

    if (Array.isArray(section.legend) && section.legend.length) {
      const legend = el("div", { class: "legend" });
      for (const item of section.legend) {
        const swatch = el("i");
        swatch.style.background = fillVar(item.fill);
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
      // `valueText` labels the bar without changing it: the bar's LENGTH still
      // comes from the numeric `value`, so a series can be measured in one
      // unit and read in another ("5m36s" over a bar 5.6 minutes long). A
      // formatted string in `value` itself would be NaN here and draw nothing.
      const shown = s.valueText ?? fmtNum(s.value);
      const row = el("div", { class: "bar-row", title: `${s.label}: ${shown}` });
      row.append(el("div", { class: "bar-label" }, s.label ?? ""));
      const fill = el("div", { class: `bar-fill ${s.fill || ""}`.trim() });
      fill.style.background = fillVar(s.fill);
      fill.style.width = `${pct.toFixed(2)}%`;
      row.append(el("div", { class: "bar-track" }, fill));
      row.append(el("div", { class: "bar-val" }, shown));
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

  // table — columns + rows; a cell is a string or { pill, tone }. Supports
  // `collapsible`/`collapsed` (see buildBlock) — e.g. repo_stats.py's "E2E
  // suites" table starts collapsed on a green run, open on a red one.
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
    return buildBlock(section, cardWrap);
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
      // A stack's own mark says "Swift" or "TypeScript" at a glance in a way a
      // laptop/desktop emoji never did — those distinguished client from
      // server, which the column titles already say.
      const logo = c.logo ? buildLogo(c.logo) : null;
      if (logo) head.append(logo);
      else if (c.icon) head.append(el("span", { class: "sec-icon", "aria-hidden": "true" }, c.icon));
      head.append(document.createTextNode(c.title || ""));
      col.append(head);
      const tiles = el("div", { class: "stats" });
      for (const item of c.items || []) tiles.append(buildStatTile(item));
      col.append(tiles);
      wrap.append(col);
    }
    return el("section", { class: "block" }, [buildHeading(section), wrap]);
  }

  // console — a terminal-styled log block (dark, monospace). Each line is a
  // status dot (tone-colored) + a status word + text + right-aligned meta.
  // Used for CI runs. Reads section.lines: {text, meta, status, tone, href, cmd}.

  // Render console rows into `term` (replacing its contents). Shared by the
  // static `console` renderer and the self-refreshing `live-console` one.
  function fillConsole(term, lines) {
    term.innerHTML = "";
    const rows = lines || [];
    for (const ln of rows) {
      const tone = ln.tone ? ` ${ln.tone}` : "";
      const line = el("div", { class: "console-line" });
      line.append(el("span", { class: `console-dot${tone}`, "aria-hidden": "true" }));
      line.append(el("span", { class: "console-status" }, ln.status ?? (ln.pill && ln.pill.text) ?? ""));
      // Which stack this run belongs to. One merged, chronological feed reads
      // better than two consoles — but only if each row says whose it is.
      const rowLogo = ln.logo ? buildLogo(ln.logo) : null;
      if (rowLogo) line.append(rowLogo);
      const text = ln.text ?? ln.q ?? "";
      line.append(el("span", { class: "console-text" },
        ln.href ? el("a", { href: ln.href, target: "_blank", rel: "noopener" }, text) : text));
      if (ln.cmd) {
        const chip = el("button", { class: "console-cmd", type: "button", title: "copy to clipboard" }, ln.cmd);
        chip.addEventListener("click", () => {
          navigator.clipboard.writeText(ln.cmd).then(() => {
            chip.classList.add("copied");
            setTimeout(() => chip.classList.remove("copied"), 1200);
          });
        });
        line.append(chip);
      }
      const metaText = [fmtTime(ln.ts), ln.meta ?? ln.note].filter(Boolean).join(" ");
      if (metaText) line.append(el("span", { class: "console-meta" }, metaText));
      term.append(line);
    }
    if (!rows.length) term.append(el("div", { class: "console-line console-empty" }, "no active runs"));
  }

  function renderConsole(section) {
    const term = el("div", { class: "console" });
    fillConsole(term, section.lines || section.items || []);
    return el("section", { class: "block" }, [buildHeading(section), term]);
  }

  // live-console — a self-refreshing console. Polls section.poll.url and
  // re-renders its rows, so in-progress/queued CI runs (which the static
  // collector filters out) show up live. The refresh cadence is a setting on
  // the SERVER-SIDE poller (the mini) — the endpoint reports its own intervalMs
  // and this view simply follows it, so there is one knob in one place. Section:
  //   { kind:"live-console", title, desc, poll:{ url, intervalMs } }
  // Endpoint returns { lines:[...], intervalMs?, updatedAt? }.
  function renderLiveConsole(section) {
    const poll = section.poll || {};
    const url = poll.url;
    let interval = Number(poll.intervalMs) || 30000;
    let timer = null;

    const dot = el("span", { class: "live-dot", title: "live" });
    const stamp = el("span", { class: "live-stamp" }, "connecting…");
    const controls = el("div", { class: "live-controls" }, [dot, el("span", { class: "live-label" }, "live"), stamp]);
    const term = el("div", { class: "console" });

    function schedule(ms) {
      if (timer) clearInterval(timer);
      timer = setInterval(tick, ms);
    }
    function tick() {
      if (!url) { fillConsole(term, []); dot.classList.add("stale"); stamp.textContent = "no endpoint"; return; }
      fetch(url, { cache: "no-cache" })
        .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then((data) => {
          fillConsole(term, data.lines || data.items || []);
          dot.classList.remove("stale");
          // Follow the poller's own cadence if it advertises one.
          const ms = Number(data.intervalMs) || interval;
          if (ms !== interval) { interval = ms; schedule(interval); }
          stamp.textContent = `updated ${new Date().toLocaleTimeString()} · every ${Math.round(interval / 1000)}s`;
        })
        .catch(() => {
          dot.classList.add("stale");
          stamp.textContent = "unreachable — retrying";
        });
    }

    tick();              // immediate first load
    schedule(interval);  // then follow the cadence
    return el("section", { class: "block" }, [buildHeading(section), controls, term]);
  }

  const RENDERERS = {
    stats: renderStats,
    compare: renderCompare,
    console: renderConsole,
    "live-console": renderLiveConsole,
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
    // Header nav links (e.g. a history page's "← back", or a board's "History →"
    // added by maybeAddHistoryLink). Always present so links can be appended.
    const nav = el("nav", { class: "board-links mono" });
    if (Array.isArray(data.links)) {
      for (const l of data.links) {
        if (l && l.href) nav.append(el("a", { href: l.href }, l.label || l.href));
      }
    }
    header.append(nav);
    return header;
  }

  // If this board has its own history page (a sibling history/board.json) and
  // isn't itself a history page, surface a "History →" link. Zero-config: the
  // link appears wherever the history collector generated a detail page.
  function maybeAddHistoryLink(container, data) {
    if (location.pathname.includes("/history/")) return;
    const declared = Array.isArray(data.links)
      && data.links.some((l) => l && /(^|\/)history\/?$/.test(l.href || ""));
    if (declared) return;
    fetch("history/board.json", { cache: "no-cache" })
      .then((r) => {
        if (!r.ok) return;
        const nav = container.querySelector("header.top .board-links");
        if (nav) nav.append(el("a", { href: "history/" }, "History →"));
      })
      .catch(() => {});
  }

  // Render one section into `parent`. An unknown kind or a throwing renderer
  // costs that one section, never the rest of the board.
  function appendSection(parent, section) {
    const renderFn = RENDERERS[section.kind];
    if (!renderFn) {
      console.warn(`statusgen: unknown section kind "${section.kind}"`);
      return;
    }
    try {
      parent.append(renderFn(section));
    } catch (err) {
      console.error(`statusgen: failed to render section kind "${section.kind}"`, err);
    }
  }

  // ---- tabs ---------------------------------------------------------------
  // A board groups its sections into tabs with a top-level `tabs` array:
  //
  //   "tabs": [{ "id": "now", "label": "Now", "icon": "⚡",
  //              "sections": ["CI — running now", "Builds"] }]
  //
  // Sections are claimed by TITLE, not by a key on the section itself —
  // deliberately. Collectors call upsert_section(), which replaces a section
  // wholesale by title, so any grouping key stored on the section would be
  // wiped on the next collector run. Keeping the mapping board-level means
  // tabs survive every collector without one line of collector change.
  //
  // Anything no tab claims renders ABOVE the tab bar and stays visible on
  // every tab. That covers the untitled hero row and banner (no title to key
  // on), and makes the failure mode safe: a section a tab forgot shows up
  // rather than vanishing into a tab nobody opens.
  function partitionSections(data) {
    const sections = Array.isArray(data.sections) ? data.sections : [];
    const tabs = Array.isArray(data.tabs) ? data.tabs.filter((t) => t && t.id) : [];
    if (!tabs.length) return { pinned: sections, groups: [] };

    const claim = new Map();
    for (const tab of tabs) {
      for (const title of Array.isArray(tab.sections) ? tab.sections : []) {
        if (!claim.has(title)) claim.set(title, tab.id);
      }
    }
    const byTab = new Map(tabs.map((t) => [t.id, []]));
    const pinned = [];
    for (const section of sections) {
      const id = section.title ? claim.get(section.title) : undefined;
      if (id && byTab.has(id)) byTab.get(id).push(section);
      else pinned.push(section);
    }
    // Drop tabs that claimed nothing present — a board can list a tab before
    // its collector has ever seeded the section, and an empty tab is noise.
    const groups = tabs
      .map((tab) => ({ tab, sections: byTab.get(tab.id) }))
      .filter((g) => g.sections.length);
    return { pinned, groups };
  }

  function renderTabs(groups) {
    const nav = el("nav", { class: "tabs", role: "tablist" });
    const panels = el("div", { class: "tab-panels" });
    const entries = [];

    for (const { tab, sections } of groups) {
      const panel = el("div", {
        class: "tab-panel", id: `panel-${tab.id}`, role: "tabpanel", hidden: "",
      });
      for (const section of sections) appendSection(panel, section);
      panels.append(panel);

      const btn = el("button", {
        class: "tab", type: "button", role: "tab",
        id: `tab-${tab.id}`, "aria-controls": `panel-${tab.id}`, "aria-selected": "false",
      });
      const tabLogo = tab.logo ? buildLogo(tab.logo) : null;
      if (tabLogo) btn.append(tabLogo);
      else if (tab.icon) btn.append(el("span", { class: "tab-icon", "aria-hidden": "true" }, tab.icon));
      btn.append(document.createTextNode(tab.label || tab.id));
      btn.addEventListener("click", () => select(tab.id, true));
      nav.append(btn);
      entries.push({ id: tab.id, btn, panel });
    }

    // The active tab lives in the URL hash so a tab is linkable and survives
    // reload — replaceState, not a hash assignment, so switching tabs doesn't
    // scroll the page or stack up history entries.
    function select(id, updateHash) {
      const target = entries.find((e) => e.id === id) || entries[0];
      if (!target) return;
      for (const e of entries) {
        const on = e === target;
        e.btn.classList.toggle("on", on);
        e.btn.setAttribute("aria-selected", String(on));
        e.panel.hidden = !on;
      }
      if (updateHash) history.replaceState(null, "", `#${target.id}`);
    }

    const fromHash = decodeURIComponent(location.hash.replace(/^#/, ""));
    select(entries.some((e) => e.id === fromHash) ? fromHash : entries[0].id, false);
    window.addEventListener("hashchange", () => {
      const id = decodeURIComponent(location.hash.replace(/^#/, ""));
      if (entries.some((e) => e.id === id)) select(id, false);
    });

    return [nav, panels];
  }

  function renderBoard(data, container, generatedAt) {
    if (data.title) document.title = data.title;
    staleAfterDays = Number.isFinite(Number(data.staleAfterDays))
      ? Number(data.staleAfterDays) : 7;

    container.innerHTML = "";
    container.append(renderHeader(data, generatedAt));

    const { pinned, groups } = partitionSections(data);
    for (const section of pinned) appendSection(container, section);
    if (groups.length) container.append(...renderTabs(groups));
  }

  function showError(container, message) {
    container.innerHTML = "";
    container.append(el("p", { class: "board-error" }, message));
  }

  // How often an open tab re-checks the board.
  //
  // The board used to be fetched exactly once, at boot, so a tab left open was
  // frozen at whatever it loaded — every run that landed afterwards was
  // invisible until someone pressed reload. That is indistinguishable from a
  // build vanishing, and it is what a board left open on a wall does all day.
  // Reported, repeatedly, as runs disappearing.
  const REFRESH_MS = 60_000;

  function init() {
    const container = document.getElementById("board-root") || document.body;
    const src = window.BOARD_SRC || "board.json";
    // Re-render only when the file actually changed. A board is a page people
    // scroll and expand things on; redrawing it every minute for no reason
    // would throw that away and make the tab unusable.
    let lastSeen = null;
    let failures = 0;

    const load = (isRefresh) =>
      fetch(src, { cache: "no-cache" })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const generatedAt = res.headers.get("Last-Modified");
          return res.text().then((text) => ({ text, generatedAt }));
        })
        .then(({ text, generatedAt }) => {
          failures = 0;
          // Compare the payload itself rather than Last-Modified: a CDN in
          // front of the site can rewrite or omit that header, and being wrong
          // here means silently never updating again — the exact bug this
          // exists to fix.
          if (isRefresh && text === lastSeen) return;
          lastSeen = text;
          renderBoard(JSON.parse(text), container, generatedAt);
          maybeAddHistoryLink(container, JSON.parse(text));
        })
        .catch((err) => {
          // A refresh that fails leaves the board that is already on screen —
          // stale data beats replacing a working page with an error because
          // the network blipped. Only the first load has nothing to fall back
          // to.
          if (!isRefresh) showError(container, `Couldn't load ${src}: ${err.message}`);
          else if (++failures === 1) console.warn(`board refresh failed: ${err.message}`);
        });

    load(false);

    if (typeof setInterval === "function") {
      setInterval(() => load(true), REFRESH_MS);
    }
    // A tab that has been in the background for hours is the worst offender:
    // catch it up the moment it is looked at, rather than up to a minute later.
    if (typeof document.addEventListener === "function") {
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) load(true);
      });
    }
  }

  // Test seam: tests/test_tabs.mjs evaluates this file against a stub DOM and
  // drives the renderer headlessly. `module` is undefined in a browser, so the
  // guard makes this a no-op everywhere it actually ships.
  if (typeof module === "object" && module && module.exports) {
    module.exports = { renderBoard, partitionSections, buildStatTile, init };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

// Session chip — when the hosting site is gated behind a vault instance
// (see docs in README), show who is signed in and offer sign-out.
// Config: /_assets/site.json {"vault": "https://vault.example.com"}.
// Absent config or signed-out → renders nothing. Never throws.
(async () => {
  try {
    const cfg = await fetch("/_assets/site.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!cfg || !cfg.vault) return;
    const me = await fetch(cfg.vault + "/api/me", { credentials: "include" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!me) return;

    // Build the chip container.
    const chip = document.createElement("div");
    chip.className = "sgen-session-chip";
    chip.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:1000;background:rgba(23,26,33,.92);border:1px solid #2e3542;border-radius:999px;padding:6px 12px 6px 6px;display:flex;align-items:center;gap:8px;font-size:12px;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#e6e8eb;box-shadow:0 2px 8px rgba(0,0,0,.4);";

    // Avatar image (if present).
    if (me.avatar && typeof me.avatar === "string" && me.avatar.trim()) {
      const img = document.createElement("img");
      img.src = me.avatar;
      img.referrerPolicy = "no-referrer";
      img.style.cssText = "width:22px;height:22px;border-radius:50%;display:block;";
      chip.appendChild(img);
    }

    // Email or ID text.
    const emailSpan = document.createElement("span");
    emailSpan.textContent = me.email || me.id || "";
    emailSpan.style.cssText = "max-width:26ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    chip.appendChild(emailSpan);

    // Sign-out link.
    const signoutLink = document.createElement("a");
    signoutLink.href = cfg.vault + "/auth/logout?return=" + encodeURIComponent(location.href);
    signoutLink.textContent = "sign out";
    signoutLink.style.cssText = "color:#9aa3af;text-decoration:none;cursor:pointer;";
    signoutLink.addEventListener("mouseover", () => { signoutLink.style.textDecoration = "underline"; });
    signoutLink.addEventListener("mouseout", () => { signoutLink.style.textDecoration = "none"; });
    chip.appendChild(signoutLink);

    document.body.appendChild(chip);
  } catch (_) { /* cosmetic feature — never break the board */ }
})();
