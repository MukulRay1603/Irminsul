/* Answer presentation: Markdown for AI-written answers, and interactive cards for exact answers.
   Loaded before app.js (both deferred), so these functions are shared globals. No inline styles
   or handlers: everything works under the strict Content-Security-Policy. */

const escHTML = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Numbers and percentages glow gold, so the figures that matter stand out at a glance.
const goldNumbers = html => html.replace(/(^|[\s(>/+-])(\d[\d,]*(?:\.\d+)?%?)(?=[\s).,;:<]|$)/g, '$1<b class="num">$2</b>');

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\[(\d+)\]/g, '<sup class="cite"><a href="#src-$1" aria-label="Source $1">$1</a></sup>');
}

/* Markdown subset the AI is asked to use: a bold lead sentence, bullets, numbered steps,
   ### headings, tables and > callouts. Input is escaped first, so nothing in it is ever HTML. */
// Some models cite as 【3】 or 【3†source】; show every citation the same way, as [3].
const normaliseCitations = text => String(text ?? "").replace(/【\s*(\d+)[^】]*】/g, "[$1]");

function renderMarkdown(text) {
  const lines = escHTML(normaliseCitations(text)).split("\n");
  let html = "", list = null, table = null, para = [];
  const flushPara = () => {
    if (!para.length) return;
    const p = para.join(" ");
    const lead = !html && /^<strong>[^]*<\/strong>[.!?]?(\s*<sup[^]*)?$/.test(inline(goldNumbers(p)).trim());
    html += `<p${lead ? ' class="lead"' : ""}>${inline(goldNumbers(p))}</p>`;
    para = [];
  };
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  const closeTable = () => {
    if (!table) return;
    const [head, ...rows] = table;
    html += `<div class="table-wrap"><table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(r => `<tr>${r.map(c => `<td>${inline(goldNumbers(c))}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>";
    table = null;
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    const cells = /^\s*\|.*\|\s*$/.test(l) ? l.trim().slice(1, -1).split("|").map(c => c.trim()) : null;
    if (cells) {
      flushPara(); closeList();
      if (cells.every(c => /^:?-{2,}:?$/.test(c))) continue;  // the |---| separator row
      (table ||= []).push(cells); continue;
    }
    closeTable();
    let m;
    if ((m = l.match(/^\s*#{2,4}\s+(.*)/))) { flushPara(); closeList(); html += `<h4>${inline(m[1])}</h4>`; continue; }
    if ((m = l.match(/^\s*[-·*]\s+(.*)/)) || (m = l.match(/^\s*(\d+)[.)]\s+(.*)/))) {
      flushPara();
      const kind = m.length === 3 ? "ol" : "ul", body = m.length === 3 ? m[2] : m[1];
      if (list !== kind) { closeList(); html += `<${kind}>`; list = kind; }
      html += `<li>${inline(goldNumbers(body))}</li>`; continue;
    }
    if ((m = l.match(/^\s*&gt;\s?(.*)/))) { flushPara(); closeList(); html += `<blockquote>${inline(goldNumbers(m[1]))}</blockquote>`; continue; }
    if (!l.trim()) { flushPara(); closeList(); continue; }
    closeList(); para.push(l.trim());
  }
  flushPara(); closeList(); closeTable();
  return html;
}

/* ---------- Cards for exact answers ---------- */
const stars = n => n ? `<span class="stars" aria-label="${n} stars">${"★".repeat(n)}</span>` : "";
const tags = c => [c.element, c.weapon_type, c.region].filter(Boolean).map(t => `<span>${escHTML(t)}</span>`).join("");
const prose = t => escHTML(t).split(/\n{2,}/).map(p => `<p>${goldNumbers(p.replace(/\n/g, "<br>"))}</p>`).join("");

function cardHead(c, kicker) {
  return `<header class="xc-head">
    <div><span class="xc-kicker">${escHTML(kicker)}</span><h3>${escHTML(c.name)}</h3>${c.title ? `<div class="xc-title">${escHTML(c.title)}</div>` : ""}</div>
    <div class="xc-meta">${stars(c.rarity)}<div class="xc-tags">${tags(c)}</div></div></header>`;
}

// A row of buttons that switches what the card shows, without asking the server again.
function segmented(name, options, selected) {
  return `<div class="seg" role="tablist" aria-label="${escHTML(name)}">${options.map(o =>
    `<button type="button" role="tab" data-key="${escHTML(o.key)}" aria-selected="${String(o.key) === String(selected)}">${escHTML(o.label)}</button>`).join("")}</div>`;
}

const CARDS = {
  stats: c => `${cardHead(c, `Level ${c.level} base stats`)}
    <div class="xc-stats">${c.stats.map(s => `<div class="xc-stat"><span>${escHTML(s.label)}</span><b>${escHTML(s.value)}</b></div>`).join("")}
      <div class="xc-stat gold"><span>${escHTML(c.highlight.label)}</span><b>${escHTML(c.highlight.value)}</b></div></div>
    <p class="xc-foot">Fully ascended, before weapons and artifacts.</p>`,

  talents: c => `${cardHead(c, "Talents")}
    ${segmented("Talent", c.tabs, c.selected)}
    <div class="xc-panel" data-panel></div>`,

  constellations: c => `${cardHead(c, "Constellations")}
    ${segmented("Constellation", c.items.map(x => ({ key: x.level, label: `C${x.level}` })), c.selected)}
    <div class="xc-panel" data-panel></div>`,

  weapon: c => `${cardHead({ ...c, element: null, region: null }, "Weapon")}
    <div class="xc-stats two">${c.stats.map(s => `<div class="xc-stat"><span>${escHTML(s.label)}</span><b>${escHTML(s.value)}</b></div>`).join("")}</div>
    ${c.passive_name ? `<h4 class="xc-sub">${escHTML(c.passive_name)}</h4>
      ${c.refinements.length > 1 ? segmented("Refinement", c.refinements.map((_, i) => ({ key: i + 1, label: `R${i + 1}` })), c.selected) : ""}
      <div class="xc-panel" data-panel></div>` : ""}`,

  set: c => `<header class="xc-head"><div><span class="xc-kicker">Artifact set</span><h3>${escHTML(c.name)}</h3></div></header>
    <ol class="xc-bonus">${c.bonuses.map(b => `<li><span class="pc">${b.pieces}-piece</span><div>${prose(b.text)}</div></li>`).join("")}</ol>`,

  // Columns per entity, rows per stat; the higher number in a row is gold.
  compare: c => `<header class="xc-head"><div><span class="xc-kicker">${escHTML(c.kicker)}</span><h3>${c.columns.map(x => escHTML(x.name)).join(' <span class="xc-vs">vs</span> ')}</h3></div></header>
    <div class="table-wrap xc-cmp-wrap"><table class="xc-cmp xc-cmp-${c.columns.length}">
      <thead><tr><td></td>${c.columns.map(x => `<th scope="col"><span class="xc-cmp-name">${escHTML(x.name)}</span>${stars(x.rarity)}<span class="xc-cmp-sub">${escHTML(x.sub || "")}</span></th>`).join("")}</tr></thead>
      <tbody>${c.rows.map(r => `<tr${r.text ? ' class="text"' : ""}><th scope="row">${escHTML(r.label)}</th>${r.values.map((v, i) =>
        r.text ? `<td>${prose(v)}</td>` : `<td${r.best.includes(i) ? ' class="best"' : ""}>${escHTML(v)}${r.best.includes(i) ? '<span class="xc-sr"> (higher)</span>' : ""}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>
    <p class="xc-foot">${escHTML(c.note)}</p>`,

  announced: c => `${cardHead(c, "Officially announced")}
    <div class="xc-callout"><b>Not playable yet.</b> Only what HoYoverse has officially shown is listed here. Talents and constellations appear once the character is released.</div>`,
};

/* Talent scaling with a level slider. The data only has some levels (1, 6, 9, 10, 13), so the
   slider steps through those. Every value is already in the card: moving it asks nothing. */
let scaleIds = 0;
const nearest = (levels, lv) => levels.reduce((best, l, i) => Math.abs(l - lv) < Math.abs(levels[best] - lv) ? i : best, 0);

function scalingTable(t, card) {
  const levels = t.levels || [];
  if (!levels.length || !t.scaling?.length) return "";  // passives have no scaling
  const i = nearest(levels, card._lv ?? 10), lv = levels[i], id = `lv-${++scaleIds}`;
  return `<div class="xc-scale" data-t="${card.talents.indexOf(t)}">
    <div class="xc-lv">
      <label for="${id}">Talent level</label>
      <button type="button" class="lv-step" data-step="-1" aria-label="Lower talent level" aria-controls="${id}" aria-disabled="${i === 0}">−</button>
      <input type="range" id="${id}" min="0" max="${levels.length - 1}" step="1" value="${i}" aria-valuetext="Level ${lv}">
      <button type="button" class="lv-step" data-step="1" aria-label="Raise talent level" aria-controls="${id}" aria-disabled="${i === levels.length - 1}">+</button>
      <output for="${id}" class="lv-out">Lv. <b>${lv}</b></output>
    </div>
    <table class="xc-scaling"><tbody>${t.scaling.map(r => `<tr><th scope="row">${escHTML(r.label)}</th><td>${escHTML(r.values[i])}</td></tr>`).join("")}</tbody></table>
    <p class="xc-lv-note"${lv > 10 ? "" : " hidden"}>Levels above 10 come from constellations.</p>
  </div>`;
}

function setLevel(card, scale, i) {
  const t = card.talents[Number(scale.dataset.t)], levels = t.levels;
  i = Math.max(0, Math.min(levels.length - 1, i));
  const lv = levels[i], input = scale.querySelector("input[type=range]");
  input.value = i; input.setAttribute("aria-valuetext", `Level ${lv}`);
  card._lv = lv;  // remembered across tabs
  scale.querySelector(".lv-out b").textContent = lv;
  scale.querySelectorAll(".xc-scaling td").forEach((td, r) => { td.textContent = t.scaling[r].values[i]; });
  scale.querySelector(".xc-lv-note").hidden = lv <= 10;
  scale.querySelectorAll(".lv-step").forEach(b => b.setAttribute("aria-disabled", String(i + Number(b.dataset.step) < 0 || i + Number(b.dataset.step) >= levels.length)));
}

function bindScaling(card, panel) {
  panel.addEventListener("input", e => {
    const scale = e.target.closest(".xc-scale");
    if (scale && e.target.type === "range") setLevel(card, scale, Number(e.target.value));
  });
  panel.addEventListener("click", e => {
    const b = e.target.closest(".lv-step"), scale = b?.closest(".xc-scale");
    if (scale) setLevel(card, scale, Number(scale.querySelector("input[type=range]").value) + Number(b.dataset.step));
  });
}

// What a switchable card shows for the selected button
const PANELS = {
  talents: (c, key) => c.talents.filter(t => t.kind === key).map(t =>
    `<article><h4 class="xc-sub">${escHTML(t.name)}</h4>${prose(t.description)}${scalingTable(t, c)}</article>`).join(""),
  constellations: (c, key) => {
    const x = c.items.find(i => String(i.level) === String(key));
    return x ? `<article><h4 class="xc-sub">C${x.level} · ${escHTML(x.name)}</h4>${prose(x.description)}</article>` : "";
  },
  weapon: (c, key) => prose(c.refinements[Number(key) - 1] || ""),
};

function renderCard(card) {
  const make = CARDS[card.type];
  if (!make) return null;
  const el = document.createElement("div");
  el.className = `xcard card-${card.type}`;
  el.dataset.el = card.element || "";
  el.innerHTML = make(card);
  const panel = el.querySelector("[data-panel]"), seg = el.querySelector(".seg");
  if (panel && PANELS[card.type]) {
    const show = key => {
      panel.innerHTML = PANELS[card.type](card, key);
      panel.classList.remove("swap"); void panel.offsetWidth; panel.classList.add("swap");
      seg?.querySelectorAll("button").forEach(b => b.setAttribute("aria-selected", b.dataset.key === String(key)));
    };
    show(card.selected);
    if (card.type === "talents") bindScaling(card, panel);
    seg?.addEventListener("click", e => { const b = e.target.closest("button[data-key]"); if (b) show(b.dataset.key); });
    // Arrow keys move between the buttons, like real tabs
    seg?.addEventListener("keydown", e => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const bs = [...seg.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
      const next = bs[(i + (e.key === "ArrowRight" ? 1 : -1) + bs.length) % bs.length];
      next.focus(); next.click(); e.preventDefault();
    });
  }
  return el;
}

/* ---------- Answer header: what kind of answer this is, and copy ---------- */
const BADGES = {
  exact: ["From game data", "No AI used", "exact"],
  announced: ["Official announcement", "No AI used", "announced"],
  rag: ["Written by AI", "from cited sources", "ai"],
  refuse_leak: ["Leak filter", "Nothing searched", "guard"],
  refuse_injection: ["Guardrail", "Request refused", "guard"],
  refuse_offtopic: ["Genshin only", "Outside what I cover", "guard"],
  busy: ["Busy", "Try again soon", "busy"],
  no_llm: ["AI answers off", "Game-data answers still work", "busy"],
  rag_empty: ["No sources found", "Not in released data", "busy"],
  no_allowance: ["AI answers used up for now", "They refill over time", "busy"],
};

function answerHeader(route, version, nSources) {
  const [label, sub, cls] = BADGES[route] || [route, "", ""];
  const detail = route === "rag" && nSources ? `from ${nSources} cited source${nSources === 1 ? "" : "s"}` : sub;
  return `<div class="ans-head"><span class="badge ${cls}"><i></i>${escHTML(label)}</span><span class="badge-sub">${escHTML(detail)}</span>
    ${version ? `<span class="ver" title="Game data version this answer comes from">v${escHTML(version)}</span>` : ""}
    <button type="button" class="copy" aria-label="Copy answer" title="Copy answer">Copy</button></div>`;
}
