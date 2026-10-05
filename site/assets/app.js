// Shared bits for every page: hyperspace background, corner dropdowns, liquid glass, data loading.
(function () {
  const ROOT = document.body.dataset.root || "";
  const PAGE = document.body.dataset.page;
  const CATS = [
    { key: "all", label: "All", noun: "projects" },
    { key: "apps", label: "Apps", noun: "apps" },
    { key: "games", label: "Games", noun: "games" },
    { key: "other", label: "Other", noun: "projects" },
  ];
  const PAGES = [
    { key: "home", label: "Home", href: ROOT || "./" },
    { key: "rankings", label: "Rankings", href: ROOT + "leaderboards/" },
    { key: "live", label: "Live", href: ROOT + "live/" },
  ];

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };

  function getCategory() {
    const q = new URLSearchParams(location.search).get("cat");
    const c = q || store.get("deploylist.cat") || "all";
    return CATS.some((x) => x.key === c) ? c : "all";
  }

  let category = getCategory();
  const listeners = [];

  function setCategory(c) {
    if (!CATS.some((x) => x.key === c)) c = "all";
    category = c;
    store.set("deploylist.cat", c);
    const url = new URL(location.href);
    if (c === "all") url.searchParams.delete("cat"); else url.searchParams.set("cat", c);
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
  function dropdown(side, id) {
    const wrap = document.createElement("div");
    wrap.className = `corner ${side} dropdown`;
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
    document.body.appendChild(wrap);
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

  let catMenu, counts = null;
  function renderCategoryMenu() {
    if (!catMenu) return;
    const cur = CATS.find((c) => c.key === category) || CATS[0];
    const labelEl = catMenu.querySelector(".dd-label");
    if (labelEl) labelEl.textContent = cur.label;
    const menuEl = catMenu.querySelector(".dd-menu");
    if (menuEl) {
      menuEl.innerHTML = CATS.map((c) => `
        <button role="menuitemradio" data-cat="${c.key}" aria-current="${c.key === category}">
          <span>${c.label}${counts ? ` <span class="count">(${counts[c.key] || 0})</span>` : ""}</span>
          ${icon("check")}</button>`).join("");
    }
  }

  function initMenus() {
    catMenu = dropdown("left", "cat-menu");
    catMenu.querySelector(".dd-menu").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]");
      if (b) {
        setCategory(b.dataset.cat);
        closeAll();
      }
    });
    renderCategoryMenu();

    const nav = dropdown("right", "nav-menu");
    const curPage = PAGES.find((p) => p.key === PAGE) || PAGES[0];
    const navLabel = nav.querySelector(".dd-label");
    if (navLabel) navLabel.textContent = curPage.label;
    const navMenu = nav.querySelector(".dd-menu");
    if (navMenu) {
      navMenu.innerHTML = PAGES.map((p) => `
        <a role="menuitem" href="${p.href}" aria-current="${p.key === PAGE}">
          <span>${p.label}</span>${icon("check")}</a>`).join("");
    }
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
          d.sites.forEach((s, i) => (s.id = s.domain || String(i)));
          return d;
        })
        .catch((err) => {
          dataPromise = null;
          throw err;
        });
    }
    return dataPromise;
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
  function setCounts(sites, limit) {
    counts = { all: 0 };
    CATS.forEach((c) => {
      if (c.key === "all") return;
      counts[c.key] = ranked(sites, c.key, limit).length;
      counts.all += counts[c.key];
    });
    renderCategoryMenu();
  }

  // ---- hyperspace ----
  function hyperspace() {
    const canvas = document.createElement("canvas");
    canvas.id = "hyperspace";
    canvas.setAttribute("aria-hidden", "true");
    const veil = document.createElement("div");
    veil.className = "veil";
    // Snapshots of ranked sites fly past on their own layer, cleared every frame,
    // so they don't smear like the star trails do.
    const snapCanvas = document.createElement("canvas");
    snapCanvas.id = "snapshots";
    snapCanvas.setAttribute("aria-hidden", "true");
    document.body.prepend(veil);
    document.body.prepend(snapCanvas);
    document.body.prepend(canvas);
    const ctx = canvas.getContext("2d", { alpha: false });
    const sctx = snapCanvas.getContext("2d");
    const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
    let reduce = motionQuery.matches;
    let w = 0, h = 0, cx = 0, cy = 0, dpr = 1, stars = [];
    const DEPTH = 1000;
    const N = Math.round(Math.min(1100, Math.max(350, ((innerWidth || 800) * (innerHeight || 600)) / 900)));

    function resetStar(s, fresh) {
      // Keep stars off the exact center line, where they'd pile up into a bright blob.
      const a = Math.random() * Math.PI * 2, r = 12 + Math.sqrt(Math.random()) * 220;
      s.x = Math.cos(a) * r;
      s.y = Math.sin(a) * r;
      s.z = fresh ? Math.random() * DEPTH : DEPTH;
      s.pz = s.z;
    }

    const BUCKETS = 8;
    const paths = Array.from({ length: BUCKETS }, () => []);
    const bucketStyles = [];
    const bucketWidths = new Float32Array(BUCKETS);

    function updateBucketWidths() {
      for (let b = 0; b < BUCKETS; b++) {
        const t = (b + 0.5) / BUCKETS;
        bucketWidths[b] = (0.8 + t * 1.8) * dpr;
      }
    }

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.width = snapCanvas.width = Math.max(1, Math.floor((innerWidth || 800) * dpr));
      h = canvas.height = snapCanvas.height = Math.max(1, Math.floor((innerHeight || 600) * dpr));
      cx = w / 2; cy = h / 2;
      updateBucketWidths();
    }
    resize();
    let resizeTimer;
    addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 150);
    }, { passive: true });

    for (let i = 0; i < N; i++) {
      const s = { x: 0, y: 0, z: 0, pz: 0 };
      resetStar(s, true);
      stars.push(s);
    }

    // Colors come from CSS so the field follows light/dark mode.
    let star = "225, 60%, 30%", space = "#eef1f7", fade = "rgba(238,241,247,0.35)";
    function parseHex(hex) {
      hex = (hex || "").replace("#", "").trim();
      if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
      if (hex.length >= 6) {
        return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
      }
      return [238, 241, 247];
    }
    // Safari can run this before the stylesheet's variables resolve, which used to leave
    // light-mode colors painted under dark-mode text. Fall back by the system theme, and
    // read again once the page has loaded or is restored from the back/forward cache.
    const darkQuery = matchMedia("(prefers-color-scheme: dark)");
    let colorsResolved = false;
    function readColors() {
      const cs = getComputedStyle(document.documentElement);
      const dark = darkQuery.matches;
      colorsResolved = !!cs.getPropertyValue("--space").trim();
      star = cs.getPropertyValue("--star").trim() || (dark ? "214, 90%, 84%" : "228, 62%, 26%");
      space = cs.getPropertyValue("--space").trim() || (dark ? "#04050b" : "#dde3f0");
      const rgb = parseHex(space);
      fade = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.35)`;
      bucketStyles.length = 0;
      for (let b = 0; b < BUCKETS; b++) {
        const t = (b + 0.5) / BUCKETS;
        bucketStyles.push(`hsla(${star},${Math.min(1, t * t * 2.4)})`);
      }
    }
    function refreshColors() {
      const before = space;
      readColors();
      if (space !== before) { ctx.fillStyle = space; ctx.fillRect(0, 0, w, h); }
    }
    readColors();
    darkQuery.addEventListener("change", refreshColors);
    addEventListener("load", refreshColors);
    addEventListener("pageshow", refreshColors);

    // ---- site snapshots ----
    const pics = [], cards = [];
    const MAX_CARDS = 8, CARD_W = 34, CARD_H = CARD_W * 0.625; // world units; stills are 16:10
    let spawnIn = 600;
    fetch(ROOT + "snapshots/index.json")
      .then((r) => (r.ok ? r.json() : []))
      .then((names) => {
        if (!Array.isArray(names)) return;
        // Shuffle, then load a handful at a time as they're needed.
        names = names.filter((n) => /^[\w.-]+\.jpg$/.test(n)).sort(() => Math.random() - 0.5).slice(0, 80);
        names.forEach((n) => {
          const img = new Image();
          img.decoding = "async";
          img.onload = () => pics.push(img);
          img.src = ROOT + "snapshots/" + n;
        });
      })
      .catch(() => {});

    function spawnCard() {
      if (!pics.length || cards.length >= MAX_CARDS) return;
      const used = new Set(cards.map((c) => c.img));
      const free = pics.filter((p) => !used.has(p));
      if (!free.length) return;
      // Start away from the center so cards pass beside the title rather than through it.
      const a = Math.random() * Math.PI * 2, r = 130 + Math.random() * 100;
      cards.push({ img: free[Math.floor(Math.random() * free.length)], x: Math.cos(a) * r, y: Math.sin(a) * r * 0.6, z: DEPTH });
    }

    function drawCards(dt, speed) {
      sctx.clearRect(0, 0, w, h);
      if (reduce) return;
      spawnIn -= dt;
      if (spawnIn <= 0) { spawnCard(); spawnIn = 350 + Math.random() * 450; }
      const scale = Math.max(w, h);
      for (let i = cards.length - 1; i >= 0; i--) {
        const c = cards[i];
        c.z -= speed * 0.85 * (1 + (DEPTH - c.z) / 400); // nearly star speed
        const k = scale / c.z;
        const cw = CARD_W * k, ch = CARD_H * k;
        const x = cx + c.x * k - cw / 2, y = cy + c.y * k - ch / 2;
        if (c.z < 20 || x > w || y > h || x + cw < 0 || y + ch < 0) { cards.splice(i, 1); continue; }
        // Fade in from the distance.
        sctx.globalAlpha = Math.min(1, (DEPTH - c.z) / 150) * 0.92;
        const rad = Math.min(cw, ch) * 0.07;
        sctx.save();
        sctx.beginPath();
        sctx.roundRect(x, y, cw, ch, rad);
        sctx.clip();
        sctx.drawImage(c.img, x, y, cw, ch);
        sctx.restore();
        sctx.lineWidth = Math.max(1, dpr);
        sctx.strokeStyle = "rgba(255,255,255,0.35)";
        sctx.beginPath();
        sctx.roundRect(x, y, cw, ch, rad);
        sctx.stroke();
      }
      sctx.globalAlpha = 1;
    }

    let last = performance.now();
    let animId = null;

    function renderFrame(now) {
      if (!colorsResolved) refreshColors(); // keep checking until the stylesheet's colors are in
      const dt = Math.min(50, now - last);
      last = now;
      const speed = 0.09 * dt;
      ctx.fillStyle = fade;
      ctx.fillRect(0, 0, w, h);
      const scale = Math.max(w, h), cap = 26 * dpr;
      for (const p of paths) p.length = 0;
      for (const s of stars) {
        s.pz = s.z;
        s.z -= speed * (1 + (DEPTH - s.z) / 400);
        if (s.z < 1) { resetStar(s, false); continue; }
        const x = cx + (s.x / s.z) * scale, y = cy + (s.y / s.z) * scale;
        if (x < -50 || x > w + 50 || y < -50 || y > h + 50) { resetStar(s, false); continue; }
        const t = 1 - s.z / DEPTH;
        if (t < 0.1) continue; // too faint to see
        let px = cx + (s.x / s.pz) * scale, py = cy + (s.y / s.pz) * scale;
        // Cap streak length so near stars read as streaks, not lines across the screen.
        const dx = x - px, dy = y - py, len = Math.hypot(dx, dy);
        if (len > cap && len > 0) { px = x - (dx / len) * cap; py = y - (dy / len) * cap; }
        paths[Math.min(BUCKETS - 1, Math.floor(t * BUCKETS))].push(px, py, x, y);
      }
      ctx.lineCap = "round";
      for (let b = 0; b < BUCKETS; b++) {
        const pts = paths[b];
        if (!pts.length) continue;
        ctx.strokeStyle = bucketStyles[b];
        ctx.lineWidth = bucketWidths[b];
        ctx.beginPath();
        for (let i = 0; i < pts.length; i += 4) { ctx.moveTo(pts[i], pts[i + 1]); ctx.lineTo(pts[i + 2], pts[i + 3]); }
        ctx.stroke();
      }
      drawCards(dt, speed);
    }

    function loop(now) {
      renderFrame(now);
      if (!reduce && !document.hidden) {
        animId = requestAnimationFrame(loop);
      } else {
        animId = null;
      }
    }

    function startAnim() {
      if (animId !== null || reduce || document.hidden) return;
      last = performance.now();
      animId = requestAnimationFrame(loop);
    }

    function stopAnim() {
      if (animId !== null) {
        cancelAnimationFrame(animId);
        animId = null;
      }
    }

    ctx.fillStyle = space;
    ctx.fillRect(0, 0, w, h);
    if (reduce) {
      for (let i = 0; i < 6; i++) renderFrame(last + 16 * i);
    } else {
      startAnim();
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopAnim();
      } else {
        startAnim();
      }
    });

    motionQuery.addEventListener("change", (e) => {
      reduce = e.matches;
      if (reduce) {
        stopAnim();
        for (let i = 0; i < 6; i++) renderFrame(last + 16 * i);
      } else {
        startAnim();
      }
    });
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

  window.DL = {
    ROOT, CATS, store, loadData, inCategory, ranked, setCounts, safeUrl, esc, icon,
    get category() { return category; },
    onCategory(fn) { listeners.push(fn); },
  };

  if (PAGE === "home") hyperspace();
  initMenus();
  liquidGlass();
})();
