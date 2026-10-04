// Shared bits for every page: hyperspace background, corner dropdowns, data loading.
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

  // ---- dropdowns ----
  function dropdown(side, id) {
    const wrap = document.createElement("div");
    wrap.className = `corner ${side} dropdown`;
    wrap.id = id;
    wrap.innerHTML = `<button class="glass dd-toggle" aria-haspopup="true" aria-expanded="false">
      <span class="caret" aria-hidden="true">▼</span><span class="dd-label"></span></button>
      <div class="glass dd-menu" role="menu"></div>`;
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
          <span class="check" aria-hidden="true">✓</span></button>`).join("");
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
          <span>${p.label}</span><span class="check" aria-hidden="true">✓</span></a>`).join("");
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
  function setCounts(sites, limit) {
    counts = {};
    CATS.forEach((c) => {
      const n = sites.filter((s) => inCategory(s, c.key)).length;
      counts[c.key] = limit ? Math.min(n, limit) : n;
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
    document.body.prepend(veil);
    document.body.prepend(canvas);
    const ctx = canvas.getContext("2d", { alpha: false });
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
      w = canvas.width = Math.max(1, Math.floor((innerWidth || 800) * dpr));
      h = canvas.height = Math.max(1, Math.floor((innerHeight || 600) * dpr));
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
    function readColors() {
      const cs = getComputedStyle(document.documentElement);
      star = cs.getPropertyValue("--star").trim() || "225, 60%, 30%";
      space = cs.getPropertyValue("--space").trim() || "#eef1f7";
      const rgb = parseHex(space);
      fade = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.35)`;
      bucketStyles.length = 0;
      for (let b = 0; b < BUCKETS; b++) {
        const t = (b + 0.5) / BUCKETS;
        bucketStyles.push(`hsla(${star},${Math.min(1, t * t * 2.4)})`);
      }
    }
    readColors();
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readColors);

    let last = performance.now();
    let animId = null;

    function renderFrame(now) {
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

  window.DL = {
    ROOT, CATS, store, loadData, inCategory, setCounts, safeUrl, esc,
    get category() { return category; },
    onCategory(fn) { listeners.push(fn); },
  };

  if (PAGE === "home") hyperspace();
  initMenus();
})();
