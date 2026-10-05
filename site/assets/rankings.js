// Page script; inline scripts are blocked by the Content-Security-Policy.
const { esc, safeUrl } = DL;
const fmt = new Intl.NumberFormat("en-US");
let data, entered = false;
const ext = DL.icon("ext");

// "r/SideProject" reads as a muted "r/" and the subreddit name.
function sourceLabel(src) {
  const m = /^(r\/)(.+)$/.exec(src || "");
  return m ? `<span class="sn"><span class="pre">${m[1]}</span>${esc(m[2])}</span>` : `<span class="sn">${esc(src)}</span>`;
}

function render() {
  const cat = DL.CATS.find((c) => c.key === DL.category);
  const noun = document.getElementById("noun");
  if (noun && noun.textContent !== cat?.noun) {
    noun.textContent = cat ? cat.noun : "projects";
    // Repaint the brush stroke under the new word.
    const r = document.querySelector(".brush-reveal");
    if (r) {
      r.style.animation = "none";
      void r.offsetWidth;
      r.style.animation = "";
    }
  }
  const rows = DL.ranked(data?.sites || [], DL.category, 25);
  const max = rows[0]?.votes || 1;
  const tbody = document.getElementById("rows");
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="updated">Nothing in this category yet.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((s, i) => `
    <tr>
      <td class="rank"><span class="badge ${i < 3 ? "medal r" + (i + 1) : ""}">${i + 1}</span></td>
      <td class="domain-cell">
        <div class="line">
          <a class="domain" href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer"><span class="dn">${esc(s.domain)}</span>${ext}</a>
          ${s.embeddable ? "" : '<span class="tag" title="This site can\'t be shown inside Live view">Not in Live</span>'}
        </div>
        <div class="title" title="${esc(s.title)}">${esc(s.title)}</div>
        <a class="src-line" href="${esc(safeUrl(s.post_url))}" target="_blank" rel="noopener noreferrer">${sourceLabel(s.source)}${ext}</a>
        <div class="meter" aria-hidden="true"><span data-w="${Math.max(2, Math.round((s.votes / max) * 100))}"></span></div>
      </td>
      <td class="num votes">${fmt.format(s.votes)}</td>
      <td class="src"><a href="${esc(safeUrl(s.post_url))}" target="_blank" rel="noopener noreferrer" title="${esc(s.source)}">${sourceLabel(s.source)}${ext}</a></td>
    </tr>`).join("");
  // The first set of rows rises in on load.
  if (!entered) {
    entered = true;
    tbody.classList.add("rise");
    tbody.querySelectorAll("tr").forEach((tr, i) => tr.style.setProperty("--i", i));
  } else {
    tbody.classList.remove("rise");
  }
  // Widths are set through the DOM because the CSP forbids inline style attributes.
  // They start at zero and grow on the next frame.
  requestAnimationFrame(() => tbody.querySelectorAll(".meter span[data-w]").forEach((b) => (b.style.width = b.dataset.w + "%")));
}

const pop = document.getElementById("src-pop");
const srcBtn = document.getElementById("src-btn");
if (srcBtn && pop) {
  srcBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = !pop.classList.contains("open");
    document.querySelectorAll(".dropdown.open").forEach((d) => {
      d.classList.remove("open");
      d.querySelector(".dd-toggle")?.setAttribute("aria-expanded", "false");
    });
    pop.classList.toggle("open", open);
    srcBtn.setAttribute("aria-expanded", String(open));
  });
  pop.addEventListener("click", (e) => e.stopPropagation());
}

DL.loadData().then((d) => {
  data = d;
  DL.setCounts(d.sites, 25);
  const srcList = document.getElementById("src-list");
  if (srcList && Array.isArray(d.sources)) {
    srcList.innerHTML = d.sources.map((s) =>
      `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer"><span>${esc(s.name)}</span>${ext}</a>`).join("");
  }
  const updatedEl = document.getElementById("updated");
  if (updatedEl) {
    const date = d.generated_at ? new Date(d.generated_at) : null;
    const dateStr = date && !isNaN(date.getTime())
      ? date.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })
      : "recently";
    updatedEl.textContent = "Updated " + dateStr;
  }
  render();
  DL.onCategory(render);
}).catch(() => {
  const tbody = document.getElementById("rows");
  if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="updated">Couldn\'t load rankings.</td></tr>';
});
