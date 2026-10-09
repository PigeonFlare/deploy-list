// Shared bits for every page: the homepage wall of sites, corner dropdowns, liquid glass, data loading.
(function () {
  const ROOT = document.body.dataset.root || "";
  const PAGE = document.body.dataset.page;
  const CATS = [
    { key: "all", label: "All", noun: "projects" },
    { key: "apps", label: "Apps", noun: "apps" },
    { key: "games", label: "Games", noun: "games" },
    { key: "other", label: "Other", noun: "projects" },
  ];
  // New visitors start on Games; the URL leaves out the category only when it's this one.
  const DEFAULT_CAT = "games";
  // Every page can show the last month or just the last week; the choice carries across pages.
  const RANGES = [
    { key: "month", label: "Last month" },
    { key: "week", label: "Last week" },
  ];
  const PAGES = [
    { key: "home", label: "Home", href: ROOT || "./" },
    { key: "live", label: "Live", href: ROOT + "live/" },
    { key: "rankings", label: "Rankings", href: ROOT + "leaderboards/" },
  ];

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
    remove(k) { try { localStorage.removeItem(k); } catch {} },
  };

  // Sites seen in Live, kept across visits, oldest first. Live won't bring one back until
  // every eligible site has been seen; sites that leave the rankings are dropped. Seeing them
  // all turns the Live view button gold for good and starts the list over.
  const VISITED = "deploylist.visited";
  const GOLD = "deploylist.gold";
  function readVisited() {
    try {
      const v = JSON.parse(store.get(VISITED) || "[]");
      return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
    } catch { return []; }
  }
  let visited = readVisited();
  function markVisited(id) {
    visited = visited.filter((x) => x !== id);
    visited.push(id);
    store.set(VISITED, JSON.stringify(visited));
    renderProgress();
  }
  function pruneVisited(d) {
    const ids = new Set(((d && d.sites) || []).map((s) => s.id));
    const kept = visited.filter((id) => ids.has(id));
    if (kept.length !== visited.length) { visited = kept; store.set(VISITED, JSON.stringify(visited)); }
  }
  function clearVisited() {
    visited = [];
    store.remove(VISITED);
    store.remove(GOLD);
    renderProgress();
  }

  // The category and time range carry from page to page within the site, but a refresh, or
  // arriving from anywhere else (a typed address, a bookmark, another site), starts over on
  // Games and Last month, whatever the address says.
  const tab = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch {} },
  };
  const nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
  const fromSite = (() => { try { return new URL(document.referrer).origin === location.origin; } catch { return false; } })();
  if ((nav && nav.type === "reload") || !fromSite) {
    tab.set("deploylist.cat", DEFAULT_CAT);
    tab.set("deploylist.range", "month");
    const url = new URL(location.href);
    url.searchParams.delete("cat");
    url.searchParams.delete("range");
    history.replaceState(history.state, "", url);
  }
  function getCategory() {
    const q = new URLSearchParams(location.search).get("cat");
    const c = q || tab.get("deploylist.cat") || DEFAULT_CAT;
    return CATS.some((x) => x.key === c) ? c : DEFAULT_CAT;
  }

  let category = getCategory();
  const listeners = [];

  function getRange() {
    const r = new URLSearchParams(location.search).get("range") || tab.get("deploylist.range") || "month";
    return RANGES.some((x) => x.key === r) ? r : "month";
  }
  let range = getRange();
  const rangeListeners = [];

  function setRange(r) {
    if (!RANGES.some((x) => x.key === r)) r = "month";
    range = r;
    tab.set("deploylist.range", r);
    const url = new URL(location.href);
    if (r === "month") url.searchParams.delete("range"); else url.searchParams.set("range", r);
    history.replaceState(history.state, "", url);
    renderRangeMenu();
    rangeListeners.forEach((fn) => fn(r));
  }

  function setCategory(c) {
    if (!CATS.some((x) => x.key === c)) c = DEFAULT_CAT;
    category = c;
    tab.set("deploylist.cat", c);
    const url = new URL(location.href);
    if (c === DEFAULT_CAT) url.searchParams.delete("cat"); else url.searchParams.set("cat", c);
    history.replaceState(history.state, "", url);
    renderCategoryMenu();
    listeners.forEach((fn) => fn(c));
  }

  // ---- icons (stroked, 24px grid) ----
  const ICONS = {
    chev: '<path d="M6 9l6 6 6-6"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    ext: '<path d="M8 6h10v10M18 6L6 18"/>',
  };
  function icon(name) {
    return `<svg class="icon ${name}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  }

  // ---- dropdowns ----
  function dropdown(side, id, parent) {
    const wrap = document.createElement("div");
    wrap.className = parent ? "dropdown" : `corner ${side} dropdown`;
    wrap.id = id;
    wrap.innerHTML = `<button class="lg dd-toggle" aria-haspopup="true" aria-expanded="false">
      <span class="dd-label"></span>${icon("chev")}</button>
      <div class="lg frost dd-menu" role="menu"></div>`;
    const btn = wrap.querySelector(".dd-toggle");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !wrap.classList.contains("open");
      closeAll();
      wrap.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", String(open));
    });
    (parent || document.body).appendChild(wrap);
    return wrap;
  }
  function closeAll() {
    document.querySelectorAll(".dropdown.open, .popover.open").forEach((el) => {
      el.classList.remove("open");
    });
    document.querySelectorAll('[aria-expanded="true"]').forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", closeAll);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });

  let catMenu, counts = null, countSites = null;
  function renderCategoryMenu() {
    if (!catMenu) return;
    const cur = CATS.find((c) => c.key === category) || CATS[0];
    const labelEl = catMenu.querySelector(".dd-label");
    if (labelEl) labelEl.innerHTML = cur.label + (counts ? ` ${progress(counts[cur.key])}` : "");
    const menuEl = catMenu.querySelector(".dd-menu");
    if (menuEl) {
      menuEl.innerHTML = CATS.map((c) => `
        <button role="menuitemradio" data-cat="${c.key}" aria-current="${c.key === category}">
          <span>${c.label}${counts ? ` ${progress(counts[c.key])}` : ""}</span>
          ${icon("check")}</button>`).join("");
    }
  }

  let rangeMenu;
  function renderRangeMenu() {
    if (!rangeMenu) return;
    const cur = RANGES.find((r) => r.key === range) || RANGES[0];
    rangeMenu.querySelector(".dd-label").textContent = cur.label;
    rangeMenu.querySelector(".dd-menu").innerHTML = RANGES.map((r) => `
      <button role="menuitemradio" data-range="${r.key}" aria-current="${r.key === range}">
        <span>${r.label}</span>${icon("check")}</button>`).join("");
  }

  function initMenus() {
    // Page menu on the left, category menu on the right (created in that order so
    // keyboard focus moves left to right).
    const nav = dropdown("left", "nav-menu");
    const curPage = PAGES.find((p) => p.key === PAGE) || PAGES[0];
    const navLabel = nav.querySelector(".dd-label");
    if (navLabel) navLabel.textContent = curPage.label;
    const navMenu = nav.querySelector(".dd-menu");
    if (navMenu) {
      navMenu.innerHTML = PAGES.map((p) => `
        <a role="menuitem" href="${p.href}" aria-current="${p.key === PAGE}">
          <span>${p.label}</span>${icon("check")}</a>`).join("");
    }

    // The time menu sits just left of the category menu on every page.
    let right;
    {
      right = document.createElement("div");
      right.className = "corner right corner-group";
      document.body.appendChild(right);
      rangeMenu = dropdown("right", "range-menu", right);
      rangeMenu.querySelector(".dd-menu").addEventListener("click", (e) => {
        const b = e.target.closest("[data-range]");
        if (b) {
          setRange(b.dataset.range);
          closeAll();
        }
      });
      renderRangeMenu();
    }
    catMenu = dropdown("right", "cat-menu", right);
    catMenu.querySelector(".dd-menu").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]");
      if (b) {
        setCategory(b.dataset.cat);
        closeAll();
      }
    });
    renderCategoryMenu();
  }

  // ---- data ----
  let dataPromise;
  function loadData() {
    if (!dataPromise) {
      dataPromise = fetch(ROOT + "data/sites.json", { cache: "no-cache" }) // revalidate so a refresh shows up right away
        .then((r) => {
          if (!r.ok) throw new Error(String(r.status));
          return r.json();
        })
        .then((d) => {
          if (!d || !Array.isArray(d.sites)) d = { ...(d || {}), sites: [] };
          d.sites.forEach((s, i) => (s.id = s.post_url || s.domain || String(i)));
          pruneVisited(d);
          return d;
        })
        .catch((err) => {
          dataPromise = null;
          throw err;
        });
    }
    return dataPromise;
  }
  // The month's ranked sites, or the top sites posted in the 7 days before the data was
  // collected (one per domain, best-voted first). Sites only in the week's list carry
  // "month": false.
  const WEEK = 7 * 24 * 3600;
  function inRange(d, r = range) {
    const sites = (d && d.sites) || [];
    if (r !== "week") return sites.filter((s) => s.month !== false);
    const end = Date.parse(d.generated_at) / 1000 || Date.now() / 1000;
    const seen = new Set();
    return sites
      .filter((s) => s.created >= end - WEEK && !seen.has(s.domain) && seen.add(s.domain))
      .slice(0, 100);
  }
  function inCategory(s, c = category) { return c === "all" || s.category === c; }
  // Each site belongs to exactly one category. With a limit, each category keeps its
  // top `limit` sites and "All" is those lists combined, so the counts add up.
  function ranked(sites, c = category, limit) {
    const keep = (s) => {
      if (!limit) return true;
      const own = sites.filter((x) => x.category === s.category);
      return own.indexOf(s) < limit;
    };
    return sites.filter((s) => inCategory(s, c) && keep(s));
  }
  // Counts are the sites Live can show (x seen of y) in each category of the given list.
  function progress(n) {
    const c = n || { x: 0, y: 0 };
    return `<span class="count${c.y && c.x >= c.y ? " done" : ""}">(${c.x}/${c.y})</span>`;
  }
  function celebrate() {
    const btn = catMenu && catMenu.querySelector(".dd-toggle");
    if (!btn) return;
    btn.classList.remove("complete");
    void btn.offsetWidth;
    btn.classList.add("complete");
    setTimeout(() => btn.classList.remove("complete"), 1000);
  }
    function setCounts(sites) {
    countSites = sites;
    renderProgress();
  }
  function renderProgress() {
    if (!countSites) return;
    const seen = new Set(visited);
    counts = { all: { x: 0, y: 0 } };
    CATS.forEach((c) => {
      if (c.key === "all") return;
      const live = ranked(countSites, c.key).filter((s) => s.embeddable);
      counts[c.key] = { x: live.filter((s) => seen.has(s.id)).length, y: live.length };
      counts.all.x += counts[c.key].x;
      counts.all.y += counts[c.key].y;
    });
    if (counts.all.y && counts.all.x >= counts.all.y) {
      store.set(GOLD, "1");
      visited = [];
      store.remove(VISITED);
      celebrate();
      return renderProgress();
    }
    renderCategoryMenu();
    const tag = document.getElementById("tagline-progress");
    if (tag) tag.outerHTML = progress(counts.all).replace('class="', 'id="tagline-progress" class="');
    const live = document.getElementById("go-live");
    if (live) {
      const done = store.get(GOLD) === "1";
      live.classList.toggle("gold", done);
      live.classList.toggle("tinted", !done);
    }
  }
  // Coming back to a page from the back/forward cache, pick up sites seen since.
  addEventListener("pageshow", (e) => { if (e.persisted) { visited = readVisited(); renderProgress(); } });

  // ---- wall of sites (homepage only) ----
  // Rows of site stills in phone, tablet, laptop and desktop frames, pressed together like
  // bricks. Each row drifts sideways, alternating direction at slightly different speeds.
  // The drift is a CSS animation (style.css), so it stays smooth on phones; it pauses while
  // the tab is hidden and stands still for reduced motion.
  function wall() {
    const el = document.createElement("div");
    el.id = "wall";
    el.setAttribute("aria-hidden", "true");
    document.body.prepend(el);
    // Which still each frame shows; the screen's shape comes from style.css.
    const KINDS = { phone: "phone", tablet: "tablet", laptop: "desktop", desktop: "desktop" };
    const DIRS = { phone: "phone/", tablet: "tablet/", desktop: "" };
    // A mix that leans on laptops and phones, like the flyer.
    const MIX = ["laptop", "phone", "tablet", "laptop", "desktop", "phone", "tablet", "laptop"];
    const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    let pools = null, builtW = 0, builtH = 0;
    const FPS = 30;

    function take(still) {
      const p = pools[still];
      if (!p.list.length) return null;
      const n = p.list[p.i++ % p.list.length];
      return ROOT + "snapshots/" + DIRS[still] + n;
    }

    function build() {
      const vw = innerWidth || 800, vh = innerHeight || 600;
      builtW = vw; builtH = vh;
      const rowH = Math.round(Math.max(110, Math.min(230, vh / 4.6, vw / 2.6)));
      const gap = Math.round(rowH * 0.06);
      el.style.setProperty("--u", (rowH / 204).toFixed(3));
      el.style.setProperty("--gap", gap + "px");
      el.textContent = "";
      const kinds = Object.keys(KINDS).filter((k) => pools[KINDS[k]].list.length);
      if (!kinds.length) return;
      const mix = MIX.filter((k) => kinds.includes(k));
      const rows = Math.ceil((vh + gap) / (rowH + gap)) + 1;
      let k = Math.floor(Math.random() * mix.length);
      for (let r = 0; r < rows; r++) {
        const row = document.createElement("div");
        row.className = "row";
        row.style.height = rowH + "px";
        const track = document.createElement("div");
        track.className = "track";
        row.appendChild(track);
        el.appendChild(row);
        // Fill one half wider than the screen, then repeat it, so sliding by half loops seamlessly.
        while (track.scrollWidth < vw + rowH * 2) {
          const kind = mix[k++ % mix.length];
          const src = take(KINDS[kind]);
          if (!src) break;
          const dev = document.createElement("div");
          dev.className = "dev " + kind;
          const img = new Image();
          img.decoding = "async";
          img.alt = "";
          img.onload = () => img.classList.add("in");
          img.src = src;
          dev.appendChild(img);
          track.appendChild(dev);
        }
        const half = track.scrollWidth;
        for (const d of [...track.children]) {
          const c = d.cloneNode(true);
          c.firstChild.onload = () => c.firstChild.classList.add("in");
          track.appendChild(c);
        }
        // 14 to 24 px a second, every other row the other way, each from its own starting point.
        // Every row steps on one shared 30 fps clock, so the compositor redraws the wall half as often.
        const steps = Math.round((half / (14 + Math.random() * 10)) * FPS);
        track.style.animationDuration = steps / FPS + "s";
        track.style.animationTimingFunction = `steps(${steps})`;
        track.style.animationDelay = -Math.floor(Math.random() * steps) / FPS + "s";
        if (r % 2) track.style.animationDirection = "reverse";
      }
      // Start every row on the same frame so their steps line up.
      requestAnimationFrame(() => {
        const t = document.timeline.currentTime;
        el.getAnimations({ subtree: true }).forEach((a) => { if (a.animationName === "wall-drift") a.startTime = t; });
      });
    }

    fetch(ROOT + "snapshots/index.json")
      .then((r) => (r.ok ? r.json() : {}))
      .then((index) => {
        if (Array.isArray(index)) index = { desktop: index }; // older single-list index
        const ok = (a) => (Array.isArray(a) ? a.filter((n) => /^[\w.-]+\.jpg$/.test(n)) : []);
        pools = {};
        for (const still of Object.keys(DIRS)) pools[still] = { list: shuffle(ok(index[still])), i: 0 };
        build();
      })
      .catch(() => {});

    // Rebuild when the width changes, or the height grows past the rows (a phone's address bar
    // coming and going only nudges the height, so that alone leaves the wall be).
    let timer = 0;
    addEventListener("resize", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (pools && (Math.abs(innerWidth - builtW) > 40 || innerHeight > builtH + 120)) build();
      }, 200);
    }, { passive: true });
    const pause = () => el.classList.toggle("paused", document.hidden);
    document.addEventListener("visibilitychange", pause);
    pause();
  }

  // Only ever hand http(s) URLs from the data to links and the frame.
  function safeUrl(u) {
    try {
      const x = new URL(u);
      if (x.protocol === "https:" || x.protocol === "http:") {
        // Disallow credential-carrying URLs
        if (x.username || x.password) return "about:blank";
        return x.href;
      }
      return "about:blank";
    } catch {
      return "about:blank";
    }
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  // ---- liquid glass ----
  // Chromium can run an SVG filter as a backdrop filter, so there the top buttons
  // bend what's behind them at the rim like a lens. Each button gets a displacement
  // map drawn for its exact size and corner radius. Safari and Firefox keep the
  // CSS blur, rim and sheen from style.css.
  function liquidGlass() {
    const supported = !!navigator.userAgentData && window.CSS && CSS.supports("backdrop-filter", "url(#lg)") &&
      !matchMedia("(prefers-reduced-transparency: reduce)").matches;
    if (!supported || !window.ResizeObserver) return;
    const NS = "http://www.w3.org/2000/svg";
    const defs = document.createElementNS(NS, "svg");
    defs.setAttribute("class", "lg-defs");
    defs.setAttribute("aria-hidden", "true");
    defs.setAttribute("width", "0");
    defs.setAttribute("height", "0");
    document.body.appendChild(defs);
    const filters = new Map();

    // Red/green encode where each pixel samples the backdrop from: 128 is "straight
    // through"; within the bezel the sample is pulled toward the center, strongest at the edge.
    function displacementMap(w, h, r) {
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const ctx = c.getContext("2d");
      const img = ctx.createImageData(w, h), d = img.data;
      const bezel = Math.max(4, Math.min(r, 18, h / 2, w / 2));
      const hw = w / 2, hh = h / 2;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const px = x + 0.5 - hw, py = y + 0.5 - hh;
          const qx = Math.abs(px) - (hw - r), qy = Math.abs(py) - (hh - r);
          let nx = 0, ny = 0, dist;
          if (qx > 0 && qy > 0) { const l = Math.hypot(qx, qy); dist = r - l; nx = qx / l; ny = qy / l; }
          else if (qx > qy) { dist = r - qx; nx = 1; }
          else { dist = r - qy; ny = 1; }
          nx *= px < 0 ? -1 : 1; ny *= py < 0 ? -1 : 1;
          let m = 0;
          if (dist < bezel) { const t = Math.max(0, dist) / bezel; m = (1 - t) * (1 - t); }
          const i = (y * w + x) * 4;
          d[i] = 128 - nx * m * 127; d[i + 1] = 128 - ny * m * 127; d[i + 2] = 128; d[i + 3] = 255;
        }
      }
      ctx.putImageData(img, 0, 0);
      return c.toDataURL();
    }

    function filterFor(w, h, r, blur) {
      const key = `${w}x${h}x${r}x${blur}`;
      if (filters.has(key)) return filters.get(key);
      const id = "lg-" + filters.size;
      const f = document.createElementNS(NS, "filter");
      f.id = id;
      for (const [k, v] of Object.entries({ x: 0, y: 0, width: w, height: h, filterUnits: "userSpaceOnUse", "color-interpolation-filters": "sRGB" })) f.setAttribute(k, v);
      f.innerHTML = `<feGaussianBlur in="SourceGraphic" stdDeviation="${blur}" result="soft"/>
        <feImage href="${displacementMap(w, h, r)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>
        <feDisplacementMap in="soft" in2="map" scale="${Math.round(Math.min(48, h * 0.75))}" xChannelSelector="R" yChannelSelector="G"/>`;
      defs.appendChild(f);
      filters.set(key, id);
      return id;
    }

    function apply(el) {
      const w = el.offsetWidth, h = el.offsetHeight;
      if (!w || !h) return;
      const cs = getComputedStyle(el);
      const raw = cs.borderTopLeftRadius;
      let r = parseFloat(raw) || 0;
      if (raw.endsWith("%")) r = (r / 100) * Math.min(w, h);
      r = Math.round(Math.min(r, w / 2, h / 2));
      const blur = parseFloat(cs.getPropertyValue("--lg-blur")) || 1;
      el.style.backdropFilter = `url(#${filterFor(w, h, r, blur)}) saturate(170%)`;
    }

    const ro = new ResizeObserver((entries) => entries.forEach((e) => apply(e.target)));
    document.querySelectorAll(".lg").forEach((el) => ro.observe(el));
  }

  // ---- glass lighting ----
  // One light sits above the top center of the window. Each glass button's rim glint
  // (style.css) slides along its top edge toward that light and keeps about the same
  // size whatever the button's width, the shading tilts with it, and buttons farther
  // from it catch a little less.
  function lightRims() {
    const els = document.querySelectorAll(".lg");
    if (!els.length) return;
    function aim() {
      const vw = innerWidth, vh = innerHeight, lx = vw / 2, ly = -0.4 * vh;
      els.forEach((el) => {
        const b = el.getBoundingClientRect();
        if (!b.width) return;
        const dx = (lx - (b.left + b.width / 2)) / vw;          // -0.5 … 0.5
        const dy = (b.top + b.height / 2 - ly) / vh;            // 0.4 … 1.4
        const x = Math.max(10, Math.min(90, 50 + dx * 110));
        el.style.setProperty("--lg-lx", x.toFixed(1) + "%");
        el.style.setProperty("--lg-lw", Math.max(28, Math.min(60, 3600 / b.width)).toFixed(1) + "%");
        el.style.setProperty("--lg-la", (180 + Math.atan2(dx * vw, dy * vh) * 90 / Math.PI).toFixed(1) + "deg");
        el.style.setProperty("--lg-li", Math.max(0.7, 1.12 - dy * 0.3).toFixed(2));
      });
    }
    let queued = false;
    const later = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; aim(); }); } };
    aim();
    addEventListener("resize", later);
    addEventListener("scroll", later, { passive: true });
    addEventListener("animationend", later);
    if (window.ResizeObserver) { const ro = new ResizeObserver(later); els.forEach((el) => ro.observe(el)); }
  }

  window.DL = {
    ROOT, CATS, store, loadData, markVisited, clearVisited,
    get visited() { return visited; }, inRange, inCategory, ranked, setCounts, safeUrl, esc, icon,
    get category() { return category; },
    DEFAULT_CAT,
    get range() { return range; },
    onCategory(fn) { listeners.push(fn); },
    onRange(fn) { rangeListeners.push(fn); },
  };

  // Homepage intro (style.css): start it once fonts are in and the page has painted, and
  // replay it when the page comes back from the back/forward cache.
  function playIntro() {
    // fonts.ready only covers fonts the page has already asked for, so let a frame lay the
    // page out first; otherwise the fonts swap in mid-intro and everything jolts.
    // A font that hangs holds the intro for a second at most.
    const start = () => requestAnimationFrame(() => document.body.classList.add("intro"));
    requestAnimationFrame(() => requestAnimationFrame(() => {
      Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 1000))]).then(start, start);
    }));
    addEventListener("pageshow", (e) => {
      if (!e.persisted) return;
      document.getAnimations().forEach((a) => { if (a.animationName === "pop-in") a.currentTime = 0; });
    });
  }

  if (PAGE === "home") { wall(); playIntro(); }
  initMenus();
  liquidGlass();
  lightRims();
})();
