// Learning links and offline QR codes for the illustrated guide and the official docs.
// Uses web/vendor/qrcode.js (qrcode-generator by Kazuhiko Arase, MIT licence).
window.Learn = (() => {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let cfg = null;
  const setConfig = (learn) => { cfg = learn || null; };

  function links(tag) {
    if (!cfg || !cfg.topics || !cfg.topics[tag]) return null;
    const t = cfg.topics[tag];
    const out = {};
    if (t.guide) {
      const num = t.guide.replace("ch", "");
      out.guide = { url: cfg.guide_url + "#" + t.guide, title: `Chapter ${num}: ${cfg.chapters[t.guide] || ""}`.trim() };
    }
    if (t.docs) {
      const url = /^https?:/.test(t.docs) ? t.docs : cfg.docs_url + t.docs;
      out.docs = { url, title: /github\.com/.test(url) ? "Project on GitHub" : "Official docs" };
    }
    return out;
  }

  function qrSvg(url) {
    if (typeof qrcode !== "function") return "";
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  }

  // A pair of scannable codes: [{url, label, sub}]
  function qrBlock(items) {
    return `<div class="qr-pair">${items.map((i) => `
      <a class="qr" href="${esc(i.url)}" target="_blank" rel="noopener">
        <span class="qr-code" aria-hidden="true">${qrSvg(i.url)}</span>
        <span class="qr-label">${esc(i.label)}</span>
        ${i.sub ? `<span class="qr-sub">${esc(i.sub)}</span>` : ""}
      </a>`).join("")}</div>`;
  }

  const home = () => cfg ? [
    { url: cfg.guide_url, label: "Read the story", sub: cfg.guide_title },
    { url: cfg.docs_url, label: "Read the docs", sub: cfg.docs_title },
  ] : [];

  return { setConfig, links, qrBlock, home, esc };
})();
