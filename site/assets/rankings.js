// Page script; inline scripts are blocked by the Content-Security-Policy.
const { esc, safeUrl } = DL;
const fmt = new Intl.NumberFormat("en-US");
let data;

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
  const rows = (data?.sites || []).filter((s) => DL.inCategory(s)).slice(0, 25);
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
        <div class="bar" data-w="${Math.round((s.votes / max) * 100)}"></div>
        <div class="inner">
          <span><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.domain)} ↗</a>${s.embeddable ? "" : '<span class="nolive" title="This site can\'t be shown inside Live view">not in live</span>'}</span>
          <span class="title">${esc(s.title)}</span>
        </div>
      </td>
      <td class="num votes">${fmt.format(s.votes)}</td>
      <td class="src"><a href="${esc(safeUrl(s.post_url))}" target="_blank" rel="noopener noreferrer">${esc(s.source)} ↗</a></td>
    </tr>`).join("");
  // Widths are set through the DOM because the CSP forbids inline style attributes.
  tbody.querySelectorAll(".bar[data-w]").forEach((b) => (b.style.width = b.dataset.w + "%"));
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
      `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a>`).join("");
  }
  const updatedEl = document.getElementById("updated");
  if (updatedEl) {
    const date = d.generated_at ? new Date(d.generated_at) : null;
    const dateStr = date && !isNaN(date.getTime()) ? date.toLocaleString() : "recently";
    updatedEl.textContent = "Updated " + dateStr;
  }
  render();
  DL.onCategory(render);
}).catch(() => {
  const tbody = document.getElementById("rows");
  if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="updated">Couldn\'t load rankings.</td></tr>';
});
