// Page script; inline scripts are blocked by the Content-Security-Policy.
const fmt = new Intl.NumberFormat("en-US");
const $ = (id) => document.getElementById(id);
// History of viewed sites lives in sessionStorage, so it's cleared when the session ends.
const KEY = "deploylist.live";
let pool = [], byId = {}, hist = { ids: [], pos: -1 };
try { hist = JSON.parse(sessionStorage.getItem(KEY)) || hist; } catch {}
const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(hist)); } catch {} };

function candidates() { return pool.filter((s) => DL.inCategory(s)); }

function show(site) {
  $("empty").hidden = true;
  $("frame").hidden = false;
  $("frame").src = DL.safeUrl(site.url);
  $("site-link").textContent = site.domain;
  $("site-link").href = DL.safeUrl(site.url);
  $("site-link").title = site.title;
  $("votes").textContent = `${fmt.format(site.votes)} votes`;
  $("post-link").href = DL.safeUrl(site.post_url);
  $("post-link").hidden = false;
  $("prev").disabled = hist.pos <= 0;
  document.title = `${site.domain} · deploylist live`;
  if (hist.pos === hist.ids.length - 1) prepareNext();
}

// Pick the next random site ahead of time and warm up a connection to it,
// so pressing › loads faster.
let upcoming = null;
function randomPick() {
  const list = candidates();
  if (!list.length) return null;
  const seen = new Set(hist.ids);
  const fresh = list.filter((s) => !seen.has(s.id));
  const recent = new Set(hist.ids.slice(-Math.floor(list.length / 2)));
  const older = list.filter((s) => !recent.has(s.id));
  const from = fresh.length ? fresh : older.length ? older : list;
  return from[Math.floor(Math.random() * from.length)];
}
function prepareNext() {
  upcoming = randomPick();
  document.querySelectorAll("link[data-warm]").forEach((l) => l.remove());
  if (!upcoming) return;
  const link = Object.assign(document.createElement("link"), { rel: "preconnect", href: new URL(upcoming.url).origin });
  link.dataset.warm = "";
  document.head.appendChild(link);
}

function empty(msg) {
  $("frame").hidden = true; $("frame").removeAttribute("src");
  $("empty").hidden = false; $("empty").textContent = msg;
  $("site-link").textContent = "deploylist live"; $("site-link").removeAttribute("href");
  $("votes").textContent = ""; $("post-link").hidden = true;
  $("prev").disabled = hist.pos <= 0;
}

function next() {
  // Walk forward through history first, then pick a random site, preferring unseen ones.
  if (hist.pos < hist.ids.length - 1) { hist.pos++; save(); return show(byId[hist.ids[hist.pos]]); }
  const pick = upcoming && DL.inCategory(upcoming) && !hist.ids.includes(upcoming.id) ? upcoming : randomPick();
  upcoming = null;
  if (!pick) return empty("No live-viewable sites in this category yet.");
  hist.ids.push(pick.id); hist.pos = hist.ids.length - 1; save();
  show(pick);
}

function prev() {
  if (hist.pos <= 0) return;
  hist.pos--; save(); show(byId[hist.ids[hist.pos]]);
}

$("next").addEventListener("click", next);
$("prev").addEventListener("click", prev);
addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea")) return;
  if (e.key === "ArrowRight") next();
  if (e.key === "ArrowLeft") prev();
});

DL.loadData().then((d) => {
  pool = d.sites.filter((s) => s.embeddable);
  pool.forEach((s) => (byId[s.id] = s));
  DL.setCounts(pool);
  // Drop history entries that are no longer in the data.
  hist.ids = hist.ids.filter((id) => byId[id]);
  hist.pos = Math.min(hist.pos, hist.ids.length - 1);
  const cur = byId[hist.ids[hist.pos]];
  if (cur && DL.inCategory(cur)) show(cur); else { hist.ids = hist.ids.slice(0, hist.pos + 1); next(); }
  DL.onCategory(() => { hist.ids = hist.ids.slice(0, hist.pos + 1); next(); });
}).catch(() => empty("Couldn't load the site list."));
