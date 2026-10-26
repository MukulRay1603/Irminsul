/* Installable app: registers the service worker, says when the device is offline, and keeps
   the browser's theme colour in step with light/dark mode. */
(() => {
  if ("serviceWorker" in navigator && isSecureContext) {
    addEventListener("load", () => navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}));
  }

  // A calm banner while offline: the page and planner still work, answers need the network
  const note = document.createElement("div");
  note.className = "offline-note"; note.setAttribute("role", "status");  // empty, so hidden, while online
  document.body.append(note);
  const sync = () => { note.textContent = navigator.onLine ? "" : "You're offline. Answers need a connection."; };
  addEventListener("online", sync); addEventListener("offline", sync); sync();

  const meta = document.querySelector('meta[name="theme-color"]');
  const paint = () => { if (meta) meta.content = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim() || "#0A1811"; };
  new MutationObserver(paint).observe(document.documentElement, { attributes: true, attributeFilter: ["data-mode"] });
  paint();
})();
