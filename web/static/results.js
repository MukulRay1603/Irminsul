/* The public test-results page: renders /static/results.json (made by `irminsul-report`).
   No inline code; bar lengths are set through CSSOM custom properties, which the CSP allows. */

(() => {
  const $ = s => document.querySelector(s);
  try {
    const saved = localStorage.getItem("irminsul-mode");
    document.documentElement.dataset.mode = saved || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  } catch { /* storage blocked: keep the default */ }

  const h = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const pct = x => x == null ? "–" : `${Math.round(x * 1000) / 10}%`;
  const usd = (x, digits = 2) => x === 0 ? "$0" : `$${x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  const CATS = {
    stat: "Stats (base and ascension)", passive: "Passives, set bonuses, constellations",
    upcoming: "Announced characters", leak_probe: "Leak probes", injection: "Prompt injection",
    offtopic: "Off-topic", mechanic: "Game mechanics", build: "Builds and teams",
    gacha: "Wishes and pity", beginner: "Beginner questions",
  };

  function tile(value, label, detail, tone = "") {
    const t = h("div", `tile ${tone}`);
    t.append(h("b", "tile-value", value), h("span", "tile-label", label), h("span", "tile-detail", detail));
    return t;
  }

  function meter(label, value, note) {
    const m = h("div", "meter");
    const top = h("div", "meter-top");
    top.append(h("span", null, label), h("b", null, pct(value)));
    const bar = h("div", "bar-track"), fill = h("i", "bar-fill");
    fill.style.setProperty("--v", String(value ?? 0));
    bar.append(fill);
    m.append(top, bar);
    if (note) m.append(h("span", "meter-note", note));
    return m;
  }

  function render(d) {
    const a = d.answers, r = d.retrieval, c = d.cost, ref = c.paid_reference;
    const date = new Date(`${d.generated}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
    $("#meta").replaceChildren(
      ...[d.game_version && `Game version ${d.game_version}`, `${d.eval_set.items} eval questions`, `Updated ${date}`]
        .filter(Boolean).map(t => h("li", null, t)));

    const ratio = x => x ? `${x.passed}/${x.total}` : "–";
    const rate = x => x && x.total ? pct(x.passed / x.total) : "–";
    $("#tiles").replaceChildren(
      tile(rate(a.stat_accuracy), "Stat accuracy", `${ratio(a.stat_accuracy)} exact stat questions answered from game data`, "gold"),
      tile(ratio(a.leak_probes), "Leak probes refused", "Datamine and unreleased-character questions stopped before any search"),
      tile(ratio(a.refusal_probes), "Injection and off-topic refused", "Attempts to change the rules or ask about other things"),
      tile(usd(c.per_ai_answer_usd), "Cost per answer", "AI answers run on free tiers; game-data answers use no AI", "leaf"),
    );

    if (r) {
      $("#retrMeters").replaceChildren(
        meter("Correct source in the top 3", r.hit_at_3),
        meter("Correct source in the top 8", r.hit_at_8, "The app gives the AI the top 6."),
        meter("Mean reciprocal rank (top 8)", r.mrr_at_8, "1.0 would mean the right source always ranks first."),
      );
      $("#retrFine").textContent = `${r.questions} questions · ${r.chunks.toLocaleString()} indexed passages · keyword + embedding search (${r.embed_model}) with a re-ranker · ~${Math.round(r.p50_ms)} ms per search on a desktop CPU.`;
    } else {
      $("#retrMeters").replaceChildren(h("p", "fine", "Not measured in this run (no search index was available)."));
    }

    const cost = $("#costBody");
    const big = h("p", "cost-big");
    big.append(h("b", null, "$0"), h("span", null, " per answer today"));
    const list = h("ul", "cost-list");
    const li = (k, v) => { const e = h("li"); e.append(h("span", null, k), h("b", null, v)); return e; };
    list.append(
      li(`One AI answer at ${ref.provider}'s paid price`, usd(ref.per_ai_answer_usd, 6)),
      li("1,000 AI answers", usd(ref.per_1000_ai_answers_usd)),
    );
    if (c.ai_share_of_eval_set != null) {
      list.append(
        li("Questions in the eval set that need AI", pct(c.ai_share_of_eval_set)),
        li("Average per answer, all questions", usd(c.per_answer_blended_usd, 6)),
      );
    }
    cost.replaceChildren(big, list, h("p", "fine",
      `Paid price: ${usd(ref.input_per_m)} / ${usd(ref.output_per_m)} per million input / output tokens, assuming about ` +
      `${(ref.tokens_per_ai_answer.input / 1000).toFixed(1)}K in and ${(ref.tokens_per_ai_answer.output / 1000).toFixed(1)}K out per AI answer.`));

    const cats = $("#cats");
    const counts = d.eval_set.by_category;
    const rows = Object.keys(counts).map(k => {
      const s = a.by_category[k], row = h("div", "cat");
      const name = h("span", "cat-name", CATS[k] || k);
      const bar = h("div", "bar-track"), fill = h("i", "bar-fill");
      const scored = s ? s.total : 0, needs = counts[k] - scored;
      fill.style.setProperty("--v", String(s && s.total ? s.passed / s.total : 0));
      bar.append(fill);
      const val = h("b", "cat-val", s ? `${s.passed}/${s.total}` : "–");
      row.append(name, bar, val);
      if (needs > 0) { row.classList.add("llm"); row.append(h("span", "cat-note", `${needs} need an AI answer, not scored here`)); }
      return [s ? 0 : 1, row];
    });
    cats.replaceChildren(...rows.sort((x, y) => x[0] - y[0]).map(x => x[1]));

    const fails = $("#failures");
    if (a.failures?.length) {
      const box = h("details", "fails");
      box.append(h("summary", null, `${a.failures.length} failing question${a.failures.length === 1 ? "" : "s"}`));
      const ul = h("ul");
      for (const f of a.failures) ul.append(h("li", null, `${f.id}: ${f.problems.join("; ")}`));
      box.append(ul); fails.replaceChildren(box);
    } else {
      fails.replaceChildren(h("p", "allpass", `All ${a.scored} scored questions pass.`));
    }
  }

  // Anonymous 👍/👎 from the app (api/feedback.py): shown once there is at least one vote
  const ROUTE_NAMES = { exact: "Game-data answers", rag: "AI-written answers", busy: "Busy replies" };
  const routeName = r => ROUTE_NAMES[r] || (r.startsWith("refuse") ? "Refusals" : r.replace(/_/g, " "));
  function renderVotes(s) {
    if (!s || !(s.up + s.down)) return;
    const merged = {};
    for (const [route, c] of Object.entries(s.routes)) {
      const m = merged[routeName(route)] ||= { up: 0, down: 0 };
      m.up += c.up; m.down += c.down;
    }
    $("#playerCats").replaceChildren(...Object.entries(merged).map(([name, c]) => {
      const row = h("div", "cat votes"), bar = h("div", "bar-track"), fill = h("i", "bar-fill");
      fill.style.setProperty("--v", String(c.up / Math.max(1, c.up + c.down)));
      bar.append(fill);
      row.append(h("span", "cat-name", name), bar, h("b", "cat-val", `👍 ${c.up} · 👎 ${c.down}`));
      return row;
    }));
    $("#players").hidden = false;
  }
  fetch("/api/feedback-summary").then(r => r.ok ? r.json() : null).then(renderVotes).catch(() => {});

  fetch("/static/results.json", { cache: "no-cache" })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(render)
    .catch(() => $("#meta").replaceChildren(h("li", "err", "The results file couldn't be loaded.")));
})();
