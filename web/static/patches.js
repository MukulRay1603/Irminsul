/* Patch notes: what each game version added or changed, from GET /api/patches (official data,
   released content only). "For my characters" filters to the planner's roster, read straight
   from this device's storage (planner.js keeps it there); nothing about it goes to the server.
   No inline styles or handlers: the page runs under a strict CSP. */

(() => {
  const root = document.getElementById("patchesApp");
  if (!root) return;
  const PREF = "irminsul-patches-mine";
  const YT = /^[\w-]{6,20}$/;
  let data = null, selected = null, mine = false, roster = null, loading = null;

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
  const pref = { get() { try { return localStorage.getItem(PREF) === "1"; } catch { return false; } },
                 set(v) { try { localStorage.setItem(PREF, v ? "1" : "0"); } catch {} } };
  // One formatter for every date: building one per call was the page's slowest step on phones
  const DATES = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const COMPACT = new Intl.NumberFormat(undefined, { notation: "compact" });
  const longDate = iso => DATES.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
  const httpUrl = u => /^https:\/\//.test(u || "") ? u : null;

  /* ---------- the planner roster, read-only from this device ---------- */
  // Same store as planner.js: IndexedDB "irminsul" / "kv" / "plan", localStorage as fallback.
  function readPlan() {
    const fromLocal = () => { try { return JSON.parse(localStorage.getItem("irminsul-planner-plan") || "null"); } catch { return null; } };
    return new Promise(resolve => {
      if (!("indexedDB" in self)) return resolve(fromLocal());
      const req = indexedDB.open("irminsul", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");  // as planner.js, so it never breaks it
      req.onerror = req.onblocked = () => resolve(fromLocal());
      req.onsuccess = () => {
        try {
          const get = req.result.transaction("kv", "readonly").objectStore("kv").get("plan");
          get.onsuccess = () => { req.result.close(); resolve(get.result ?? fromLocal()); };
          get.onerror = () => { req.result.close(); resolve(fromLocal()); };
        } catch { resolve(fromLocal()); }
      };
    });
  }
  async function loadRoster() {
    const plan = await readPlan();
    const ids = new Set();
    for (const c of Array.isArray(plan?.characters) ? plan.characters : []) if (typeof c?.id === "string") ids.add(c.id);
    for (const w of Array.isArray(plan?.weapons) ? plan.weapons : []) if (typeof w?.id === "string") ids.add(w.id);
    roster = ids;
  }

  /* ---------- rendering ---------- */
  function openEntity(id) {
    if (typeof showEntity !== "function") return;  // app.js dossier
    showEntity(id);
    document.getElementById("ask")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
  function source(url, label = "Source") {
    const href = httpUrl(url);
    return href ? h("a", { class: "pn-src", href, target: "_blank", rel: "noopener noreferrer", text: label }) : null;
  }
  function entityCard(x) {
    const meta = [x.rarity ? `${x.rarity}★` : "", x.element, x.weapon_type].filter(Boolean).join(" · ");
    return h("li", { class: "pn-item", "data-el": x.element || "", "data-kind": x.kind },
      h("button", { type: "button", class: "pn-open", onclick: () => openEntity(x.id) },
        h("i", { "aria-hidden": "true" }),
        h("span", { class: "pn-name", text: x.name }),
        h("span", { class: "pn-meta", text: meta })),
      source(x.source));
  }
  function change(c) {
    const fields = c.fields.length ? c.fields : [{ field: "Description text", before: "", after: "" }];
    return h("li", { class: "pn-change", "data-el": c.element || "" },
      h("div", { class: "pn-change-head" },
        h("button", { type: "button", class: "pn-open", onclick: () => openEntity(c.id) },
          h("i", { "aria-hidden": "true" }), h("span", { class: "pn-name", text: c.name })),
        h("span", { class: "pn-meta", text: `Updated ${c.dates.map(longDate).join(", ")}` }),
        source(c.source)),
      h("dl", { class: "pn-fields" }, fields.map(f => {
        const short = f.before.length + f.after.length < 90 && !f.before.includes("\n") && !f.after.includes("\n");
        if (!f.before && !f.after) return h("div", { class: "pn-field" }, h("dt", { text: f.field }), h("dd", { text: "Changed in the official data." }));
        if (short) return h("div", { class: "pn-field" }, h("dt", { text: f.field }),
          h("dd", {}, h("del", { text: f.before || "—" }), h("span", { class: "pn-arrow", "aria-label": "changed to", text: "→" }), h("ins", { text: f.after || "—" })));
        return h("div", { class: "pn-field long" }, h("dt", { text: f.field }),
          h("dd", {}, h("details", {}, h("summary", { text: "Show before and after" }),
            h("div", { class: "pn-ba" },
              h("div", {}, h("span", { class: "pn-ba-k", text: "Before" }), h("p", { text: f.before || "—" })),
              h("div", {}, h("span", { class: "pn-ba-k", text: "After" }), h("p", { text: f.after || "—" }))))));
      })));
  }
  function video(v) {
    if (!YT.test(v.youtube_id || "")) {
      const href = httpUrl(v.url);
      return href ? h("li", {}, h("a", { class: "pn-video plain", href, target: "_blank", rel: "noopener noreferrer", text: v.title })) : null;
    }
    const title = v.title.split("|")[0].trim();
    const btn = h("button", { type: "button", class: "pn-video", "aria-label": `Play ${title}` },
      h("img", { src: `https://i.ytimg.com/vi/${v.youtube_id}/mqdefault.jpg`, alt: "", loading: "lazy", width: "320", height: "180" }),
      h("span", { text: title }));
    btn.addEventListener("click", () => btn.replaceWith(h("div", { class: "pn-video playing" },
      h("iframe", { src: `https://www.youtube-nocookie.com/embed/${v.youtube_id}?autoplay=1`, allow: "autoplay; encrypted-media; picture-in-picture", allowfullscreen: true, title: title }))));
    return h("li", {}, btn);
  }
  // Each group folds behind its heading so a big patch doesn't push the page down. New
  // characters and official videos start open; the rest show their count until opened.
  // A closed group's items are built the first time it opens: most are never opened.
  function group(title, items, make, cls = "", open = false) {
    if (!items.length) return null;
    const list = h("ul", { class: `pn-list ${cls}` });
    const box = h("details", { class: `pn-group ${cls}`, open },
      h("summary", {}, h("span", { class: "pn-gtitle", text: title }),
        h("span", { class: "pn-count", text: String(items.length) }),
        h("span", { class: "pn-chev", "aria-hidden": "true" })),
      list);
    const fill = () => { if (!list.childElementCount) list.append(...items.map(make)); };
    if (open) fill(); else box.addEventListener("toggle", () => box.open && fill());
    return box;
  }

  // Popular community build guides for this version's characters (server: api/community.py).
  // Closed by default and only fetched when opened, so nobody pays for what they don't look at.
  const communityCache = new Map();
  function communityVideo(v) {
    const li = video({ youtube_id: v.youtube_id, title: v.title });
    li.querySelector(".pn-video span")?.append(h("small", { class: "pn-chan",
      text: `${v.channel} · ${COMPACT.format(v.views)} views` }));
    return li;
  }
  function community(note, chars) {
    if (!data.community_videos || !chars.length) return null;
    const list = h("ul", { class: "pn-list pn-vids" });
    const status = h("p", { class: "pn-note pn-comm-note", text: "Most-viewed build guides from YouTube creators, published after release. Community content, not checked by Irminsul." });
    const box = h("details", { class: "pn-group pn-community" },
      h("summary", {}, h("span", { class: "pn-gtitle", text: "Community build guides" }),
        h("span", { class: "pn-chev", "aria-hidden": "true" })),
      list, status);
    const own = v => !mine || roster?.has(v.entity_id);
    const fill = vs => {
      const shown = vs.filter(own);
      list.replaceChildren(...shown.map(communityVideo));
      if (!shown.length) list.replaceChildren(h("li", { class: "pn-empty", text: "No community guides yet for this version." }));
    };
    box.addEventListener("toggle", async () => {
      if (!box.open) return;
      if (communityCache.has(note.version)) return fill(communityCache.get(note.version));
      list.replaceChildren(h("li", { class: "placeholder", text: "Loading community guides…" }));
      try {
        const r = await fetch(`/api/community-videos?version=${encodeURIComponent(note.version)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const vs = (await r.json()).videos.filter(v => YT.test(v.youtube_id || ""));
        communityCache.set(note.version, vs);
        fill(vs);
      } catch {
        list.replaceChildren(h("li", { class: "pn-empty", text: "Community guides didn't load. Try again in a moment." }));
      }
    });
    return box;
  }

  function render() {
    const note = data.versions.find(v => v.version === selected) || data.versions[0];
    const own = x => !mine || roster?.has(x.id);
    const chars = note.characters.filter(own), weapons = note.weapons.filter(own);
    const sets = mine ? [] : note.artifact_sets, changes = note.changes.filter(own);
    const videos = note.videos.filter(v => !mine || roster?.has(v.entity_id));

    rail.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === note.version)));
    const body = h("div", { class: "pn-body" },
      h("header", { class: "pn-head" },
        h("div", {},
          h("span", { class: "pn-kicker", text: note.live ? "Live now" : "Patch notes" }),
          h("h3", { text: `Version ${note.version}` }),
          h("p", { class: "pn-date" }, `Released ${longDate(note.date)} · `, source(note.source, "official update notices"))),
        h("button", { type: "button", class: "pn-ask", onclick: () => typeof ask === "function" && ask(`What changed in ${note.version}?`), text: "Ask about this version" })),
      note.live && data.announced.length && !mine ? h("div", { class: "pn-announced" },
        h("b", { text: "Officially announced, not playable yet: " }),
        data.announced.map((a, i) => [i ? ", " : "", h("a", { href: httpUrl(a.source) || "#", target: "_blank", rel: "noopener noreferrer", text: a.name }), ` (${[a.element, a.region].filter(Boolean).join(", ")})`]),
        ". Kit details appear here once they're released.") : null,
      group("New characters", chars, entityCard, "pn-cards", true),
      group("New weapons", weapons, entityCard, "pn-cards"),
      group("New artifact sets", sets, entityCard, "pn-cards"),
      group("Changes since the previous build", changes, change, "pn-changes"),
      group("New official videos", videos, video, "pn-vids", true),
      community(note, chars));
    const empty = !chars.length && !weapons.length && !sets.length && !changes.length && !videos.length;
    if (empty) body.append(h("p", { class: "pn-empty", text: mine
      ? (roster?.size ? "Nothing in this version for the characters in your planner." : "Your planner is empty on this device. Add characters in the Daily planner to filter patch notes to them.")
      : "Nothing new in the released data for this version." }));
    if (!note.tracked && data.tracking_since) body.append(h("p", { class: "pn-note",
      text: `New weapons, artifact sets and balance changes are tracked from ${longDate(data.tracking_since)}. Before that, patch notes list new characters from their official release dates.` }));
    view.replaceChildren(body);
  }

  /* ---------- shell ---------- */
  const rail = h("div", { class: "pn-rail", role: "group", "aria-label": "Game version" });
  const view = h("div", { class: "pn-view", "aria-live": "polite" });
  const toggle = h("input", { type: "checkbox", id: "pnMine", class: "pn-switch" });
  const toolbar = h("div", { class: "pn-tools" }, rail,
    h("label", { class: "pn-mine", for: "pnMine" }, toggle, h("span", { text: "For my characters" })));
  toggle.addEventListener("change", async () => {
    mine = toggle.checked; pref.set(mine);
    if (mine) await loadRoster();
    if (data) render();
  });
  rail.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    selected = b.dataset.v; render();
  });
  rail.addEventListener("keydown", e => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const bs = [...rail.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
    const next = bs[Math.max(0, Math.min(bs.length - 1, i + (e.key === "ArrowRight" ? 1 : -1)))];
    next.focus(); next.click(); e.preventDefault();
  });

  function load() {
    return loading ||= (async () => {
      root.replaceChildren(h("p", { class: "placeholder", text: "Loading patch notes…" }));
      try {
        const r = await fetch("/api/patches");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        data = await r.json();
        if (!data.versions?.length) throw new Error("no versions");
      } catch {
        loading = null;
        root.replaceChildren(h("p", { class: "placeholder", text: "Patch notes didn't load. Try again in a moment." }));
        return;
      }
      selected ||= data.live || data.versions[0].version;
      rail.replaceChildren(...data.versions.map(v => h("button", { type: "button", "data-v": v.version, "aria-pressed": "false",
        class: v.live ? "live" : null, text: v.version })));
      mine = toggle.checked = pref.get();
      if (mine) await loadRoster();
      root.replaceChildren(toolbar, view);
      render();
      rail.querySelector("[aria-pressed=true]")?.scrollIntoView({ block: "nearest", inline: "center" });
    })();
  }

  // Load once the page is idle (or when it comes near the screen, if that's sooner), so the
  // section fills in below the fold instead of pushing content the player is looking at.
  if ("IntersectionObserver" in self) {
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); load(); } }, { rootMargin: "600px" });
    io.observe(root);
  }
  (self.requestIdleCallback || (f => setTimeout(f, 1200)))(() => load(), { timeout: 2500 });
  document.addEventListener("click", async e => {
    const a = e.target.closest("a[data-patch]"); if (!a) return;
    selected = a.dataset.patch;
    await load();
    if (data) render();
  });
})();
