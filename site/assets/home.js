// Page script; inline scripts are blocked by the Content-Security-Policy.
// Menu counts aren't needed for first paint, so fetch the data once the page is idle.
(window.requestIdleCallback || ((fn) => setTimeout(fn, 300)))(() =>
  DL.loadData().then((d) => DL.setCounts(d.sites, 25)).catch(() => {}));
// Carry the chosen category into the next page.
function syncLinks() {
  const q = DL.category === "all" ? "" : "?cat=" + DL.category;
  document.getElementById("go-rankings").href = "leaderboards/" + q;
  document.getElementById("go-live").href = "live/" + q;
}
DL.onCategory(syncLinks); syncLinks();
