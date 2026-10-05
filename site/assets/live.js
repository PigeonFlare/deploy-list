// Page script; inline scripts are blocked by the Content-Security-Policy.
const fmt = new Intl.NumberFormat("en-US");
const $ = (id) => document.getElementById(id);
// History of viewed sites lives in sessionStorage, so it's cleared when the session ends.
const KEY = "deploylist.live";
let pool = [], byId = {}, hist = { ids: [], pos: -1 };
try {
  const parsed = JSON.parse(sessionStorage.getItem(KEY));
  if (parsed && Array.isArray(parsed.ids) && typeof parsed.pos === "number") {
    hist = parsed;
  }
} catch {}
const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(hist)); } catch {} };

function candidates() { return pool.filter((s) => DL.inCategory(s)); }

function show(site) {
  if (!site) return;
  const frame = $("frame");
  const url = DL.safeUrl(site.url);
  const postUrl = DL.safeUrl(site.post_url);

  if (!url.startsWith("https://")) {
    return empty("This site requires an insecure connection and cannot be framed.");
  }
  try {
    const parsed = new URL(url);
    if (parsed.origin === window.location.origin || parsed.hostname === "deploylist.com" || parsed.hostname === "pigeonflare.github.io") {
      return empty("This site cannot be framed.");
    }
  } catch {
    return empty("Invalid site URL.");
  }

  $("empty").hidden = true;
  frame.hidden = false;
  if (frame.src !== url) frame.src = url;

  const siteLink = $("site-link");
  siteLink.textContent = site.domain;
  siteLink.href = url;
  siteLink.title = site.title || site.domain;

  $("votes").textContent = `${fmt.format(site.votes)} votes`;

  const postLink = $("post-link");
  postLink.href = postUrl;
  postLink.hidden = false;
  $("meta-sep").hidden = false;

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
  if (!upcoming || !upcoming.url) return;
  try {
    const origin = new URL(upcoming.url).origin;
    if (origin && origin !== "null" && origin !== window.location.origin) {
      const link = Object.assign(document.createElement("link"), { rel: "preconnect", href: origin });
      link.dataset.warm = "";
      document.head.appendChild(link);
      const dnsLink = Object.assign(document.createElement("link"), { rel: "dns-prefetch", href: origin });
      dnsLink.dataset.warm = "";
      document.head.appendChild(dnsLink);
    }
  } catch {}
}

function empty(msg) {
  const frame = $("frame");
  frame.hidden = true;
  frame.removeAttribute("src");
  $("empty").hidden = false;
  $("empty").textContent = msg;
  const siteLink = $("site-link");
  siteLink.textContent = "deploylist live";
  siteLink.removeAttribute("href");
  siteLink.removeAttribute("title");
  $("votes").textContent = "";
  $("post-link").hidden = true;
  $("meta-sep").hidden = true;
  $("prev").disabled = hist.pos <= 0;
}

function next() {
  // Walk forward through history first, then pick a random site, preferring unseen ones.
  if (hist.pos < hist.ids.length - 1) {
    hist.pos++;
    save();
    return show(byId[hist.ids[hist.pos]]);
  }
  const pick = upcoming && DL.inCategory(upcoming) && !hist.ids.includes(upcoming.id) ? upcoming : randomPick();
  upcoming = null;
  if (!pick) return empty("No live-viewable sites in this category yet.");
  hist.ids.push(pick.id);
  if (hist.ids.length > 200) {
    const trim = hist.ids.length - 200;
    hist.ids = hist.ids.slice(trim);
    hist.pos = Math.max(0, hist.pos - trim);
  }
  hist.pos = hist.ids.length - 1;
  save();
  show(pick);
}

function prev() {
  if (hist.pos <= 0) return;
  hist.pos--;
  save();
  show(byId[hist.ids[hist.pos]]);
}

$("next").addEventListener("click", next);
// Controls fade out over the site and come back on hover (see style.css);
// show them for a moment when Live opens so people know where they are.
document.body.classList.add("peek");
setTimeout(() => document.body.classList.remove("peek"), 2500);
$("prev").addEventListener("click", prev);
addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea, select")) return;
  if (e.key === "ArrowRight") next();
  if (e.key === "ArrowLeft") prev();
});

DL.loadData().then((d) => {
  pool = (d.sites || []).filter((s) => s.embeddable);
  pool.forEach((s) => (byId[s.id] = s));
  DL.setCounts(pool);
  // Drop history entries that are no longer in the data.
  hist.ids = hist.ids.filter((id) => byId[id]);
  hist.pos = Math.min(hist.pos, hist.ids.length - 1);
  const cur = byId[hist.ids[hist.pos]];
  if (cur && DL.inCategory(cur)) {
    show(cur);
  } else {
    hist.ids = hist.ids.slice(0, Math.max(0, hist.pos + 1));
    next();
  }
  DL.onCategory((c) => {
    const active = byId[hist.ids[hist.pos]];
    if (active && DL.inCategory(active, c)) return;
    hist.ids = hist.ids.slice(0, Math.max(0, hist.pos + 1));
    next();
  });
}).catch(() => empty("Couldn't load the site list."));
