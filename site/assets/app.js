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
      <span class="caret">▼</span><span class="dd-label"></span></button>
      <div class="glass dd-menu" role="menu"></div>`;
    const btn = wrap.querySelector(".dd-toggle");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !wrap.classList.contains("open");
      closeAll();
      wrap.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open);
    });
    document.body.appendChild(wrap);
    return wrap;
  }
  function closeAll() {
    document.querySelectorAll(".dropdown.open, .popover.open").forEach((el) => {
      el.classList.remove("open");
      el.querySelector(".dd-toggle")?.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", closeAll);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

  let catMenu, counts = null;
  function renderCategoryMenu() {
    if (!catMenu) return;
    const cur = CATS.find((c) => c.key === category);
    catMenu.querySelector(".dd-label").textContent = cur.label;
    catMenu.querySelector(".dd-menu").innerHTML = CATS.map((c) => `
      <button role="menuitemradio" data-cat="${c.key}" aria-current="${c.key === category}">
        <span>${c.label}${counts ? ` <span class="count">(${counts[c.key] || 0})</span>` : ""}</span>
        <span class="check">✓</span></button>`).join("");
  }

  function initMenus() {
    catMenu = dropdown("left", "cat-menu");
    catMenu.querySelector(".dd-menu").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]");
      if (b) setCategory(b.dataset.cat);
    });
    renderCategoryMenu();

    const nav = dropdown("right", "nav-menu");
    nav.querySelector(".dd-label").textContent = PAGES.find((p) => p.key === PAGE).label;
    nav.querySelector(".dd-menu").innerHTML = PAGES.map((p) => `
      <a role="menuitem" href="${p.href}" aria-current="${p.key === PAGE}">
        <span>${p.label}</span><span class="check">✓</span></a>`).join("");
  }

  // ---- data ----
  let dataPromise;
  function loadData() {
    dataPromise ||= fetch(ROOT + "data/sites.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => { d.sites.forEach((s, i) => (s.id = s.domain || String(i))); return d; });
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
    const ctx = canvas.getContext("2d");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w, h, cx, cy, dpr, stars = [];
    const N = 1100, DEPTH = 1000;

    function newStar(fresh) {
      // Keep stars off the exact center line, where they'd pile up into a bright blob.
      const a = Math.random() * Math.PI * 2, r = 12 + Math.sqrt(Math.random()) * 220;
      return {
        x: Math.cos(a) * r, y: Math.sin(a) * r,
        z: fresh ? Math.random() * DEPTH : DEPTH, pz: 0,
      };
    }
    function resize() {
      dpr = Math.min(devicePixelRatio || 1, 2);
      w = canvas.width = innerWidth * dpr;
      h = canvas.height = innerHeight * dpr;
      cx = w / 2; cy = h / 2;
    }
    resize();
    addEventListener("resize", resize);
    for (let i = 0; i < N; i++) { const s = newStar(true); s.pz = s.z; stars.push(s); }

    // Colors come from CSS so the field follows light/dark mode.
    let star = "", space = "";
    function readColors() {
      const cs = getComputedStyle(document.documentElement);
      star = cs.getPropertyValue("--star").trim();
      space = cs.getPropertyValue("--space").trim();
      const [r, g, b] = space.match(/\w\w/g).map((h) => parseInt(h, 16));
      fade = `rgba(${r},${g},${b},0.35)`;
    }
    let fade;
    readColors();
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readColors);

    let last = performance.now();
    function frame(now) {
      const dt = Math.min(50, now - last); last = now;
      const speed = 0.09 * dt;
      ctx.fillStyle = fade;
      ctx.fillRect(0, 0, w, h);
      const scale = Math.max(w, h) * 0.5;
      for (const s of stars) {
        s.pz = s.z;
        s.z -= speed * (1 + (DEPTH - s.z) / 400);
        if (s.z < 1) { Object.assign(s, newStar(false)); s.pz = s.z; continue; }
        const x = cx + (s.x / s.z) * scale * 2, y = cy + (s.y / s.z) * scale * 2;
        let px = cx + (s.x / s.pz) * scale * 2, py = cy + (s.y / s.pz) * scale * 2;
        // Cap streak length so near stars read as streaks, not lines across the screen.
        const dx = x - px, dy = y - py, len = Math.hypot(dx, dy), cap = 26 * dpr;
        if (len > cap) { px = x - (dx / len) * cap; py = y - (dy / len) * cap; }
        if (x < -50 || x > w + 50 || y < -50 || y > h + 50) { Object.assign(s, newStar(false)); s.pz = s.z; continue; }
        const t = 1 - s.z / DEPTH;
        ctx.strokeStyle = `hsla(${star},${Math.min(1, t * t * 2.4)})`;
        ctx.lineCap = "round";
        ctx.lineWidth = (0.8 + t * 1.8) * dpr;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
      }
      if (!reduce) requestAnimationFrame(frame);
    }
    ctx.fillStyle = space; ctx.fillRect(0, 0, w, h);
    if (reduce) { for (let i = 0; i < 6; i++) frame(last + 16 * i); } else requestAnimationFrame(frame);
  }

  window.DL = {
    ROOT, CATS, store, loadData, inCategory, setCounts,
    get category() { return category; },
    onCategory(fn) { listeners.push(fn); },
    esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); },
  };

  if (PAGE === "home") hyperspace();
  initMenus();
})();
