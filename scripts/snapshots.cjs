// Captures a small still of each ranked site for the homepage's hyperspace.
// Stills are kept until their site leaves the rankings, so a refresh only visits new sites.
// Usage: node scripts/snapshots.cjs  (needs playwright-core; set CHROME_PATH to use an installed Chrome)
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const SITE = path.join(__dirname, "..", "site");
const OUT = path.join(SITE, "snapshots");
const DEADLINE = Date.now() + 6 * 60 * 1000; // whole run
const CONCURRENCY = 4;

const name = (domain) => domain.replace(/[^a-z0-9.-]/gi, "_") + ".jpg";

(async () => {
  const data = JSON.parse(fs.readFileSync(path.join(SITE, "data", "sites.json"), "utf8"));
  const sites = (data.sites || []).filter((s) => typeof s.url === "string" && s.url.startsWith("https://") && s.domain);
  const wanted = new Set(sites.map((s) => name(s.domain)));
  fs.mkdirSync(OUT, { recursive: true });
  for (const f of fs.readdirSync(OUT)) {
    if (f.endsWith(".jpg") && !wanted.has(f)) fs.unlinkSync(path.join(OUT, f));
  }

  const todo = sites.filter((s) => !fs.existsSync(path.join(OUT, name(s.domain))));
  if (todo.length) {
    const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
    // A 1280x800 page rendered at quarter scale gives a 320x200 still.
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 }, deviceScaleFactor: 0.25,
      serviceWorkers: "block", acceptDownloads: false, permissions: [],
    });
    let next = 0;
    async function worker() {
      while (next < todo.length && Date.now() < DEADLINE) {
        const s = todo[next++];
        const page = await context.newPage();
        try {
          await page.goto(s.url, { waitUntil: "load", timeout: 20000 });
          await page.waitForTimeout(2500); // let fonts, images and intro animations settle
          await page.screenshot({ path: path.join(OUT, name(s.domain)), type: "jpeg", quality: 72, timeout: 10000 });
          console.log(`snapshot: ${s.domain}`);
        } catch (e) {
          console.warn(`warn: no snapshot for ${s.domain}: ${String(e.message || e).split("\n")[0]}`);
        } finally {
          await page.close().catch(() => {});
        }
      }
    }
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    await browser.close();
  }

  const have = sites.map((s) => s.domain).filter((d, i, all) => all.indexOf(d) === i && fs.existsSync(path.join(OUT, name(d))));
  fs.writeFileSync(path.join(OUT, "index.json"), JSON.stringify(have.map(name)));
  console.log(`${have.length} snapshots`);
})();
