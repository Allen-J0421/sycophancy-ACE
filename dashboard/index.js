(function () {
  const grid = document.getElementById("dashboard-grid");
  const empty = document.getElementById("empty-state");
  const items = window.__DASHBOARDS__ || [];

  if (!items.length) {
    empty.hidden = false;
    return;
  }

  items.forEach((item) => {
    if (item.pending) {
      const card = document.createElement("div");
      card.className = "card pending";
      card.innerHTML =
        `<h2 class="card-title">${escapeHtml(item.title)}</h2>` +
        `<p class="card-meta">${escapeHtml(item.subtitle || "")}</p>` +
        `<p class="card-hint">python dashboard/build.py --exp ${escapeHtml(item.id)}</p>`;
      grid.appendChild(card);
      return;
    }

    const link = document.createElement("a");
    link.className = "card";
    link.href = item.href;
    link.innerHTML =
      `<h2 class="card-title">${escapeHtml(item.title)}</h2>` +
      `<p class="card-meta">${escapeHtml(item.subtitle || "")}</p>`;
    grid.appendChild(link);
  });

  function escapeHtml(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
  }
})();
