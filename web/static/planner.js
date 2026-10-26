/* Irminsul daily planner. Everything the player saves stays on this device:
   IndexedDB (localStorage as a fallback), a backup file they download, and a transfer link
   whose plan lives in the URL #fragment, which browsers never send to the server.
   Game data (domains, days, costs) comes read-only from GET /api/planner. */

const $ = (s, el = document) => el.querySelector(s);
const ELEMENT = { Pyro: "#F2774E", Hydro: "#4CC2F1", Anemo: "#72E2C2", Electro: "#B88CFF", Dendro: "#A5D64B", Cryo: "#9FE3F5", Geo: "#F2C14E" };
const DAYS = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_NAMES = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SERVERS = { america: ["America", -5], europe: ["Europe", 1], asia: ["Asia", 8] };
const TALENTS = ["Normal Attack", "Skill", "Burst"];
const PLAN_VERSION = 1;
const MAX_ITEMS = 300; // characters + weapons a plan may hold (imports are clipped to this)
const ID_RE = /^[a-z0-9-]{1,80}$/;

/* ---------- tiny DOM helper (no inline styles or handlers: the page runs under a strict CSP) ---------- */
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

/* ---------- storage: IndexedDB with a localStorage fallback ---------- */
const DB = (() => {
  const LS = "irminsul-planner-";
  let dbp = null;
  function open() {
    if (dbp) return dbp;
    dbp = new Promise((resolve, reject) => {
      if (!("indexedDB" in self)) return reject(new Error("no IndexedDB"));
      const req = indexedDB.open("irminsul", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error("IndexedDB blocked"));
    });
    return dbp;
  }
  function tx(mode, fn) {
    return open().then(db => new Promise((resolve, reject) => {
      const t = db.transaction("kv", mode), req = fn(t.objectStore("kv"));
      t.oncomplete = () => resolve(req?.result);
      t.onerror = t.onabort = () => reject(t.error);
    }));
  }
  const lsGet = k => { try { const v = localStorage.getItem(LS + k); return v ? JSON.parse(v) : undefined; } catch { return undefined; } };
  const lsSet = k => v => { try { localStorage.setItem(LS + k, JSON.stringify(v)); return true; } catch { return false; } };
  return {
    async get(k) {
      try { const v = await tx("readonly", s => s.get(k)); if (v !== undefined) return v; } catch {}
      return lsGet(k);
    },
    async set(k, v) {
      let ok = false;
      try { await tx("readwrite", s => s.put(v, k)); ok = true; } catch {}
      // A localStorage copy too: it survives an IndexedDB that fails to open on the next visit.
      return lsSet(k)(v) || ok;
    },
  };
})();
const local = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

/* ---------- plan shape, validation and size ---------- */
const clamp = (n, lo, hi, dflt) => { n = Math.round(Number(n)); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt; };
function guessServer() {
  const off = -new Date().getTimezoneOffset() / 60;
  return off <= -2 ? "america" : off < 4 ? "europe" : "asia";
}
const emptyPlan = () => ({ v: PLAN_VERSION, server: guessServer(), characters: [], weapons: [] });
// Every plan from storage, a file or a link goes through here: untrusted input in, a clean plan out.
function cleanPlan(raw) {
  if (!raw || typeof raw !== "object") return null;
  const seen = new Set(), plan = emptyPlan();
  if (raw.server in SERVERS) plan.server = raw.server;
  for (const c of Array.isArray(raw.characters) ? raw.characters : []) {
    const id = String(c?.id || "").replace(/^character\//, "");
    if (!ID_RE.test(id) || seen.has("c" + id) || plan.characters.length >= MAX_ITEMS) continue;
    seen.add("c" + id);
    const t = Array.isArray(c.talents) ? c.talents : [];
    plan.characters.push({
      id: "character/" + id,
      level: clamp(c.level, 1, 100, 90),
      talents: [0, 1, 2].map(i => {
        const now = clamp(t[i]?.[0], 1, 10, 1);
        return [now, clamp(t[i]?.[1], now, 10, Math.max(now, 8))];
      }),
    });
  }
  for (const w of Array.isArray(raw.weapons) ? raw.weapons : []) {
    const id = String(w?.id || "").replace(/^weapon\//, "");
    if (!ID_RE.test(id) || seen.has("w" + id) || plan.weapons.length >= MAX_ITEMS) continue;
    seen.add("w" + id);
    plan.weapons.push({ id: "weapon/" + id });
  }
  return plan;
}
const planSize = p => (p?.characters?.length || 0) + (p?.weapons?.length || 0);
const describe = p => {
  const c = p.characters.length, w = p.weapons.length;
  return `${c} character${c === 1 ? "" : "s"}${w ? ` and ${w} weapon${w === 1 ? "" : "s"}` : ""}`;
};

/* ---------- server day and daily reset (04:00 server time) ---------- */
function serverClock(server, now = Date.now()) {
  const shifted = now + SERVERS[server][1] * 3600e3; // server wall clock, read with getUTC*
  const gameDay = new Date(shifted - 4 * 3600e3); // the "day" flips at 04:00
  const iso = gameDay.toISOString().slice(0, 10);
  const weekday = gameDay.getUTCDay() || 7; // Mon=1 .. Sun=7
  const next = Date.UTC(gameDay.getUTCFullYear(), gameDay.getUTCMonth(), gameDay.getUTCDate() + 1, 4);
  return { day: iso, weekday, msLeft: next - shifted };
}
function countdown(ms) {
  const m = Math.max(0, Math.ceil(ms / 60000)), hh = Math.floor(m / 60), mm = m % 60;
  return hh ? `${hh}h ${String(mm).padStart(2, "0")}m` : `${mm}m`;
}

/* ---------- transfer link: deflate-raw + base64url in the #fragment ---------- */
const b64url = bytes => {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
const unb64url = str => Uint8Array.from(atob(str.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
const canDeflate = (() => { try { new CompressionStream("deflate-raw"); return true; } catch { return false; } })();
const pipe = async (bytes, stream) => new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(stream)).arrayBuffer());
// Compact form: ids without their prefix, talents flattened; daily check-offs are never included.
function packPlan(p) {
  return {
    v: PLAN_VERSION, s: p.server,
    c: p.characters.map(c => [c.id.slice(10), c.level, c.talents.flat()]),
    w: p.weapons.map(w => w.id.slice(7)),
  };
}
function unpackPlan(o) {
  if (!o || o.v !== PLAN_VERSION) return null;
  return cleanPlan({
    server: o.s,
    characters: (Array.isArray(o.c) ? o.c : []).map(c => ({
      id: c?.[0], level: c?.[1], talents: [0, 2, 4].map(i => [c?.[2]?.[i], c?.[2]?.[i + 1]]),
    })),
    weapons: (Array.isArray(o.w) ? o.w : []).map(id => ({ id })),
  });
}
async function encodeLink(p) {
  const json = new TextEncoder().encode(JSON.stringify(packPlan(p)));
  const tag = canDeflate ? "plan=" : "plan0=";
  const body = canDeflate ? b64url(await pipe(json, new CompressionStream("deflate-raw"))) : b64url(json);
  return `${location.origin}${location.pathname}#${tag}${body}`;
}
async function decodeLink(hash) {
  const m = /^#(plan0?)=([A-Za-z0-9_-]{1,20000})$/.exec(hash);
  if (!m) return null;
  let bytes = unb64url(m[2]);
  if (m[1] === "plan") bytes = await pipe(bytes, new DecompressionStream("deflate-raw"));
  if (bytes.length > 200000) return null;
  return unpackPlan(JSON.parse(new TextDecoder().decode(bytes)));
}

/* ---------- Safari / WebKit (every iOS and iPadOS browser is WebKit underneath) ---------- */
function isWebKitWithEviction() {
  const ua = navigator.userAgent;
  const iOS = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const safari = /AppleWebKit/.test(ua) && /Safari/.test(ua) && !/Chrome|Chromium|CriOS|FxiOS|EdgiOS|Edg\/|OPR|Android/.test(ua);
  // A Home Screen web app isn't subject to the 7-day limit, so it doesn't need the tip.
  const standalone = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
  return (iOS || safari) && !standalone;
}

/* ---------- the planner ---------- */
const root = $("#plannerApp");
if (root) start();

async function start() {
  let data = null, plan = null, daily = null, meta = {}, loaded = false, clockTimer = 0;
  const statusLine = h("p", { class: "pl-status", role: "status" });

  /* --- load game data and the saved plan; nothing is ever saved before this finishes --- */
  root.replaceChildren(h("p", { class: "placeholder", text: "Loading the planner…" }));
  try {
    const [res, savedPlan, savedDaily, savedMeta] = await Promise.all([
      fetch("/api/planner"), DB.get("plan"), DB.get("daily"), DB.get("meta"),
    ]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
    plan = cleanPlan(savedPlan) || emptyPlan();
    daily = savedDaily && typeof savedDaily === "object" ? savedDaily : { day: "", done: {} };
    meta = savedMeta && typeof savedMeta === "object" ? savedMeta : {};
    loaded = true;
  } catch (err) {
    root.replaceChildren(h("p", { class: "placeholder", text: "The planner's game data didn't load. Your saved plan is untouched; try again in a moment." }));
    return;
  }
  const chars = new Map(data.characters.map(c => [c.id, c]));
  const weapons = new Map(data.weapons.map(w => [w.id, w]));

  /* --- saving --- */
  // A save that would shrink the plan keeps the previous one as "plan-prev", so even a bad
  // write (the empty-state-overwrites-everything bug) can be undone.
  // The in-memory plan changes at once; writes run one at a time, in order.
  let writes = Promise.resolve(true);
  function savePlan(next, opts) {
    if (!loaded) return Promise.resolve(false);
    plan = next;
    return (writes = writes.then(() => writePlan(next, opts)));
  }
  async function writePlan(next, { userShrink = false } = {}) {
    const stored = cleanPlan(await DB.get("plan"));
    if (stored && planSize(next) < planSize(stored)) {
      if (!userShrink) { // never silently replace a bigger plan (e.g. one saved from another tab)
        flash("A bigger plan is saved on this device, maybe from another tab. Reload to see it; nothing was overwritten.");
        return false;
      }
      await DB.set("plan-prev", stored);
    }
    const ok = await DB.set("plan", next);
    if (ok && !meta.persistAsked && navigator.storage?.persist) {
      meta.persistAsked = true;
      meta.persisted = await navigator.storage.persist().catch(() => false);
      await DB.set("meta", meta);
    }
    if (!ok) flash("Couldn't save on this device (storage may be full or blocked). Download a backup to keep your plan.");
    return ok;
  }
  const saveDaily = () => DB.set("daily", daily);
  const saveMeta = () => DB.set("meta", meta);
  function flash(text, action) {
    statusLine.replaceChildren(text);
    if (action) statusLine.append(" ", h("button", { type: "button", class: "pl-link", text: action.label, onclick: action.run }));
  }

  /* --- layout --- */
  const today = h("div", { class: "pl-today panel" });
  const list = h("ul", { class: "pl-list", "aria-label": "Planned characters and weapons" });
  const results = h("ul", { class: "pl-results", id: "plResults", role: "listbox", "aria-label": "Search results" });
  const search = h("input", {
    id: "plSearch", type: "search", autocomplete: "off", maxlength: "40",
    placeholder: "Add a character or weapon", role: "combobox", "aria-controls": "plResults",
    "aria-expanded": "false", "aria-autocomplete": "list",
    oninput: () => showResults(), onkeydown: onSearchKey,
  });
  const backedUp = h("span", { class: "pl-backed" });
  const fileInput = h("input", { type: "file", accept: "application/json,.json", class: "sr", id: "plFile", tabindex: "-1", onchange: onFile });
  const linkOut = h("input", { class: "pl-linkout", readonly: true, hidden: true, "aria-label": "Transfer link" });

  const setup = h("div", { class: "pl-setup panel" },
    h("div", { class: "pad" },
      h("h3", { text: "My plan" }),
      h("p", { class: "pl-sub", text: "Set this up once: who you're building and the talent levels you're aiming for." }),
      h("div", { class: "pl-search" }, h("label", { class: "sr", for: "plSearch", text: "Add a character or weapon" }), search, results),
      list,
    ),
  );
  const backup = h("div", { class: "pl-backup panel" },
    h("div", { class: "pad" },
      h("h3", { text: "Backup and transfer" }),
      h("p", { class: "pl-sub", text: "A backup file is the only copy that survives clearing your browser." }),
      h("div", { class: "pl-actions" },
        h("button", { type: "button", class: "pl-btn primary", text: "Download backup", onclick: downloadBackup }),
        h("button", { type: "button", class: "pl-btn", text: "Import backup", onclick: () => fileInput.click() }),
        h("button", { type: "button", class: "pl-btn", text: "Copy transfer link", onclick: copyLink }),
        fileInput,
      ),
      linkOut,
      backedUp,
      statusLine,
    ),
  );
  const note = h("p", { class: "pl-privacy", text: "Your plan is saved on this device only. No account, no cookies, nothing sent to our server." });
  const tip = safariTip();
  root.replaceChildren(
    h("div", { class: "pl-grid" }, today, h("div", { class: "pl-side" }, setup, backup)),
    h("div", { class: "pl-foot" }, note, tip),
  );

  /* --- today --- */
  function needsBooks(p) { return p.talents.some(([now, goal]) => goal > now); }
  function renderToday() {
    const clock = serverClock(plan.server);
    if (daily.day !== clock.day) { daily = { day: clock.day, done: {} }; if (planSize(plan)) saveDaily(); }
    const sunday = clock.weekday === 7;
    const open = s => sunday || s.days.includes(clock.weekday);

    const serverSel = h("select", { id: "plServer", onchange: e => { plan = { ...plan, server: e.target.value }; savePlan(plan); renderToday(); } },
      Object.entries(SERVERS).map(([k, [name, off]]) => h("option", { value: k, selected: k === plan.server, text: `${name} (UTC${off >= 0 ? "+" : "−"}${Math.abs(off)})` })));
    const left = h("b", { class: "pl-left", text: countdown(clock.msLeft) });
    clearInterval(clockTimer);
    clockTimer = setInterval(() => {
      const c = serverClock(plan.server);
      if (c.day !== daily.day) renderToday(); else left.textContent = countdown(c.msLeft);
    }, 20000);

    // Books: group the planned characters by the series they still need
    const bookGroups = new Map(), weaponGroups = new Map(), done = [];
    for (const p of plan.characters) {
      const c = chars.get(p.id);
      if (!c) continue;
      if (!needsBooks(p)) { done.push(c); continue; }
      for (const key of c.books) (bookGroups.get(key) || bookGroups.set(key, []).get(key)).push(c);
    }
    for (const p of plan.weapons) {
      const w = weapons.get(p.id);
      if (w) (weaponGroups.get(w.material) || weaponGroups.set(w.material, []).get(w.material)).push(w);
    }
    const farm = [], later = [];
    for (const [key, who] of bookGroups) {
      const s = data.books[key];
      if (s) (open(s) ? farm : later).push({ key: "book:" + key, kind: "Talent books", s, who });
    }
    for (const [key, who] of weaponGroups) {
      const s = data.weapon_materials[key];
      if (s) (open(s) ? farm : later).push({ key: "weap:" + key, kind: "Weapon ascension", s, who });
    }
    later.sort((a, b) => a.s.days[0] - b.s.days[0]);

    const checks = [
      { key: "commissions", label: "Daily commissions" },
      { key: "resin", label: "Spend Original Resin" },
      ...farm.map(f => ({ key: f.key, label: `${f.s.name}: ${f.s.domain}` })),
    ];
    const head = h("div", { class: "pl-head" },
      h("div", {},
        h("span", { class: "pl-kicker", text: "Today on your server" }),
        h("h3", { class: "pl-day", text: DAY_NAMES[clock.weekday] }),
      ),
      h("div", { class: "pl-clock" },
        h("label", { for: "plServer", text: "Server" }), serverSel,
        h("span", { class: "pl-reset" }, "Daily reset in ", left),
      ),
    );
    const body = [];
    if (sunday) body.push(h("p", { class: "pl-sunday", text: "Sunday: every domain is open, so farm anything." }));
    if (!planSize(plan)) {
      body.push(h("p", { class: "placeholder pl-empty", text: "Add the characters you're building, and this shows which of their domains are open today." }));
    } else if (!farm.length) {
      body.push(h("p", { class: "placeholder pl-empty", text: bookGroups.size || weaponGroups.size ? "None of your domains are open today. Spend resin on artifacts, bosses or ley lines." : "Every talent goal in your plan is reached." }));
    }
    if (farm.length) body.push(h("ul", { class: "pl-farm" }, farm.map(card)));
    body.push(h("fieldset", { class: "pl-checks" },
      h("legend", { text: "Today's check-offs" }),
      checks.map(c => {
        const id = "plc-" + c.key.replace(/[^a-z0-9]/gi, "-");
        return h("label", { class: "pl-check", for: id },
          h("input", { type: "checkbox", id, checked: !!daily.done[c.key], onchange: e => { daily.done[c.key] = e.target.checked; saveDaily(); } }),
          h("span", { text: c.label }));
      }),
      h("p", { class: "pl-hint", text: "Check-offs clear at the daily reset." }),
    ));
    if (later.length) body.push(h("div", { class: "pl-later" },
      h("h4", { text: "Other days" }),
      h("ul", {}, later.map(f => h("li", {},
        h("span", { class: "pl-days", text: f.s.days.map(d => DAYS[d]).join(" · ") }),
        h("span", { text: `${f.s.name} ${f.kind === "Talent books" ? "books" : ""}`.trim() }),
        h("span", { class: "pl-who", text: f.who.map(x => x.name).join(", ") }),
      ))),
    ));
    if (done.length) body.push(h("p", { class: "pl-hint", text: `Talent goals reached: ${done.map(c => c.name).join(", ")}.` }));
    today.replaceChildren(h("div", { class: "pad" }, head, ...body));
  }
  function card(f) {
    return h("li", { class: "pl-card" },
      h("span", { class: "pl-kind", text: f.kind }),
      h("b", { class: "pl-series", text: f.s.name }),
      h("span", { class: "pl-domain", text: `${f.kind === "Talent books" ? "Domain of Mastery" : "Domain of Forgery"}: ${f.s.domain}${f.s.region ? ` · ${f.s.region}` : ""}` }),
      h("span", { class: "pl-items", text: f.s.items.join(" · ") }),
      h("div", { class: "pl-chips" }, f.who.map(x => chip(x))),
    );
  }
  function chip(x) {
    const dot = h("i", { "aria-hidden": "true" });
    if (x.element) dot.style.background = ELEMENT[x.element] || "var(--leaf)";
    return h("span", { class: "pl-chip" + (x.element ? "" : " weapon") }, dot, x.name);
  }

  /* --- my plan --- */
  function renderList() {
    list.replaceChildren(
      ...plan.characters.map((p, i) => charRow(p, i)),
      ...plan.weapons.map((p, i) => weaponRow(p, i)),
    );
    if (!planSize(plan)) list.append(h("li", { class: "placeholder pl-none", text: "Nothing planned yet." }));
  }
  function costTable(c) { return c.talent_costs || data.talent_costs; }
  function needsText(p, c) {
    const table = costTable(c), sum = [0, 0, 0, 0, 0];
    for (const [now, goal] of p.talents) for (let lvl = now + 1; lvl <= goal; lvl++) table[lvl - 2]?.forEach((n, i) => (sum[i] += n));
    if (!sum.some(Boolean)) return "Talent goals reached.";
    const series = c.books.length === 1 ? data.books[c.books[0]] : null;
    const names = series ? series.items : ["2★ books", "3★ books", "4★ books"];
    const parts = sum.slice(0, 3).map((n, i) => n && `${n} ${names[i]}`).filter(Boolean);
    if (sum[3]) parts.push(`${sum[3]} ${c.weekly || "weekly boss drops"}`);
    if (sum[4]) parts.push(`${sum[4]} Crown${sum[4] > 1 ? "s" : ""} of Insight`);
    return "Still needs " + parts.join(", ") + ".";
  }
  function numberInput(id, value, min, label, onchange) {
    return h("input", { id, type: "number", inputmode: "numeric", min: String(min), max: label === "level" ? "100" : "10", value: String(value), onchange });
  }
  function charRow(p, idx) {
    const c = chars.get(p.id);
    if (!c) return h("li", { class: "pl-row muted", text: `${p.id.slice(10)} (not in the current game data; kept in your plan)` });
    const need = h("p", { class: "pl-need", "aria-live": "polite", text: needsText(p, c) });
    const base = `pl-${idx}`;
    const update = () => { need.textContent = needsText(p, c); savePlan(plan); renderToday(); };
    const talentRows = p.talents.map((t, i) => {
      const goalIn = numberInput(`${base}-g${i}`, t[1], 1, "talent", () => {
        t[1] = clamp(goalIn.value, t[0], 10, t[0]); goalIn.value = t[1]; update();
      });
      const nowIn = numberInput(`${base}-n${i}`, t[0], 1, "talent", () => {
        t[0] = clamp(nowIn.value, 1, 10, 1); if (t[1] < t[0]) t[1] = t[0];
        nowIn.value = t[0]; goalIn.value = t[1]; update();
      });
      return h("div", { class: "pl-talent" },
        h("span", { class: "pl-tname", text: TALENTS[i] }),
        h("label", { class: "sr", for: nowIn.id, text: `${c.name} ${TALENTS[i]} now` }), nowIn,
        h("span", { class: "pl-arrow", "aria-hidden": "true", text: "→" }),
        h("label", { class: "sr", for: goalIn.id, text: `${c.name} ${TALENTS[i]} goal` }), goalIn,
      );
    });
    const dot = h("i", { class: "pl-dot", "aria-hidden": "true" });
    dot.style.background = ELEMENT[c.element] || "var(--leaf)";
    return h("li", { class: "pl-row" },
      h("div", { class: "pl-rowhead" },
        dot, h("b", { text: c.name }),
        h("span", { class: "pl-meta", text: `${c.rarity}★ ${c.weapon_type}` }),
        h("label", { class: "pl-lvl", for: `${base}-lvl` }, "Goal level",
          numberInput(`${base}-lvl`, p.level, 1, "level", e => { p.level = clamp(e.target.value, 1, 100, 90); e.target.value = p.level; savePlan(plan); })),
        h("button", { type: "button", class: "pl-x", "aria-label": `Remove ${c.name}`, text: "×", onclick: () => remove("characters", idx, c.name) }),
      ),
      h("div", { class: "pl-talents" }, talentRows),
      need,
    );
  }
  function weaponRow(p, idx) {
    const w = weapons.get(p.id);
    if (!w) return h("li", { class: "pl-row muted", text: `${p.id.slice(7)} (not in the current game data; kept in your plan)` });
    const s = data.weapon_materials[w.material];
    return h("li", { class: "pl-row" },
      h("div", { class: "pl-rowhead" },
        h("i", { class: "pl-dot weapon", "aria-hidden": "true" }), h("b", { text: w.name }),
        h("span", { class: "pl-meta", text: `${w.rarity}★ ${w.weapon_type}` }),
        h("button", { type: "button", class: "pl-x", "aria-label": `Remove ${w.name}`, text: "×", onclick: () => remove("weapons", idx, w.name) }),
      ),
      s && h("p", { class: "pl-need", text: `${s.items[0]} series · ${s.days.map(d => DAYS[d]).join(" & ")} and Sunday` }),
    );
  }
  async function remove(kind, idx, name) {
    const next = { ...plan, [kind]: plan[kind].filter((_, i) => i !== idx) };
    if (await savePlan(next, { userShrink: true })) flash(`Removed ${name}.`, { label: "Undo", run: undo });
    renderList(); renderToday();
  }
  async function undo() {
    const prev = cleanPlan(await DB.get("plan-prev"));
    if (prev && await savePlan(prev, { userShrink: true })) flash("Restored.");
    renderList(); renderToday();
  }
  async function add(kind, id) {
    if (plan[kind].some(x => x.id === id) || planSize(plan) >= MAX_ITEMS) return;
    const entry = kind === "characters" ? { id, level: 90, talents: [[1, 8], [1, 8], [1, 8]] } : { id };
    search.value = ""; showResults(); // before the await, so typing the next name isn't wiped
    await savePlan({ ...plan, [kind]: [...plan[kind], entry] });
    renderList(); renderToday();
    flash(`Added ${(chars.get(id) || weapons.get(id)).name}.`);
  }

  /* --- search (a small combobox) --- */
  let active = -1;
  function showResults() {
    const q = search.value.trim().toLowerCase();
    active = -1;
    if (!q) { results.replaceChildren(); search.setAttribute("aria-expanded", "false"); search.removeAttribute("aria-activedescendant"); return; }
    const hits = [
      ...data.characters.filter(c => c.name.toLowerCase().includes(q)).map(c => ["characters", c]),
      ...data.weapons.filter(w => w.name.toLowerCase().includes(q)).map(w => ["weapons", w]),
    ].slice(0, 8);
    results.replaceChildren(...hits.map(([kind, x], i) => {
      const have = plan[kind].some(p => p.id === x.id);
      return h("li", { id: `plOpt${i}`, role: "option", class: "pl-opt", "aria-selected": "false", "aria-disabled": have ? "true" : null, onclick: () => !have && add(kind, x.id), onmousedown: e => e.preventDefault() },
        chip(kind === "characters" ? x : { name: x.name }),
        h("span", { class: "pl-meta", text: have ? "in your plan" : kind === "characters" ? `${x.rarity}★ ${x.element}` : `${x.rarity}★ ${x.weapon_type}` }));
    }));
    if (!hits.length) results.append(h("li", { class: "pl-opt none", text: "No released character or weapon matches." }));
    search.setAttribute("aria-expanded", String(hits.length > 0));
  }
  function onSearchKey(e) {
    const opts = [...results.querySelectorAll('[role="option"]')];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!opts.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.setAttribute("aria-selected", String(i === active)));
      search.setAttribute("aria-activedescendant", opts[active].id);
      opts[active].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      (opts[active] || (opts.length === 1 ? opts[0] : null))?.click();
    } else if (e.key === "Escape") {
      search.value = ""; showResults();
    }
  }

  /* --- backup file --- */
  function renderBackedUp() {
    if (!meta.lastBackup) { backedUp.textContent = planSize(plan) ? "Never backed up." : ""; backedUp.classList.toggle("stale", planSize(plan) > 0); return; }
    const days = Math.floor((Date.now() - meta.lastBackup) / 864e5);
    backedUp.textContent = `Last backed up ${days < 1 ? "today" : days === 1 ? "yesterday" : `${days} days ago`}.`;
    backedUp.classList.toggle("stale", days >= 14);
  }
  async function downloadBackup() {
    const file = { app: "irminsul-planner", version: PLAN_VERSION, exported_at: new Date().toISOString(), plan, daily };
    const url = URL.createObjectURL(new Blob([JSON.stringify(file, null, 2)], { type: "application/json" }));
    const a = h("a", { href: url, download: `irminsul-plan-${new Date().toISOString().slice(0, 10)}.json`, hidden: true });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    meta.lastBackup = Date.now(); await saveMeta(); renderBackedUp();
    flash("Backup downloaded. Keep the file somewhere safe, like cloud storage.");
  }
  async function onFile() {
    const f = fileInput.files?.[0];
    fileInput.value = "";
    if (!f) return;
    try {
      if (f.size > 1e6) throw new Error("too big");
      const raw = JSON.parse(await f.text());
      if (raw?.app !== "irminsul-planner" || typeof raw.version !== "number" || raw.version > PLAN_VERSION) throw new Error("not ours");
      const incoming = cleanPlan(raw.plan);
      if (!incoming) throw new Error("no plan");
      if (await confirmReplace(incoming, "backup file")) {
        if (raw.daily?.day === serverClock(incoming.server).day && raw.daily.done && typeof raw.daily.done === "object") {
          daily = { day: raw.daily.day, done: Object.fromEntries(Object.entries(raw.daily.done).filter(([k, v]) => typeof k === "string" && k.length < 80 && v === true).slice(0, 100)) };
          saveDaily();
        }
      }
    } catch {
      flash("That file isn't an Irminsul planner backup.");
    }
  }

  /* --- transfer link --- */
  async function copyLink() {
    if (!planSize(plan)) { flash("Add something to your plan first."); return; }
    const url = await encodeLink(plan);
    try { await navigator.clipboard.writeText(url); flash("Transfer link copied. Open it on your other device to bring this plan over (daily check-offs stay here)."); linkOut.hidden = true; }
    catch { linkOut.value = url; linkOut.hidden = false; linkOut.select(); flash("Copy the link above and open it on your other device."); }
  }
  async function importFromHash() {
    if (!/^#plan0?=/.test(location.hash)) return;
    let incoming = null;
    try { incoming = await decodeLink(location.hash); } catch {}
    history.replaceState(null, "", location.pathname + location.search); // the plan leaves the address bar
    if (!incoming) { flash("That transfer link is damaged or from a newer version, so nothing was imported."); return; }
    await confirmReplace(incoming, "transfer link", true);
  }

  /* --- confirm before replacing, and never let a smaller plan replace a bigger one silently --- */
  function confirmReplace(incoming, source, always = false) {
    const cur = planSize(plan), inc = planSize(incoming);
    if (!always && cur === 0) return apply();
    return new Promise(resolve => {
      const shrink = inc < cur;
      const dlg = h("dialog", { class: "pl-dialog", "aria-labelledby": "plDlgTitle" },
        h("h3", { id: "plDlgTitle", text: `Import this ${source}?` }),
        h("p", { text: `It holds ${describe(incoming)}.` }),
        cur ? h("p", { class: shrink ? "warn" : "", text: `It will replace your current plan of ${describe(plan)} on this device.${shrink ? " That's fewer than you have now. Download a backup first if you might want it back." : ""}` }) : null,
        h("div", { class: "pl-actions" },
          shrink ? h("button", { type: "button", class: "pl-btn", text: "Download current backup", onclick: downloadBackup }) : null,
          h("button", { type: "button", class: "pl-btn", text: "Keep my plan", value: "no", onclick: () => dlg.close("no") }),
          h("button", { type: "button", class: "pl-btn primary", text: "Replace my plan", value: "yes", onclick: () => dlg.close("yes") }),
        ),
      );
      dlg.addEventListener("close", async () => {
        dlg.remove();
        resolve(dlg.returnValue === "yes" ? await apply() : (flash("Kept your current plan."), false));
      });
      document.body.append(dlg);
      dlg.showModal();
    });
    async function apply() {
      const had = planSize(plan) > 0;
      if (had) await DB.set("plan-prev", plan); // so the import can be undone
      const ok = await savePlan(incoming, { userShrink: true });
      renderList(); renderToday(); renderBackedUp();
      if (ok) flash(`Imported ${describe(incoming)}.`, had ? { label: "Undo", run: undo } : null);
      else flash("Couldn't save the imported plan on this device.");
      root.closest("section")?.scrollIntoView({ block: "start" });
      return ok;
    }
  }

  /* --- Safari tip: small, dismissible, remembered --- */
  function safariTip() {
    if (!isWebKitWithEviction() || local.get("irminsul-safari-tip") === "dismissed") return null;
    const el = h("p", { class: "pl-tip" },
      h("span", { text: "Safari clears site data after 7 days without a visit. Download a backup, or add Irminsul to your Home Screen to keep your plan." }),
      h("button", { type: "button", class: "pl-x", "aria-label": "Dismiss this tip", text: "×", onclick: () => { local.set("irminsul-safari-tip", "dismissed"); el.remove(); } }),
    );
    return el;
  }

  renderToday(); renderList(); renderBackedUp();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) renderToday(); });
  addEventListener("hashchange", importFromHash);
  importFromHash();
}
