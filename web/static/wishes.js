/* Wish tracker: pity, odds and savings. Everything a player enters stays on this device
   (localStorage); the server only ever gets plain numbers to do sums on. Imported files are
   read in the browser and never uploaded. No login, no UID, no link to the game.
   No inline styles or handlers: the page runs under a strict CSP. */

(() => {
  const root = document.getElementById("wishesApp");
  if (!root) return;
  const KEY = "irminsul-wishes";
  const BANNERS = { character: { label: "Character", hard: 90, sure: "Guaranteed (lost my last 50/50)" },
                    weapon: { label: "Weapon", hard: 80, sure: "Fate Point ready" } };
  const fresh = () => ({ banner: "character", primos: 0, fates: 0, copies: 1, welkin: false, target: "",
    character: { pity: 0, guaranteed: false }, weapon: { pity: 0, guaranteed: false }, log: [] });
  const load = () => { try { return { ...fresh(), ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return fresh(); } };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch {} };
  let s = load(), targets = [], timer = 0, imported = "";

  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
    return el;
  }
  const num = (label, key, max, onset) => h("label", { class: "wt-field" }, h("span", { text: label }),
    h("input", { type: "number", min: "0", max: String(max), inputmode: "numeric", value: String(onset.get()),
      oninput: e => { onset.set(Math.max(0, Math.min(max, parseInt(e.target.value, 10) || 0))); changed(); } }));
  const plain = n => n.toLocaleString();
  const today = () => new Date().toISOString().slice(0, 10);
  const wishes = () => s.fates + Math.floor(s.primos / 160);
  const cur = () => s[s.banner];

  /* ---------- tapping through wishes ---------- */
  function pulled(n) {
    const b = cur(), hard = BANNERS[s.banner].hard;
    b.pity = Math.min(hard - 1, b.pity + n);
    changed(true);
  }
  function gotFive(won) {
    const b = cur();
    s.log.unshift({ banner: s.banner, pulls: b.pity + 1, won, day: new Date().toISOString().slice(0, 10) });
    s.log = s.log.slice(0, 40);
    b.pity = 0;
    b.guaranteed = !won;
    changed(true);
  }

  /* ---------- import a file (read here, never uploaded) ---------- */
  function records(data) {
    if (Array.isArray(data?.list)) return data.list;  // UIGF 3
    if (Array.isArray(data?.hk4e)) return data.hk4e.flatMap(a => a.list || []);  // UIGF 4
    return null;
  }
  function importFile(file) {
    const note = root.querySelector(".wt-import-note");
    const reader = new FileReader();
    reader.onload = () => {
      let list;
      try { list = records(JSON.parse(reader.result)); } catch { list = null; }
      if (!list?.length) { imported = "That file isn't a UIGF wish export."; note.textContent = imported; return; }
      const type = r => String(r.uigf_gacha_type || r.gacha_type);
      const count = banner => {
        const rows = list.filter(r => (banner === "weapon" ? type(r) === "302" : ["301", "400"].includes(type(r))))
          .sort((a, b) => (BigInt(a.id || 0) < BigInt(b.id || 0) ? -1 : 1));
        let since = 0; const fives = [];
        for (const r of rows) {
          since += 1;
          if (String(r.rank_type) === "5") { fives.push({ banner, name: String(r.name || "").slice(0, 40), pulls: since, day: String(r.time || "").slice(0, 10) }); since = 0; }
        }
        s[banner].pity = Math.min(BANNERS[banner].hard - 1, since);
        return { rows: rows.length, fives };
      };
      const c = count("character"), w = count("weapon");
      s.log = [...c.fives, ...w.fives].sort((a, b) => (a.day < b.day ? 1 : -1)).slice(0, 40);
      imported = `Imported ${plain(c.rows + w.rows)} wishes. Pity is filled in. Tick "guaranteed" yourself if you lost your last 50/50.`;
      changed(true);
    };
    reader.readAsText(file);
  }

  /* ---------- results ---------- */
  const out = h("div", { class: "wt-out", "aria-live": "polite" });
  const savings = h("div", { class: "wt-save", "aria-live": "polite" });
  const percent = x => (x >= 0.995 && x < 1 ? ">99%" : x < 0.005 && x > 0 ? "<1%" : `${Math.round(x * 100)}%`);
  async function calculate() {
    const b = cur(), q = new URLSearchParams({ wishes: wishes(), banner: s.banner, pity: b.pity, guaranteed: b.guaranteed, copies: s.copies });
    try {
      const r = await fetch(`/api/pulls/odds?${q}`); if (!r.ok) throw 0;
      const o = await r.json();
      out.replaceChildren(
        h("p", { class: "wt-big" }, h("b", { text: percent(o.chance) }), ` chance with ${plain(wishes())} wishes`),
        h("p", { class: "wt-small", text: `About ${Math.round(o.expected)} wishes on average. ${o.worst} at the very worst, which is guaranteed.` }));
    } catch { out.replaceChildren(h("p", { class: "wt-small", text: "Odds didn't load. Try again in a moment." })); }
    if (!s.target) return savings.replaceChildren();
    try {
      const r = await fetch(`/api/pulls/income?${new URLSearchParams({ until: s.target, welkin: s.welkin })}`); if (!r.ok) throw 0;
      const e = await r.json();
      savings.replaceChildren(
        h("p", { class: "wt-big" }, "About ", h("b", { text: plain(wishes() + e.likely_wishes) }), " wishes by then"),
        h("p", { class: "wt-small", text: `Your ${plain(wishes())} now, plus about ${plain(e.likely)} free Primogems (at least ${plain(e.primos)})${e.shop_fates ? ` and ${e.shop_fates} shop Fates` : ""}, counting dailies, resets, codes, compensation and usual events. Dates are estimates.` }));
    } catch { savings.replaceChildren(); }
  }
  function changed(redraw) {
    save();
    if (redraw) render();
    clearTimeout(timer); timer = setTimeout(calculate, 250);
  }

  function history() {
    const rows = s.log.filter(x => x.banner === s.banner).slice(0, 8);
    if (!rows.length) return null;
    return h("details", { class: "wt-log" }, h("summary", { text: `Recent 5-stars (${rows.length})` }),
      h("ul", {}, rows.map(x => h("li", {}, h("b", { text: x.name || (x.won ? "Won the 50/50" : "Lost the 50/50") }), ` at ${x.pulls} pulls`, x.day ? ` · ${x.day}` : ""))));
  }
  function render() {
    const b = cur(), info = BANNERS[s.banner];
    const tabs = h("div", { class: "wt-tabs", role: "group", "aria-label": "Banner" }, Object.entries(BANNERS).map(([k, v]) =>
      h("button", { type: "button", "aria-pressed": String(k === s.banner), text: v.label, onclick: () => { s.banner = k; changed(true); } })));
    const fileInput = h("input", { type: "file", accept: ".json,application/json", class: "wt-file", id: "wtFile",
      onchange: e => e.target.files[0] && importFile(e.target.files[0]) });
    root.replaceChildren(h("div", { class: "wt-grid" },
      h("div", { class: "wt-card" },
        h("h3", { text: "Your banner" }), tabs,
        h("div", { class: "wt-row" }, num("Current pity", "pity", info.hard - 1, { get: () => b.pity, set: v => { b.pity = v; } }),
          h("label", { class: "wt-check" }, h("input", { type: "checkbox", checked: b.guaranteed, onchange: e => { b.guaranteed = e.target.checked; changed(); } }), h("span", { text: info.sure }))),
        h("div", { class: "wt-taps" },
          h("button", { type: "button", text: "+1 wish", onclick: () => pulled(1) }),
          h("button", { type: "button", text: "+10 wishes", onclick: () => pulled(10) }),
          h("button", { type: "button", class: "gold", text: "Got what I wanted", onclick: () => gotFive(true) }),
          h("button", { type: "button", text: s.banner === "weapon" ? "Got the wrong 5-star" : "Lost the 50/50", onclick: () => gotFive(false) })),
        history(),
        h("div", { class: "wt-import" }, fileInput, h("label", { for: "wtFile", class: "wt-file-btn", text: "Import a wish history file" }),
          h("p", { class: "wt-import-note", text: imported || "UIGF JSON from any wish tool. It's read in your browser and never uploaded. Never paste a game link or run a script for a website, including this one." }))),
      h("div", { class: "wt-card" },
        h("h3", { text: "Your stash" }),
        h("div", { class: "wt-row" }, num(s.estimated ? "Primogems (estimate, tell me the real number anytime)" : "Primogems", "primos", 999999, { get: () => s.primos, set: v => { s.primos = v; s.asOf = today(); s.estimated = false; } }),
          num("Intertwined Fates", "fates", 9999, { get: () => s.fates, set: v => { s.fates = v; } }),
          num(s.banner === "weapon" ? "Copies wanted" : "Copies wanted (C0 = 1)", "copies", 7, { get: () => s.copies, set: v => { s.copies = Math.max(1, v); } })),
        out,
        h("h3", { text: "Saving up" }),
        h("div", { class: "wt-row" }, h("label", { class: "wt-field wide" }, h("span", { text: "By when?" }),
          h("select", { onchange: e => { s.target = e.target.value; changed(); } }, h("option", { value: "", text: "Pick a version" }),
            targets.map(t => h("option", { value: t.date, selected: t.date === s.target, text: `${t.label} (about ${t.date})` })))),
          h("label", { class: "wt-check" }, h("input", { type: "checkbox", checked: s.welkin, onchange: e => { s.welkin = e.target.checked; changed(); } }), h("span", { text: "I have Welkin Moon" }))),
        savings)));
    calculate();
  }

  /* ---------- the chat is the input: it tells us, we remember ---------- */
  window.wishes = {
    memory() {
      const stash = s.primos || s.fates || s.character.pity
        ? { primos: s.primos, fates: s.fates, pity: s.character.pity, guaranteed: s.character.guaranteed } : null;
      return { stash, uid: s.uid || null };
    },
    remember(trace) {
      if (trace?.uid) { s.uid = trace.uid; save(); }
      const t = trace?.stash; if (!t) return;
      if (t.primos) s.primos = t.primos;
      if (t.fates) s.fates = t.fates;
      if (t.primos || t.fates) s.asOf = today();
      s.character.pity = t.pity ?? s.character.pity;
      s.character.guaranteed = t.guaranteed ?? s.character.guaranteed;
      changed(true);
    },
  };

  /* Primogems earned since the player last told us: dailies and resets add up by themselves */
  async function catchUp() {
    if (!s.asOf || s.asOf >= today() || !s.primos) return;
    try {
      const q = new URLSearchParams({ until: today(), since: s.asOf });
      const r = await fetch(`/api/pulls/income?${q}`); if (!r.ok) return;
      s.primos += (await r.json()).primos; s.asOf = today(); s.estimated = true; changed(true);
    } catch {}
  }

  fetch("/api/pulls/targets").then(r => (r.ok ? r.json() : { targets: [] })).then(d => { targets = d.targets; render(); catchUp(); }).catch(render);
})();
