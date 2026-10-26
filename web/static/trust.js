/* Trust features for each answer: which sentences match their cited sources, and a way to
   report a wrong answer. Loaded after answers.js and before app.js; app.js calls
   window.trust.decorate(answerEl, done) once an answer has finished. No inline styles or
   handlers, so it runs under the strict Content-Security-Policy. Nothing here talks to our
   server: the report opens a pre-filled issue on GitHub in a new tab. */

window.trust = (() => {
  const REPO = "MukulRay1603/Irminsul";
  const MAX_URL = 6000;  // GitHub (and some browsers) reject much longer issue URLs
  const TIPS = {
    number: "A number here isn't in the cited source",
    words: "Not found in the cited source",
    no_citation: "No source cited, and none of the sources says this",
  };

  // The stylesheet is added from here so the page head (owned by the app shell) stays as is.
  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/static/trust.css";
  document.head.append(css);

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const squash = s => s.toLowerCase().replace(/\s+/g, "");

  /* Every visible non-space character of the answer with the text node it sits in, so a
     sentence from the server can be found however the Markdown split it into elements.
     Citation markers are skipped: the server's sentence text has them removed too. */
  function charMap(root) {
    let text = ""; const at = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: n => n.parentElement.closest(".cite") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    for (let n; (n = walk.nextNode());) {
      for (let i = 0; i < n.data.length; i++) {
        const c = n.data[i].toLowerCase();
        if (c.length === 1 && !/\s/.test(c)) { text += c; at.push([n, i]); }
      }
    }
    return { text, at };
  }

  // Splits a run of characters into one [node, start, end) piece per text node (the spaces
  // between them, skipped in the map, are inside the same node and come along).
  function pieces(at, from, to) {
    const out = [];
    for (let k = from; k < to; k++) {
      const [node, i] = at[k], last = out[out.length - 1];
      if (last && last[0] === node) last[2] = i + 1;
      else out.push([node, i, i + 1]);
    }
    return out;
  }

  function markSentences(body, sentences) {
    const map = charMap(body), jobs = [];
    let cursor = 0;
    for (const s of sentences) {
      const needle = squash(s.text);
      if (!needle) continue;
      const found = map.text.indexOf(needle, cursor);
      if (found < 0) continue;  // not on the page as written: leave it unmarked, never guess
      cursor = found + needle.length;
      if (s.status === "unsupported" || s.status === "uncited") {
        jobs.push({ s, parts: pieces(map.at, found, cursor) });
      }
    }
    // Wrap from the end backwards so splitting a text node never moves a piece still to come.
    for (const { s, parts } of jobs.reverse()) {
      const tip = TIPS[s.reason] || TIPS.words;
      const where = "";  // sources are named buttons now, so no numbers in the tip
      parts.reverse().forEach(([node, a, b], k) => {
        const range = document.createRange();
        range.setStart(node, a); range.setEnd(node, b);
        const span = el("span", "trust-flag"); span.title = tip;
        range.surroundContents(span);
        if (k === 0) {  // after the sentence's last piece: the tooltip, reachable by keyboard
          const mark = el("span", "trust-mark", "?");
          mark.tabIndex = 0; mark.setAttribute("role", "note");
          mark.setAttribute("aria-label", tip + where);
          mark.dataset.tip = tip + where;
          span.after(mark);
        }
      });
    }
    // Tooltips open leftwards from the mark; near the left edge (phones) they open rightwards.
    const place = e => {
      const m = e.target.closest?.(".trust-mark");
      if (m) m.classList.toggle("flip", m.getBoundingClientRect().left < 240);
    };
    body.addEventListener("pointerover", place);
    body.addEventListener("focusin", place);
  }

  function summary(g) {
    const bad = g.unsupported.length, none = g.uncited.length;
    if (!g.checked && !none) return null;
    const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    let text = "", ok = !bad && !none;
    if (g.checked) {
      text = bad
        ? `${plural(bad, "sentence", "sentences")} couldn't be matched to ${bad === 1 ? "its source" : "their sources"}`
        : g.checked === 1 ? "The cited sentence matches its source"
        : `All ${g.checked} cited sentences match their sources`;
    }
    if (none) text += `${text ? " · " : ""}${plural(none, "sentence has", "sentences have")} no source`;
    const line = el("p", `trust-sum ${ok ? "ok" : "warn"}`);
    line.append(el("i", null), el("span", null, text));
    line.title = "Each sentence is checked against the text of the source it cites: every number must "
      + "appear there, and most of its words. A quick automatic check, not a guarantee.";
    return line;
  }

  /* ---------- Report a wrong answer: a pre-filled GitHub issue, nothing sent to us ---------- */
  function issueUrl({ question, route, answer, sources, version }) {
    const base = `https://github.com/${REPO}/issues/new?`;
    const params = {
      template: "wrong-answer.yml",
      title: `Wrong answer: ${question.slice(0, 80)}`,
      question, route, sources: sources.join("\n") || "(none)", version: version || "unknown",
    };
    const query = new URLSearchParams(params).toString();
    const room = MAX_URL - base.length - query.length - "&answer=".length;
    let text = answer;
    const fits = t => new URLSearchParams({ answer: t }).toString().length - "answer=".length <= room;
    if (!fits(text)) {  // cut by halves, then grow back, to the longest prefix that fits
      const tail = "\n…(cut to fit the link)";
      let lo = 0, hi = text.length;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; fits(text.slice(0, mid) + tail) ? lo = mid : hi = mid - 1; }
      text = text.slice(0, lo) + tail;
    }
    return `${base}${query}&${new URLSearchParams({ answer: text })}`;
  }

  // The answer as plain text: citations back as [n], one line per paragraph, bullet or row.
  function answerText(body) {
    if (!body) return "";
    const copy = body.cloneNode(true);
    copy.querySelectorAll(".trust-mark").forEach(m => m.remove());
    copy.querySelectorAll(".cite").forEach(c => c.replaceWith(` [${c.dataset.n || c.textContent.trim()}]`));
    // Game-data cards are laid out with many small elements: keep their words apart.
    if (body.classList.contains("has-card")) copy.querySelectorAll("span, b, strong, em, h3, h4").forEach(e => e.after(" "));
    copy.querySelectorAll("p, li, h4, tr, blockquote, div").forEach(b => b.append("\n"));
    copy.querySelectorAll("li").forEach(li => li.prepend("- "));
    copy.querySelectorAll("td, th").forEach(c => c.append(" | "));
    return copy.textContent.replace(/[ \t]+/g, " ").replace(/ ?\n ?/g, "\n")
      .replace(/\s+\[(\d+)\]/g, " [$1]").replace(/\n{3,}/g, "\n\n").trim();
  }

  function addReport(answerEl, done) {
    const head = answerEl.querySelector(".ans-head"), copy = head?.querySelector(".copy");
    if (!head) return;
    const btn = el("button", "report", "Report");
    btn.type = "button"; btn.setAttribute("aria-expanded", "false");
    btn.title = "Report a wrong answer";
    const note = el("p", "trust-report"); note.hidden = true;
    const link = el("a", null, "Open GitHub ↗");
    link.target = "_blank"; link.rel = "noopener noreferrer";
    note.append(el("span", null, "Opens a pre-filled issue on GitHub. Nothing is sent to Irminsul. "), link);
    btn.addEventListener("click", () => {
      const q = answerEl.previousElementSibling?.classList.contains("q") ? answerEl.previousElementSibling.textContent : "";
      link.href = issueUrl({
        question: q.trim(),
        route: done.route,
        answer: answerText(answerEl.querySelector(".body")),
        sources: (done.citations || []).map(c => `[${c.n}] ${c.doc_id || c.title}`),
        version: document.getElementById("fVersion")?.textContent.trim(),
      });
      note.hidden = !note.hidden;
      btn.setAttribute("aria-expanded", String(!note.hidden));
    });
    (copy || head.lastElementChild).after(btn);
    head.after(note);
  }

  function decorate(answerEl, done) {
    if (!answerEl || !done) return;
    addReport(answerEl, done);
    const g = done.trace?.grounding, body = answerEl.querySelector(".body");
    if (!g || !body || done.route !== "rag") return;
    try { markSentences(body, g.sentences || []); } catch { /* marking is a nicety; the summary still shows */ }
    const line = summary(g);
    if (line) body.after(line);
  }

  return { decorate, issueUrl };
})();
