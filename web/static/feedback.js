/* Anonymous feedback: 👍/👎 on each answer and the general "Send feedback" form (about page).
   Loaded after trust.js and before app.js; app.js calls window.feedback.decorate(answerEl,
   done, question) once an answer has finished. A page with a [data-feedback-form] element
   gets the general form there. POST /feedback stores no IP or id (see api/feedback.py).
   One vote per answer, remembered in sessionStorage. No inline styles or handlers, so it runs
   under the strict Content-Security-Policy. */

window.feedback = (() => {
  const KEY = "irminsul-feedback";
  const REASONS = [
    ["wrong_info", "Wrong info"],
    ["missing_info", "Missing info"],
    ["hard_to_read", "Hard to read"],
    ["not_answered", "Didn't answer my question"],
  ];
  const MAX = 500;

  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/static/feedback.css";
  document.head.append(css);

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const votes = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; } };
  const remember = (key, rating) => {
    try { sessionStorage.setItem(KEY, JSON.stringify({ ...votes(), [key]: rating })); } catch {}
  };
  // Same question, same route: the same answer as far as a vote is concerned.
  const keyOf = (question, route) => `${route}:${question}`.slice(0, 300);

  async function send(body) {
    const res = await fetch("/feedback", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    if (res.ok) return;
    const e = await res.json().catch(() => ({}));
    throw new Error(typeof e.detail === "string" ? e.detail : "Couldn't send that. Please try again.");
  }

  // A comment box with a live character count; shared by the 👎 form and the general one.
  function commentBox(id, label, placeholder) {
    const wrap = el("div", "fb-field");
    const lab = el("label", null, label); lab.htmlFor = id;
    const box = el("textarea"); box.id = id; box.maxLength = MAX; box.rows = 3; box.placeholder = placeholder;
    const count = el("span", "fb-count", `0 / ${MAX}`); count.id = `${id}-count`; count.setAttribute("aria-live", "polite");
    box.setAttribute("aria-describedby", count.id);
    box.addEventListener("input", () => { count.textContent = `${box.value.length} / ${MAX}`; });
    wrap.append(lab, box, count);
    return { wrap, box };
  }

  let seq = 0;

  function decorate(answerEl, done, question) {
    const head = answerEl?.querySelector(".ans-head");
    if (!head || !done) return;
    const q = (question || "").trim(), key = keyOf(q, done.route);
    const payload = rating => ({
      kind: "answer", rating, question: q.slice(0, 600) || undefined, route: done.route,
      doc_ids: [...new Set((done.citations || []).map(c => c.doc_id).filter(Boolean))].slice(0, 12),
      game_version: head.querySelector(".ver")?.textContent.replace(/^v/, "").trim() || undefined,
    });

    const group = el("span", "fb"); group.setAttribute("role", "group"); group.setAttribute("aria-label", "Was this answer helpful?");
    const up = el("button", "fb-vote", "👍"), down = el("button", "fb-vote", "👎");
    up.type = down.type = "button";
    up.setAttribute("aria-label", "Helpful"); up.title = "Helpful";
    down.setAttribute("aria-label", "Not helpful"); down.title = "Not helpful";
    down.setAttribute("aria-expanded", "false");
    const thanks = el("span", "fb-thanks", "Thanks!"); thanks.setAttribute("role", "status"); thanks.hidden = true;
    thanks.tabIndex = -1;  // takes focus when the 👎 form it replaces goes away
    group.append(up, down, thanks);
    (head.querySelector(".report") || head.querySelector(".copy") || head.lastElementChild).after(group);

    const lock = rating => {
      for (const b of [up, down]) b.disabled = true;
      (rating === "up" ? up : down).setAttribute("aria-pressed", "true");
      thanks.hidden = false;
    };
    const prior = votes()[key];
    if (prior) { lock(prior); thanks.textContent = "Thanks for the feedback"; return; }

    // The 👎 form: optional reason chips and an optional comment
    const id = `fb${++seq}`;
    const form = el("form", "fb-form"); form.hidden = true; form.setAttribute("aria-label", "What went wrong?");
    const chips = el("div", "fb-chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "What went wrong? (optional)");
    let reason = null;
    for (const [value, label] of REASONS) {
      const chip = el("button", "fb-chip", label); chip.type = "button"; chip.dataset.reason = value;
      chip.setAttribute("aria-pressed", "false");
      chips.append(chip);
    }
    chips.addEventListener("click", e => {
      const chip = e.target.closest(".fb-chip"); if (!chip) return;
      reason = reason === chip.dataset.reason ? null : chip.dataset.reason;
      chips.querySelectorAll(".fb-chip").forEach(c => c.setAttribute("aria-pressed", String(c.dataset.reason === reason)));
    });
    const { wrap, box } = commentBox(id, "Anything else? (optional)", "What should it have said?");
    const err = el("p", "fb-error"); err.setAttribute("role", "alert"); err.hidden = true;
    const actions = el("div", "fb-actions");
    const submit = el("button", "fb-send", "Send"); submit.type = "submit";
    const cancel = el("button", "fb-cancel", "Cancel"); cancel.type = "button";
    actions.append(submit, cancel, el("span", "fb-note", "Anonymous. Please leave out personal details."));
    form.append(chips, wrap, err, actions);
    (answerEl.querySelector(".trust-report") || head).after(form);

    const close = () => { form.hidden = true; down.setAttribute("aria-expanded", "false"); down.focus(); };
    up.addEventListener("click", async () => {
      lock("up");
      try { await send(payload("up")); remember(key, "up"); }
      catch (e) { thanks.textContent = e.message; up.disabled = down.disabled = false; up.removeAttribute("aria-pressed"); }
    });
    down.addEventListener("click", () => {
      form.hidden = !form.hidden;
      down.setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) chips.querySelector(".fb-chip").focus();
    });
    cancel.addEventListener("click", close);
    form.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); close(); } });
    form.addEventListener("submit", async e => {
      e.preventDefault();
      submit.disabled = true; err.hidden = true;
      const body = payload("down");
      if (reason) body.reason = reason;
      if (box.value.trim()) body.comment = box.value.trim();
      try {
        await send(body);
        remember(key, "down"); form.remove(); lock("down"); thanks.focus();
      } catch (ex) {
        err.textContent = ex.message; err.hidden = false; submit.disabled = false;
      }
    });
  }

  /* ---------- The general form (about page) ---------- */
  function mountGeneral(slot) {
    const form = el("form", "fb-form fb-general");
    const { wrap, box } = commentBox("fbGeneral", "Your feedback", "Ideas, bugs, something you'd like Irminsul to answer…");
    box.rows = 5; box.required = true;
    const err = el("p", "fb-error"); err.setAttribute("role", "alert"); err.hidden = true;
    const done = el("p", "fb-done", "Thanks! Your feedback was sent."); done.setAttribute("role", "status"); done.hidden = true;
    const actions = el("div", "fb-actions");
    const submit = el("button", "fb-send", "Send feedback"); submit.type = "submit";
    actions.append(submit, el("span", "fb-note", "Anonymous: no name, email or account. Personal details are refused."));
    form.append(wrap, err, actions);
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const comment = box.value.trim();
      if (!comment) { box.focus(); return; }
      submit.disabled = true; err.hidden = true;
      try {
        await send({ kind: "general", rating: "none", comment });
        form.hidden = true; done.hidden = false;
      } catch (ex) {
        err.textContent = ex.message; err.hidden = false;
      } finally { submit.disabled = false; }
    });
    slot.replaceChildren(form, done);
  }

  const slot = document.querySelector("[data-feedback-form]");
  if (slot) mountGeneral(slot);

  return { decorate };
})();
