// Page script; inline scripts are blocked by the Content-Security-Policy.
// Menu counts aren't needed for first paint, so fetch the data once the page is idle.
(window.requestIdleCallback || ((fn) => setTimeout(fn, 300)))(() =>
  DL.loadData().then((d) => DL.setCounts(DL.inRange(d, "month"))).catch(() => {}));
// Carry the chosen category into the next page.
function syncLinks() {
  const q = DL.category === "all" ? "" : "?cat=" + encodeURIComponent(DL.category);
  const goRankings = document.getElementById("go-rankings");
  const goLive = document.getElementById("go-live");
  if (goRankings) goRankings.href = "leaderboards/" + q;
  if (goLive) goLive.href = "live/" + q;
}
DL.onCategory(syncLinks); syncLinks();

