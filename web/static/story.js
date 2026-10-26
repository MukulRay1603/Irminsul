/* Story-safe mode: "I've finished the Archon Quest up to …" picker. The choice is kept in this
   browser only (localStorage) and sent with each question as `story_until`; the server then
   hides lore revealed after that point. Loaded before app.js, which reads window.story.value()
   when it asks and calls window.story.decorate(answerEl, done, question, ask) once an answer
   has finished. No inline styles or handlers, so it runs under the strict CSP. */

window.story = (() => {
  const KEY = "irminsul-story";
  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/static/story.css";
  document.head.append(css);

  const read = () => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } };
  const write = v => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch {} };
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  let points = null;  // [{key, label, chapter, until}] once /api/story answers
  let current = read();
  const selects = [];

  const pointOf = key => points?.find(p => p.key === key);

  function set(key, from) {
    current = key; write(key);
    for (const s of selects) if (s !== from) s.value = key;
    document.querySelectorAll(".story-pick").forEach(w => w.classList.toggle("on", !!key));
  }

  function fill(select) {
    select.replaceChildren(...points.map(p => {
      const o = el("option", null, `${p.label} (${p.chapter})`); o.value = p.key; return o;
    }), Object.assign(el("option", null, "Everything released (no spoiler filter)"), { value: "" }));
    select.value = current;
  }

  // One picker per [data-story-slot]; they stay in sync.
  function mount(slot, n) {
    const id = `storyUntil${n}`;
    const wrap = el("div", "story-pick");
    const label = el("label", null, "Archon Quest finished up to");
    label.htmlFor = id;
    const select = el("select"); select.id = id;
    select.title = "Lore past this point is hidden. Saved in this browser only.";
    select.addEventListener("change", () => set(select.value, select));
    wrap.append(label, select);
    slot.append(wrap);
    selects.push(select);
  }

  document.querySelectorAll("[data-story-slot]").forEach(mount);
  fetch("/api/story").then(r => r.ok ? r.json() : null).then(data => {
    if (!data?.points?.length) return;
    points = data.points;
    if (current && !pointOf(current)) current = "";  // a point we no longer offer
    selects.forEach(fill);
    set(current);
  }).catch(() => {});

  /* After an answer: a "Show anyway" button for a spoiler stop, and a quiet note on any answer
     the filter shaped. `ask(question, {story: ""})` asks again with no limit. */
  function decorate(answerEl, done, question, ask) {
    const f = done.trace?.spoiler_filter;
    if (done.route === "spoiler") {
      const row = el("div", "story-stop");
      const btn = el("button", "story-anyway", "Show anyway");
      btn.type = "button";
      btn.addEventListener("click", () => ask(question, { story: "" }));
      row.append(btn, el("span", null, "Asks once without the filter. Your setting stays."));
      answerEl.querySelector(".body")?.after(row);
    } else if (f?.hidden) {
      const note = el("p", "story-note", `Spoiler filter on: up to ${f.label}, ${f.hidden} passage${f.hidden === 1 ? "" : "s"} hidden.`);
      answerEl.querySelector(".body")?.after(note);
    }
  }

  // The trace line for "Why this answer".
  const traceLine = f => f ? `up to ${f.label} (v${f.max_version}), ${f.hidden} passage${f.hidden === 1 ? "" : "s"} hidden` : "";

  return { value: () => current, decorate, traceLine };
})();
