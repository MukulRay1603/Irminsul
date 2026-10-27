/* The about page: the saved light/dark mode, the live game data version and build date, and
   the fair-use numbers, all from /health. The feedback form is feedback.js's. No inline code,
   so it runs under the strict Content-Security-Policy. */

(() => {
  const $ = s => document.querySelector(s);
  try {
    const saved = localStorage.getItem("irminsul-mode");
    document.documentElement.dataset.mode = saved || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  } catch { /* storage blocked: keep the default */ }

  const minutes = s => {
    const m = Math.round(s / 60);
    return m % 60 === 0 ? `${m / 60} hour${m === 60 ? "" : "s"}` : `${m} minutes`;
  };

  fetch("/health").then(r => r.json()).then(h => {
    const v = h.corpus?.game_version || "", live = v.length >= 2 ? `${v[0]}.${v[1]}` : "";
    const built = h.corpus?.built_at ? new Date(h.corpus.built_at) : null;
    const date = built && !isNaN(built) ? built.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "";
    $("#version").textContent = live
      ? `Live game data: version ${live}${date ? `, updated ${date}` : ""}.`
      : "Live game data version unavailable right now.";
    const l = h.limits;
    if (l?.allowance_cap && l?.allowance_regen_s) {
      $("#allowance").textContent = `up to ${l.allowance_cap} banked, one more every ${minutes(l.allowance_regen_s)}`;
    }
  }).catch(() => { $("#version").textContent = "Couldn't reach the server for the live data version."; });
})();
