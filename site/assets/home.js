// Page script; inline scripts are blocked by the Content-Security-Policy.
// Menu counts aren't needed for first paint, so fetch the data once the page is idle.
(window.requestIdleCallback || ((fn) => setTimeout(fn, 300)))(() =>
  DL.loadData().then((d) => {
    DL.setCounts(d.sites, 25);
    // "Updated Oct 4 · 25 sites ranked" above the logo.
    const date = d.generated_at ? new Date(d.generated_at) : null;
    const pulse = document.getElementById("pulse");
    const text = document.getElementById("pulse-text");
    if (!pulse || !text || !date || isNaN(date.getTime()) || !d.sites.length) return;
    const when = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    text.innerHTML = `Updated <b>${DL.esc(when)}</b> · ${Math.min(25, d.sites.length)} sites ranked`;
    pulse.classList.add("ready");
  }).catch(() => {}));
// Carry the chosen category into the next page.
function syncLinks() {
  const q = DL.category === "all" ? "" : "?cat=" + encodeURIComponent(DL.category);
  const goRankings = document.getElementById("go-rankings");
  const goLive = document.getElementById("go-live");
  if (goRankings) goRankings.href = "leaderboards/" + q;
  if (goLive) goLive.href = "live/" + q;
}
DL.onCategory(syncLinks); syncLinks();

