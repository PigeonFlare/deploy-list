// Page script; inline scripts are blocked by the Content-Security-Policy.
const { esc, safeUrl } = DL;
const fmt = new Intl.NumberFormat("en-US");
let data;

function render() {
  const cat = DL.CATS.find((c) => c.key === DL.category);
  const noun = document.getElementById("noun");
  if (noun.textContent !== cat.noun) {
    noun.textContent = cat.noun;
    // Repaint the brush stroke under the new word.
    const r = document.querySelector(".brush-reveal");
    r.style.animation = "none"; r.getBoundingClientRect(); r.style.animation = "";
  }
  const rows = data.sites.filter((s) => DL.inCategory(s)).slice(0, 25);
  const max = rows[0]?.votes || 1;
  document.getElementById("rows").innerHTML = rows.length ? rows.map((s, i) => `
    <tr>
      <td class="rank"><span class="badge ${i < 3 ? "medal r" + (i + 1) : ""}">${i + 1}</span></td>
      <td class="domain-cell">
        <div class="bar" data-w="${(s.votes / max) * 100}"></div>
        <div class="inner">
          <span><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.domain)} ↗</a>${s.embeddable ? "" : '<span class="nolive" title="This site can\'t be shown inside Live view">not in live</span>'}</span>
          <span class="title">${esc(s.title)}</span>
        </div>
      </td>
      <td class="num votes">${fmt.format(s.votes)}</td>
      <td class="src"><a href="${esc(safeUrl(s.post_url))}" target="_blank" rel="noopener">${esc(s.source)} ↗</a></td>
    </tr>`).join("") : `<tr><td colspan="4" class="updated">Nothing in this category yet.</td></tr>`;
  // Widths are set through the DOM because the CSP forbids inline style attributes.
  document.querySelectorAll(".bar[data-w]").forEach((b) => (b.style.width = b.dataset.w + "%"));
}

const pop = document.getElementById("src-pop");
document.getElementById("src-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  const open = !pop.classList.contains("open");
  document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open"));
  pop.classList.toggle("open", open);
});
pop.addEventListener("click", (e) => e.stopPropagation());

DL.loadData().then((d) => {
  data = d;
  DL.setCounts(d.sites, 25);
  document.getElementById("src-list").innerHTML = d.sources.map((s) =>
    `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.name)} ↗</a>`).join("");
  document.getElementById("updated").textContent = "Updated " + new Date(d.generated_at).toLocaleString();
  render();
  DL.onCategory(render);
}).catch(() => {
  document.getElementById("rows").innerHTML = '<tr><td colspan="4" class="updated">Couldn\'t load rankings.</td></tr>';
});
