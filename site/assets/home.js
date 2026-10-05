// Page script; inline scripts are blocked by the Content-Security-Policy.
// Menu counts aren't needed for first paint, so fetch the data once the page is idle.
let data;
(window.requestIdleCallback || ((fn) => setTimeout(fn, 300)))(() =>
  DL.loadData().then((d) => { data = d; DL.setCounts(DL.inRange(d)); }).catch(() => {}));
DL.onRange(() => { if (data) DL.setCounts(DL.inRange(data)); syncLinks(); });
// Carry the chosen category and time range into the next page.
function syncLinks() {
  const params = new URLSearchParams();
  if (DL.category !== "all") params.set("cat", DL.category);
  if (DL.range !== "month") params.set("range", DL.range);
  const q = params.toString() ? "?" + params : "";
  const goRankings = document.getElementById("go-rankings");
  const goLive = document.getElementById("go-live");
  if (goRankings) goRankings.href = "leaderboards/" + q;
  if (goLive) goLive.href = "live/" + q;
}
DL.onCategory(syncLinks); syncLinks();

