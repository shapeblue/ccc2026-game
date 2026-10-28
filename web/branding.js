// Shows logos listed under "branding" in data/game.json. A logo whose file is missing
// is skipped (main logos) or shown as the partner's name (partner logos).
(() => {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let partners = [];
  window.partnerLogo = (name) => {
    const p = partners.find((x) => x.name.toLowerCase() === String(name).toLowerCase());
    return p ? `<img class="card-logo" src="${esc(p.src)}" alt="" onerror="this.remove()">` : "";
  };
  function logo(item, kind) {
    const wrap = document.createElement("span");
    wrap.className = `logo logo-${kind}`;
    const img = new Image();
    img.alt = item.name;
    img.onerror = () => {
      if (kind === "main") return wrap.remove();
      img.remove();
      wrap.textContent = item.name;
      wrap.classList.add("logo-text");
    };
    img.src = item.src;
    wrap.appendChild(img);
    return wrap;
  }
  fetch("/data/game.json").then((r) => r.json()).then((g) => {
    const b = g.branding || {};
    partners = b.partners || [];
    document.querySelectorAll('[data-brand="main"]').forEach((el) => (b.main || []).forEach((l) => el.appendChild(logo(l, "main"))));
    document.querySelectorAll('[data-brand="partners"]').forEach((el) => partners.forEach((l) => el.appendChild(logo(l, "partner"))));
    if (!partners.length) document.querySelectorAll("[data-partners]").forEach((el) => el.remove());
  }).catch(() => {});
})();
