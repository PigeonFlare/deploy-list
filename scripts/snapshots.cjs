// Captures small stills of each ranked site for the homepage's wall of devices (a desktop,
// a tablet and a phone view, as each looks in Live view on that screen), and checks that
// each site marked for Live view really runs inside a frame (some pass the header check but
// refuse in script, e.g. "Not executing in a top-level window"); those are taken out of Live,
// marked "down" when the site itself doesn't load and "iframe" when only framing fails.
// Stills are kept until their site leaves the rankings, so a refresh only visits new sites.
// Usage: node scripts/snapshots.cjs  (needs playwright-core; set CHROME_PATH to use an installed Chrome)
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const SITE = path.join(__dirname, "..", "site");
const OUT = path.join(SITE, "snapshots");
const DEADLINE = Date.now() + 8 * 60 * 1000; // whole run
const CONCURRENCY = 6;

const name = (domain) => domain.replace(/[^a-z0-9.-]/gi, "_") + ".jpg";
// Desktop stills sit in snapshots/ itself (the laptop and desktop frames share them),
// the others in a folder each. A page is rendered at a fraction of its size, so a desktop
// still is 640x400, a tablet one 328x472 and a phone one 195x422.
const VARIANTS = [
  { key: "desktop", dir: "", viewport: { width: 1280, height: 800 }, scale: 0.5 },
  { key: "tablet", dir: "tablet", viewport: { width: 820, height: 1180 }, scale: 0.4, mobile: "" },
  { key: "phone", dir: "phone", viewport: { width: 390, height: 844 }, scale: 0.5, mobile: " Mobile" },
];
const fileOf = (v, domain) => path.join(OUT, v.dir, name(domain));
// Script errors that mean a page won't run framed.
const FRAME_ERROR = /top-level|\btop\b|frame|parent|cross-origin|SecurityError|sandbox/i;
// Same sandbox as Live view's iframe.
const SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-pointer-lock allow-modals";

(async () => {
  const DATA = path.join(SITE, "data", "sites.json");
  const data = JSON.parse(fs.readFileSync(DATA, "utf8"));
  const sites = (data.sites || []).filter((s) => typeof s.url === "string" && s.url.startsWith("https://") && s.domain);
  const wanted = new Set(sites.map((s) => name(s.domain)));
  for (const v of VARIANTS) {
    const dir = path.join(OUT, v.dir);
    fs.mkdirSync(dir, { recursive: true });
    for (const f of fs.readdirSync(dir)) {
      if (f.endsWith(".jpg") && !wanted.has(f)) fs.unlinkSync(path.join(dir, f));
    }
  }

  const todo = VARIANTS.flatMap((v) => sites.filter((s) => !fs.existsSync(fileOf(v, s.domain))).map((s) => [v, s]));
  const framed = sites.filter((s) => s.embeddable);
  // The scraper's own request can fail on TLS or bot checks a browser gets through, so a
  // site it found down only stays down if Chrome can't load it either.
  const down = sites.filter((s) => s.live_issue === "down");
  let changed = 0;
  if (todo.length || framed.length || down.length) {
    const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
    const chrome = browser.version().split(".")[0];
    const contexts = {};
    for (const v of VARIANTS) {
      contexts[v.key] = await browser.newContext({
        viewport: v.viewport, deviceScaleFactor: v.scale,
        // Tablets and phones get a touch screen and a mobile Chrome user agent, so sites
        // serve the layout they would to a real one.
        ...(v.mobile !== undefined && {
          isMobile: true, hasTouch: true,
          userAgent: `Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chrome}.0.0.0${v.mobile} Safari/537.36`,
        }),
        serviceWorkers: "block", acceptDownloads: false, permissions: [],
      });
    }
    const context = contexts.desktop;
    // Record script errors in every frame, so the frame check can read them.
    await context.addInitScript(() => {
      window.__dlErrors = [];
      const push = (m) => { try { window.__dlErrors.push(String(m)); } catch {} };
      addEventListener("error", (e) => push(e.message || e.error), true);
      addEventListener("unhandledrejection", (e) => push((e.reason && e.reason.message) || e.reason));
    });

    async function snapshot(v, s) {
      const page = await contexts[v.key].newPage();
      try {
        await page.goto(s.url, { waitUntil: "load", timeout: 20000 });
        await page.waitForTimeout(2500); // let fonts, images and intro animations settle
        await page.screenshot({ path: fileOf(v, s.domain), type: "jpeg", quality: 72, timeout: 10000 });
        console.log(`snapshot (${v.key}): ${s.domain}`);
      } catch (e) {
        console.warn(`warn: no ${v.key} snapshot for ${s.domain}: ${String(e.message || e).split("\n")[0]}`);
      } finally {
        await page.close().catch(() => {});
      }
    }

    async function loadsOnItsOwn(url) {
      const page = await context.newPage();
      try {
        const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
        const code = res ? res.status() : 0;
        return code > 0 && code !== 404 && code !== 410 && code < 500;
      } catch {
        return false;
      } finally {
        await page.close().catch(() => {});
      }
    }

    async function frameCheck(s) {
      const page = await context.newPage();
      try {
        const src = s.url.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
        await page.setContent(`<iframe src="${src}" sandbox="${SANDBOX}" style="width:1280px;height:800px;border:0"></iframe>`);
        await page.waitForTimeout(6000);
        const frame = page.frames().find((f) => f !== page.mainFrame());
        if (!frame) return;
        const errors = await frame.evaluate(() => window.__dlErrors || []).catch(() => []);
        const blocked = frame.url().startsWith("chrome-error:");
        const bad = errors.find((m) => FRAME_ERROR.test(m));
        if (blocked || bad) {
          // A frame error page looks the same whether the site is offline or refuses
          // framing, so open it normally to tell which.
          const down = blocked && !(await loadsOnItsOwn(s.url));
          s.embeddable = false;
          s.live_issue = down ? "down" : "iframe";
          changed++;
          console.log(`not in Live: ${s.domain} (${down ? "site doesn't load" : blocked ? "refused to load in a frame" : bad})`);
        }
      } catch (e) {
        console.warn(`warn: frame check skipped for ${s.domain}: ${String(e.message || e).split("\n")[0]}`);
      } finally {
        await page.close().catch(() => {});
      }
    }

    async function downCheck(s) {
      if (!(await loadsOnItsOwn(s.url))) return;
      s.embeddable = true;
      delete s.live_issue;
      changed++;
      console.log(`back up: ${s.domain}`);
      await frameCheck(s);
    }

    const jobs = [
      ...todo.map(([v, s]) => () => snapshot(v, s)),
      ...framed.map((s) => () => frameCheck(s)),
      ...down.map((s) => () => downCheck(s)),
    ];
    let next = 0;
    async function worker() {
      while (next < jobs.length && Date.now() < DEADLINE) await jobs[next++]();
    }
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    await browser.close();
  }
  if (changed) fs.writeFileSync(DATA, JSON.stringify(data));

  // index.json lists the stills of each kind: {"desktop": [...], "tablet": [...], "phone": [...]}.
  const domains = sites.map((s) => s.domain).filter((d, i, all) => all.indexOf(d) === i);
  const index = {};
  for (const v of VARIANTS) {
    index[v.key] = domains.filter((d) => fs.existsSync(fileOf(v, d))).map(name);
    console.log(`${index[v.key].length} ${v.key} snapshots`);
  }
  fs.writeFileSync(path.join(OUT, "index.json"), JSON.stringify(index));
})();
