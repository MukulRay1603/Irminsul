const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const ELEMENT = { Pyro: "#F2774E", Hydro: "#4CC2F1", Anemo: "#72E2C2", Electro: "#B88CFF", Dendro: "#A5D64B", Cryo: "#9FE3F5", Geo: "#F2C14E" };
const ROUTES = {
  exact: ["From game data", ""], announced: ["Official announcement only", "announced"],
  rag: ["Written from sources", ""], refuse_leak: ["Leak filter", "guard"],
  refuse_injection: ["Guardrail", "guard"], refuse_offtopic: ["Genshin only", "guard"],
  busy: ["Busy", "busy"], no_llm: ["Needs an AI key", "busy"], rag_empty: ["No sources found", "busy"],
  no_allowance: ["AI answers used up for now", "busy"],
};
const TIERS = { official: "Official", rayy_verified: "Team-verified", kqm: "KQM", community: "Community" };

/* ---------- Light / dark ---------- */
const modeBtn = $("#modeBtn");
function setMode(m) {
  document.documentElement.dataset.mode = m;
  modeBtn.setAttribute("aria-label", m === "dark" ? "Switch to light mode" : "Switch to dark mode");
  modeBtn.innerHTML = m === "dark"
    ? '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'
    : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  store.set("irminsul-mode", m);
  tree.recolor();
}
modeBtn.onclick = () => setMode(document.documentElement.dataset.mode === "dark" ? "light" : "dark");

/* ---------- Top bar turns solid past the hero ---------- */
const bar = $("#bar");
new IntersectionObserver(([e]) => bar.classList.toggle("solid", !e.isIntersecting), { threshold: .12 }).observe($(".hero-inner"));

/* ---------- The tree: grows once, then breathes (cheap after the first two seconds) ---------- */
// Low-power devices (phones, 4-core laptops, data saver) get fewer motes, 30 fps and no glow.
const lowPower = (navigator.deviceMemory || 8) <= 4 || (navigator.hardwareConcurrency || 8) <= 4 ||
  matchMedia("(max-width: 640px)").matches || navigator.connection?.saveData === true;
const tree = (() => {
  const cv = $("#tree"), ctx = cv.getContext("2d");
  let W = 0, H = 0, dpr = 1, branches = [], tips = [], motes = [], colors = {};
  let baked = null, glow = null, growEnd = 0, raf = 0, onScreen = true, last = 0;
  const t0 = performance.now();
  const rnd = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const ease = t => t < 0 ? 0 : t > 1 ? 1 : 1 - Math.pow(1 - t, 3);
  function sprite(color) {
    const c = document.createElement("canvas"); c.width = c.height = 32;
    const g = c.getContext("2d"), rg = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    rg.addColorStop(0, color); rg.addColorStop(1, "transparent"); g.fillStyle = rg; g.fillRect(0, 0, 32, 32);
    return c;
  }
  function recolor() {
    const cs = getComputedStyle(document.documentElement);
    colors = { leaf: cs.getPropertyValue("--leaf").trim(), gold: cs.getPropertyValue("--gold").trim(), sap: cs.getPropertyValue("--sap").trim() };
    glow = sprite(colors.sap); baked = null;
    if (W && !raf) frame(performance.now());
  }
  function build() {
    dpr = Math.min(devicePixelRatio || 1, lowPower ? 1 : 2);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    branches = []; tips = []; baked = null;
    const r = rnd(7), scale = Math.min(W, H * 1.2), maxDepth = lowPower ? 7 : 8;
    (function grow(x, y, ang, len, w, depth, start) {
      const x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len, bend = (r() - .5) * len * .5;
      branches.push({ x, y, x2, y2, cx: (x + x2) / 2 + Math.cos(ang + Math.PI / 2) * bend, cy: (y + y2) / 2 + Math.sin(ang + Math.PI / 2) * bend, w, depth, start, dur: .18 + depth * .02 });
      if (depth >= maxDepth || len < 6) { tips.push({ x: x2, y: y2, ph: r() * 6.28 }); return; }
      const n = depth < 2 ? 2 : r() < .3 ? 3 : 2;
      for (let i = 0; i < n; i++) {
        const spread = (depth < 2 ? .42 : .55) * (i - (n - 1) / 2) + (r() - .5) * .35;
        grow(x2, y2, ang + spread, len * (.72 + r() * .1), w * .68, depth + 1, start + .14);
      }
    })(W / 2, H + 10, -Math.PI / 2, scale * .2, Math.max(6, scale * .016), 0, 0);
    for (let i = 0; i < 6; i++) {  // roots spread along the bottom
      const dir = i % 2 ? 1 : -1;
      (function root(x, y, a, len, w, d) {
        const x2 = x + Math.cos(a) * len, y2 = y + Math.sin(a) * len;
        branches.push({ x, y, x2, y2, cx: (x + x2) / 2, cy: (y + y2) / 2 + len * .1, w, depth: d + 2, start: .1 + d * .12, dur: .25, root: true });
        if (d < 4) root(x2, y2, a + (r() - .5) * .5, len * .75, w * .65, d + 1);
      })(W / 2 + dir * 10, H - 4, Math.PI * (dir > 0 ? 0 : 1) + (r() - .5) * .2 + .12 * dir, scale * .14, Math.max(3, scale * .01), 0);
    }
    growEnd = Math.max(...branches.map(b => b.start + b.dur));
    motes = Array.from({ length: lowPower ? 26 : Math.round(Math.min(80, W / 16)) }, () => spawn(r, true));
  }
  function spawn(r = Math.random, any = false) {
    return { x: W / 2 + (r() - .5) * W * .9, y: any ? r() * H : H + 10, v: .15 + r() * .45, s: .8 + r() * 2.2, ph: r() * 6.28, gold: r() < .25 };
  }
  function stroke(c, b, p, shadow) {
    const g = c.createLinearGradient(b.x, b.y, b.x2, b.y2);
    g.addColorStop(0, colors.gold); g.addColorStop(1, colors.leaf);
    c.strokeStyle = g; c.globalAlpha = (b.root ? .35 : .55) * (1 - b.depth * .045);
    c.lineWidth = b.w; c.lineCap = "round";
    c.shadowColor = colors.leaf; c.shadowBlur = shadow ? (b.depth > 4 ? 12 : 4) : 0;
    c.beginPath(); c.moveTo(b.x, b.y);
    if (p >= 1) c.quadraticCurveTo(b.cx, b.cy, b.x2, b.y2);
    else {
      const q = 1 - p;
      c.quadraticCurveTo(b.x + (b.cx - b.x) * p, b.y + (b.cy - b.y) * p,
        q * q * b.x + 2 * q * p * b.cx + p * p * b.x2, q * q * b.y + 2 * q * p * b.cy + p * p * b.y2);
    }
    c.stroke();
  }
  function bake() {  // the grown tree never changes: draw it once, then just copy the bitmap
    baked = document.createElement("canvas"); baked.width = W * dpr; baked.height = H * dpr;
    const c = baked.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (const b of branches) stroke(c, b, 1, !lowPower);
  }
  function frame(now) {
    raf = 0;
    if (lowPower && !reduced && now - last < 33) return schedule();
    last = now;
    const t = reduced ? 99 : (now - t0) / 1000;
    ctx.clearRect(0, 0, W, H);
    if (t >= growEnd) {
      if (!baked) bake();
      ctx.globalAlpha = 1; ctx.shadowBlur = 0; ctx.drawImage(baked, 0, 0, W, H);
      if (!lowPower) for (const tip of tips) {
        const pulse = .5 + .5 * Math.sin(t * 1.3 + tip.ph), s = 8 + 8 * pulse;
        ctx.globalAlpha = .2 + .5 * pulse; ctx.drawImage(glow, tip.x - s / 2, tip.y - s / 2, s, s);
      }
    } else for (const b of branches) { const p = ease((t - b.start) / b.dur); if (p > 0) stroke(ctx, b, p, false); }
    ctx.shadowBlur = 0;
    const show = Math.min(1, Math.max(0, t - 1));
    for (const m of motes) {
      if (!reduced) { m.y -= m.v; m.x += Math.sin(t * .6 + m.ph) * .25; if (m.y < -10) Object.assign(m, spawn()); }
      ctx.globalAlpha = show * (.25 + .35 * Math.sin(t * 1.7 + m.ph) ** 2);
      ctx.fillStyle = m.gold ? colors.gold : colors.leaf;
      ctx.beginPath(); ctx.arc(m.x, m.y, m.s, 0, 6.28); ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (!reduced) schedule();
  }
  // Only animate while the hero is on screen and the tab is visible
  function schedule() { if (!raf && onScreen && !document.hidden && !reduced) raf = requestAnimationFrame(frame); }
  new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; schedule(); }).observe(cv);
  document.addEventListener("visibilitychange", schedule);
  let resizeTimer;
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (cv.clientWidth !== W || Math.abs(cv.clientHeight - H) > 120) { build(); if (!raf) frame(performance.now()); } }, 150);
  });
  return { start() { build(); recolor(); }, recolor };  // recolor draws the first frame
})();
setMode(store.get("irminsul-mode") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
tree.start();

/* ---------- Ambient sound: generated live, off until you turn it on ---------- */
const sound = (() => {
  let ac, master, timer;
  function start() {
    ac = ac || new AudioContext();
    master = ac.createGain(); master.gain.value = 0; master.connect(ac.destination);
    const delay = ac.createDelay(); delay.delayTime.value = .42;
    const fb = ac.createGain(); fb.gain.value = .38; delay.connect(fb).connect(delay); delay.connect(master);
    const lp = ac.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 900; lp.Q.value = .4; lp.connect(master); lp.connect(delay);
    const lfo = ac.createOscillator(), lfoAmt = ac.createGain(); lfo.frequency.value = .05; lfoAmt.gain.value = 380;
    lfo.connect(lfoAmt).connect(lp.frequency); lfo.start();
    // A soft D-major pad (D2 A2 F#3 E4), two detuned voices each
    for (const f of [73.42, 110, 185, 329.6]) for (const d of [-4, 4]) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = f < 120 ? "sine" : "triangle"; o.frequency.value = f; o.detune.value = d;
      g.gain.value = f < 120 ? .18 : .06; o.connect(g).connect(lp); o.start();
    }
    master.gain.linearRampToValueAtTime(.11, ac.currentTime + 3);
    // Occasional chimes from a pentatonic scale, like light passing through leaves
    const notes = [587.3, 659.3, 740, 880, 987.8, 1174.7];
    (function chime() {
      const o = ac.createOscillator(), g = ac.createGain(), now = ac.currentTime;
      o.type = "sine"; o.frequency.value = notes[Math.floor(Math.random() * notes.length)];
      g.gain.setValueAtTime(0, now); g.gain.linearRampToValueAtTime(.05, now + .02); g.gain.exponentialRampToValueAtTime(.0001, now + 3.5);
      o.connect(g); g.connect(master); g.connect(delay); o.start(now); o.stop(now + 3.6);
      timer = setTimeout(chime, 3500 + Math.random() * 6000);
    })();
  }
  function stop() {
    clearTimeout(timer);
    if (!master) return;
    const m = master; m.gain.linearRampToValueAtTime(0, ac.currentTime + 1);
    setTimeout(() => m.disconnect(), 1100); master = null;
  }
  return { start, stop };
})();
const soundBtn = $("#soundBtn");
soundBtn.onclick = () => {
  const on = soundBtn.getAttribute("aria-pressed") !== "true";
  soundBtn.setAttribute("aria-pressed", on); on ? sound.start() : sound.stop();
};

/* ---------- AI-answer counter: ticks locally, re-synced from the server after every answer ---------- */
const quotaUI = (() => {
  let q = null, synced = 0, lastCur = null, lastCount = "";
  const hms = s => {
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
    return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };
  // Points that refilled since the last sync, worked out without asking the server
  function level(b, gone) {
    let cur = b.current, next = b.next_in_s - gone;
    while (next <= 0 && cur < b.cap) { cur++; next += b.regen_s; }
    return { cur, next, full: cur >= b.cap };
  }
  function render() {
    if (!q) return;
    const gone = (Date.now() - synced) / 1000, me = level(q.personal, gone), pool = level(q.pool, gone);
    const box = $("#quota"); box.hidden = false;
    box.classList.toggle("empty", me.cur === 0);
    if (lastCur !== null && me.cur !== lastCur) { box.classList.add("tick"); setTimeout(() => box.classList.remove("tick"), 300); }
    lastCur = me.cur;
    const count = `${me.cur}<small> / ${q.personal.cap} AI answers</small>`;
    if (count !== lastCount) { $("#qCount").innerHTML = count; lastCount = count; }
    $("#qTimer").innerHTML = me.full ? "Full" : `+1 in <b>${hms(me.next)}</b>`;
    $("#qGauge").style.transform = `scaleX(${me.cur / q.personal.cap})`;
    $("#qPool").innerHTML = pool.cur > 0 ? `Shared pool <b>${pool.cur}</b> ready` : `Shared pool refills in <b>${hms(pool.next)}</b>`;
  }
  function set(quota) { if (quota?.personal) { q = quota; synced = Date.now(); render(); } }
  function sync() { fetch("/quota").then(r => r.ok ? r.json() : null).then(set).catch(() => {}); }
  setInterval(() => { if (!document.hidden) render(); }, 1000);
  sync();
  // Popover fallback for browsers without the Popover API
  if (!HTMLElement.prototype.hasOwnProperty("popover")) {
    const pop = $("#qInfo"); pop.hidden = true;
    pop.style.cssText = "position:fixed;inset:auto 16px 16px;margin:auto;z-index:50";
    document.querySelectorAll('[popovertarget="qInfo"]').forEach(b => b.onclick = () => pop.hidden = !pop.hidden);
  }
  return { set, sync };
})();

/* ---------- Live data facts ---------- */
// A free host sleeps when idle: if it takes a moment to answer, say so calmly in the hero
const waking = setTimeout(() => $("#waking").textContent = "Waking up the tree… first load can take a few seconds.", 2000);
const awake = () => { clearTimeout(waking); $("#waking").textContent = ""; };
fetch("/health").then(r => { awake(); return r.json(); }).then(h => {
  const v = h.corpus.game_version || "", live = v.length >= 2 ? `${v[0]}.${v[1]}` : "?";
  const keys = h.llm_providers.filter(p => p.configured).length;
  $("#dataChip").innerHTML = `Game data <b>${esc(live)}</b>` + (keys ? "" : ", AI answers off");
  $("#fVersion").textContent = live; gameVersion = live; $("#fDocs").textContent = (h.corpus.docs || 0).toLocaleString();
  $("#facts").hidden = false;
}).catch(() => { awake(); $("#dataChip").textContent = "Offline"; });

/* ---------- Character gallery ---------- */
let roster = [];
fetch("/api/characters").then(r => r.json()).then(list => {
  roster = list; $("#fChars").textContent = list.length;
  const els = Object.keys(ELEMENT).filter(e => list.some(c => c.element === e));
  const icon = e => list.find(c => c.element === e && c.element_icon)?.element_icon;
  $("#filters").innerHTML = els.map(e => `<button type="button" data-el="${e}" aria-pressed="false" aria-label="${e}" title="${e}">${icon(e) ? `<img src="${esc(icon(e))}" alt="" width="22" height="22">` : `<span class="el-letter">${e[0]}</span>`}</button>`).join("");
  renderGallery();
});
const fold = s => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();  // case and accents don't matter
function renderGallery() {
  const on = $("#filters [aria-pressed=true]")?.dataset.el, term = fold($("#gallerySearch").value);
  const shown = roster.filter(c => (!on || c.element === on) && (!term || fold(c.name).includes(term)));
  $("#galleryEmpty").textContent = roster.length && !shown.length ? "No released character matches that." : "";
  $("#gallery").innerHTML = shown.map(c =>
    `<button type="button" class="ccard" data-id="${esc(c.id)}" data-r="${c.rarity}" data-el="${esc(c.element)}">
       ${c.card ? `<img src="${esc(c.card)}" alt="" loading="lazy" decoding="async" width="150" height="225">` : ""}
       <span class="meta"><b>${esc(c.name)}</b><span>${"★".repeat(c.rarity)} ${esc(c.element)}</span></span></button>`).join("");
}
$("#gallerySearch").addEventListener("input", renderGallery);
$("#filters").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  const was = b.getAttribute("aria-pressed") === "true";
  $("#filters").querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", "false"));
  b.setAttribute("aria-pressed", String(!was)); renderGallery();
};
// Pointer light + tilt on gallery cards, throttled to one update per frame (mouse only)
let tiltFrame = 0;
$("#gallery").addEventListener("pointermove", e => {
  const card = e.target.closest(".ccard");
  if (!card || tiltFrame || e.pointerType !== "mouse") return;
  tiltFrame = requestAnimationFrame(() => {
    tiltFrame = 0;
    const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    card.style.setProperty("--mx", `${x * 100}%`); card.style.setProperty("--my", `${y * 100}%`);
    card.style.setProperty("--ry", `${(x - .5) * 10}deg`); card.style.setProperty("--rx", `${(.5 - y) * 10}deg`);
  });
});
$("#gallery").onclick = e => {
  const b = e.target.closest(".ccard"); if (!b) return;
  showEntity(b.dataset.id); $("#ask").scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
};

/* ---------- Conversation ---------- */
const md = text => renderMarkdown(text);
function setRoute(el, route) {
  const [label, cls] = ROUTES[route] || [route, ""];
  const r = $(".route", el); r.className = `route ${cls}`; r.lastElementChild.textContent = label;
}
let busy = false, gameVersion = "";
async function ask(q) {
  q = q.trim(); if (!q || busy) return;
  busy = true; document.querySelectorAll(".ask button").forEach(b => b.disabled = true);
  $("#hint")?.remove();
  const thread = $("#thread");
  thread.insertAdjacentHTML("beforeend", `<div class="q">${esc(q)}</div>`);
  const el = document.createElement("div"); el.className = "a";
  el.classList.add("streaming");
  el.innerHTML = `<div class="route"><i></i><span>Searching the branches…</span></div><div class="body typing"></div>`;
  thread.append(el); thread.setAttribute("aria-busy", "true");
  $("#ask").scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
  const body = $(".body", el); let text = "", done = null;
  try {
    const res = await fetch("/ask/stream", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(typeof e.detail === "string" ? e.detail : `Error ${res.status}`); }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done: end } = await reader.read(); if (end) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        const kind = block.match(/^event: (.*)$/m)?.[1], data = JSON.parse(block.match(/^data: (.*)$/m)?.[1] || "{}");
        if (kind === "meta") setRoute(el, data.route);
        if (kind === "delta") { text += data.text; body.innerHTML = md(text); }
        if (kind === "done") done = data;
      }
    }
  } catch (err) { setRoute(el, "busy"); body.innerHTML = `<p>${esc(err.message)}</p>`; }
  body.classList.remove("typing"); el.classList.remove("streaming"); thread.removeAttribute("aria-busy");
  busy = false; document.querySelectorAll(".ask button").forEach(b => b.disabled = false);
  if (!done) return;
  quotaUI.set(done.quota);
  // The server's output guard changed a streamed answer (e.g. removed a link): show its version
  if (done.text) { text = done.text; body.innerHTML = md(text); }
  $(".route", el).outerHTML = answerHeader(done.route, gameVersion, done.citations?.length || 0);
  const cardEl = done.card && renderCard(done.card);
  if (cardEl) { body.replaceChildren(cardEl); body.classList.add("has-card"); }
  const copy = $(".copy", el);
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(normaliseCitations(text).replace(/\s*\[\d+\]/g, "")); copy.textContent = "Copied"; }
    catch { copy.textContent = "Copy failed"; }
    setTimeout(() => copy.textContent = "Copy", 1600);
  };
  if (done.route === "refuse_leak") body.insertAdjacentHTML("beforebegin",
    `<div class="redacted" aria-hidden="true"><span></span><span></span><span></span><div class="stamp"><b>Hidden by the leak filter</b></div></div>`);
  labelCitations(body, done.citations);
  if (done.citations?.length) el.append(sourceRow(done.citations));
  const why = document.createElement("button"); why.type = "button"; why.className = "why"; why.textContent = "Why this answer?";
  why.onclick = () => { renderTrace(done); $("#tracePanel").scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  el.append(why); renderTrace(done);
  window.trust?.decorate(el, done);  // source check marks and the Report button (trust.js)
  // Suggested next questions: picked from game data, free ones marked (they don't use AI answers)
  if (done.follow_ups?.length) {
    const box = document.createElement("div"); box.className = "next";
    box.innerHTML = `<span class="next-label">Ask next</span>` + done.follow_ups.map(f =>
      `<button type="button" data-q="${esc(f.question)}">${esc(f.question)}${f.free ? ` <span class="free" title="Answered from game data: instant, and doesn't use your AI answers">free</span>` : ""}</button>`).join("");
    box.onclick = ev => { const b = ev.target.closest("button[data-q]"); if (b) ask(b.dataset.q); };
    el.append(box);
  }
  const ent = done.trace.entity || done.citations?.map(c => c.doc_id || "").find(d => /^(character|weapon|artifact)\//.test(d))?.split("#")[0];
  if (ent) showEntity(ent);
}
for (const id of ["heroForm", "dockForm"]) $("#" + id).addEventListener("submit", e => {
  e.preventDefault(); const inp = $("input", e.target); ask(inp.value); inp.value = "";
});
$("#prompts").onclick = e => { if (e.target.matches("button")) ask(e.target.textContent); };

function renderTrace(d) {
  queueMicrotask(sizeBars);
  const t = d.trace, p = $("#tracePanel"); p.hidden = false;
  const why = {
    exact: "Answered straight from official game data. No AI model was used.",
    announced: "Officially announced but not released, so only official information is shown.",
    refuse_leak: "The question asks about leaks or unannounced content, so the leak filter stopped it before any search.",
    refuse_injection: "The question tried to change the assistant's instructions, so the guardrail refused it.",
    refuse_offtopic: "The question isn't about Genshin Impact.",
    rag: "Search and re-ranking found the sources, then an AI model wrote the answer citing them.",
    busy: "This needs an AI model, and none is available right now.",
    no_allowance: "Your AI answers refill over time (see the counter). Answers from game data stay free.",
  }[d.route] || "";
  const hits = (t.retrieval || []).slice(0, 6), max = Math.max(...hits.map(h => h.score), 1e-6);
  p.innerHTML = `<div class="pad"><h3>Why this answer</h3><p class="placeholder">${esc((ROUTES[d.route] || [d.route])[0])}. ${why}</p>
    <ul class="list"><li><span>Time</span><span>${esc(t.latency_ms ?? "?")} ms</span></li>
    ${t.provider ? `<li><span>Model</span><span>${esc(t.provider)}, ${esc(t.model)}</span></li>` : ""}
    ${t.tokens ? `<li><span>Tokens</span><span>${esc(t.tokens.prompt)} in, ${esc(t.tokens.completion)} out</span></li>` : ""}
    ${t.cache === "hit" ? `<li><span>Cache</span><span>Answered before</span></li>` : ""}</ul>
    ${hits.length ? `<p class="placeholder searched">Sources searched</p>` + hits.map(h =>
      `<div class="row"><small title="${esc(h.doc_id)}">${esc(h.doc_id)}</small><div class="bar-s" data-w="${Math.max(8, 64 * h.score / max)}"></div></div>`).join("") : ""}</div>`;
}

function sizeBars() {
  document.querySelectorAll("#tracePanel .bar-s[data-w]").forEach(b => b.style.width = `${b.dataset.w}px`);
}

/* ---------- Dossier ---------- */
const KIND = { normal_attack: "Normal Attack", skill: "Elemental Skill", burst: "Elemental Burst", passive: "Passive" };
async function showEntity(id) {
  const r = await fetch(`/api/entity?id=${encodeURIComponent(id)}`); if (!r.ok) return;
  const e = await r.json(), box = $("#dossier");
  if (document.startViewTransition && !reduced && box.querySelector(".art, h3")) {
    await document.startViewTransition(() => paintEntity(e, box)).updateCallbackDone;
  } else paintEntity(e, box);
}
function paintEntity(e, box) {
  box.style.setProperty("--el", ELEMENT[e.element] || "var(--leaf)");
  if (e.kind === "character") {
    const s = e.base_stats, announced = e.release.status === "announced";
    const pct = v => v == null ? "-" : s.bonus_stat === "Elemental Mastery" ? Math.round(v) : (v * 100).toFixed(1) + "%";
    const kit = list => `<ul class="kit">${list.map(x => `<li><details><summary>
        ${x.icon ? `<img class="ico" src="${esc(x.icon)}" alt="">` : `<span class="ico"></span>`}
        <span><span class="kind">${esc(x.level ? "C" + x.level : KIND[x.kind] || x.kind)}</span><span class="nm">${esc(x.name)}</span></span>
      </summary><div class="desc">${esc(x.description)}</div></details></li>`).join("")}</ul>`;
    box.innerHTML = `<div class="art">
        ${e.banner ? `<img class="banner" src="${esc(e.banner)}" alt="">` : ""}
        ${e.splash ? `<img class="splash" src="${esc(e.splash)}" alt="${esc(e.name)} official art">` : e.art ? `<img class="splash icon-only" src="${esc(e.art)}" alt="">` : ""}
        <div class="who">
          ${e.rarity ? `<span class="stars" aria-label="${e.rarity} stars">${"★".repeat(e.rarity)}</span>` : ""}
          <h2>${esc(e.name)}</h2>${e.title ? `<div class="title">${esc(e.title)}</div>` : ""}
          <div class="tags">${e.element ? `<span>${e.element_icon ? `<img src="${esc(e.element_icon)}" alt="">` : ""}${esc(e.element)}</span>` : ""}
            ${e.weapon_type ? `<span>${esc(e.weapon_type)}</span>` : ""}${e.region ? `<span>${esc(e.region)}</span>` : ""}</div>
          ${announced ? `<span class="badge">Announced: official info only</span>` : ""}
        </div></div>
      <div class="pad">
        ${e.summary ? `<p class="summary">${esc(e.summary)}</p>` : ""}
        ${s ? `<div class="stats">
          <div class="stat"><div class="k">Base HP</div><div class="v">${Math.round(s.hp).toLocaleString()}</div></div>
          <div class="stat"><div class="k">Base ATK</div><div class="v">${Math.round(s.atk)}</div></div>
          <div class="stat"><div class="k">Base DEF</div><div class="v">${Math.round(s.defense)}</div></div>
          <div class="stat"><div class="k" title="${esc(s.bonus_stat)}">${esc(s.bonus_stat || "Bonus")}</div><div class="v">${pct(s.bonus_value)}</div></div></div>
          <p class="placeholder level-note">Level ${esc(s.level)}, fully ascended</p>` : ""}
        ${e.talents?.length || e.constellations?.length ? `<div class="tabs" role="tablist">
          <button role="tab" aria-selected="true" data-tab="t">Talents</button>
          <button role="tab" aria-selected="false" data-tab="c">Constellations</button></div>
          <div data-pane="t">${kit(e.talents)}</div><div data-pane="c" hidden>${kit(e.constellations)}</div>` : ""}
      </div>`;
    box.querySelectorAll("[role=tab]").forEach(b => b.onclick = () => {
      box.querySelectorAll("[role=tab]").forEach(x => x.setAttribute("aria-selected", x === b));
      box.querySelectorAll("[data-pane]").forEach(p => p.hidden = p.dataset.pane !== b.dataset.tab);
    });
  } else if (e.kind === "weapon") {
    const sec = e.secondary_value == null ? "-" : e.secondary_stat === "Elemental Mastery" ? Math.round(e.secondary_value) : (e.secondary_value * 100).toFixed(1) + "%";
    box.innerHTML = `<div class="pad"><span class="stars">${"★".repeat(e.rarity)}</span><h3 class="big">${esc(e.name)}</h3>
      <p class="summary">${esc(e.weapon_type)}</p>
      <div class="stats two"><div class="stat"><div class="k">Base ATK</div><div class="v">${esc(e.base_atk ?? "-")}</div></div>
      <div class="stat"><div class="k">${esc(e.secondary_stat || "Secondary")}</div><div class="v">${sec}</div></div></div>
      ${e.passive_name ? `<p class="passive-name"><strong>${esc(e.passive_name)}</strong></p><p class="summary">${esc(e.passive_by_refinement[0] || "")}</p>` : ""}</div>`;
  } else {
    box.innerHTML = `<div class="pad"><h3 class="big">${esc(e.name)}</h3><ul class="kit">${Object.entries(e.bonuses).map(([n, t]) =>
      `<li><details open><summary><span class="ico"></span><span><span class="kind">${n}-piece bonus</span></span></summary><div class="desc">${esc(t)}</div></details></li>`).join("")}</ul></div>`;
  }
  const vp = $("#videoPanel");
  if (e.videos?.length) {
    vp.hidden = false;
    vp.innerHTML = `<div class="pad"><h3>Official videos</h3><div class="videos">${e.videos.slice(0, 4).map(v =>
      `<button type="button" class="video" data-yt="${esc(v.youtube_id)}" aria-label="Play ${esc(v.title)}">
         <img src="https://i.ytimg.com/vi/${esc(v.youtube_id)}/mqdefault.jpg" alt="" loading="lazy"><span>${esc(v.title.split("|")[0].trim())}</span></button>`).join("")}</div></div>`;
    vp.querySelectorAll(".video").forEach(b => b.onclick = () => {
      if (!/^[\w-]{6,20}$/.test(b.dataset.yt)) return;
      b.outerHTML = `<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/${b.dataset.yt}?autoplay=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen title="Official video"></iframe></div>`;
    });
  } else vp.hidden = true;
}

/* ---------- Keyboard: "/" jumps to the question box, Esc leaves it ---------- */
document.addEventListener("keydown", e => {
  const t = e.target, typing = t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
  if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
    // The follow-up box when it's on screen, else the big one in the hero
    const dock = $("#dockQ"), r = dock.getBoundingClientRect(), inView = r.top < innerHeight && r.bottom > 0;
    e.preventDefault(); (inView ? dock : $("#heroQ")).focus();
  } else if (e.key === "Escape" && typing && t.matches("input:not([type=checkbox]):not([type=radio]), textarea")) t.blur();
});

// Art is fetched by the server on first use; if an image turns out to be missing (404), drop it
// so the layout falls back as it does when there is no art at all, instead of a broken icon.
document.addEventListener("error", e => {
  if (e.target instanceof HTMLImageElement && new URL(e.target.src).pathname.startsWith("/art/")) e.target.remove();
}, true);
