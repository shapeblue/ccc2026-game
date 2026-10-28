(() => {
  const $ = (id) => document.getElementById(id);
  const KIOSK = new URLSearchParams(location.search).has("kiosk");
  const state = { data: null, cards: {}, token: null, nick: null, match: null, scenario: null,
                  placed: [], tab: "zone", deadline: 0, timer: null, idle: null, me: null };

  const api = async (path, body) => {
    const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.error || `Request failed (${res.status})`);
    return json;
  };
  const store = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch {} },
  };
  const show = (name) => {
    for (const s of ["register", "done", "brief", "play", "result"]) $(`screen-${s}`).classList.toggle("hidden", s !== name);
    const strip = document.querySelector("[data-partners]");
    if (strip) strip.classList.toggle("hidden", name === "play");
    window.scrollTo(0, 0);
  };
  const tagLabel = (t) => state.data.tags[t] || t;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Same dependency rules as the server: drop cards whose needs aren't met until stable.
  function resolve(ids) {
    let active = ids.slice();
    for (;;) {
      const provided = new Set(active.flatMap((id) => state.cards[id].provides));
      const still = active.filter((id) => state.cards[id].requires.every((r) => provided.has(r)));
      if (still.length === active.length) return { active: new Set(active), provided };
      active = still;
    }
  }
  const cost = () => state.placed.reduce((n, id) => n + state.cards[id].cost, 0);

  function cardEl(card, { placed = false, inactiveNeeds = null, used = false, afford = true } = {}) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `card cat-${card.cat}` + (placed ? " placed" : "") + (card.partner ? " is-partner" : "") +
      (inactiveNeeds ? " inactive" : "") + (used ? " used" : "") + (!afford && !used && !placed ? " cant-afford" : "");
    const needs = inactiveNeeds
      ? `Needs ${inactiveNeeds.map(tagLabel).join(" and ")}`
      : !placed && card.requires.length ? `Needs ${card.requires.map(tagLabel).join(" and ")}` : "";
    b.innerHTML = `<span class="name">${esc(card.name)}</span><span class="cost" aria-label="${card.cost} credits">${card.cost}</span>` +
      `<span class="text">${esc(card.text)}</span>` + (needs ? `<span class="needs">${esc(needs)}</span>` : "") +
      (card.partner ? `<span class="partner">${window.partnerLogo ? window.partnerLogo(card.partner) : ""}Partner: ${esc(card.partner)}</span>` : "");
    b.setAttribute("aria-label", `${card.name}, ${card.cost} credits. ${placed ? "In your design, select to remove." : used ? "Already in your design." : "Select to add."} ${needs}`);
    if (used) b.disabled = true;
    return b;
  }

  function render() {
    const sc = state.scenario;
    const { active, provided } = resolve(state.placed);
    const left = sc.budget - cost();
    $("budget-left").textContent = left;
    $("g-budget").classList.toggle("warn", left <= 2);

    const board = $("board");
    board.innerHTML = "";
    for (const cat of state.data.categories) {
      const lane = document.createElement("div");
      lane.className = `lane cat-${cat.id}`;
      lane.innerHTML = `<h3>${esc(cat.label)}</h3><div class="slots"></div>`;
      const slots = lane.querySelector(".slots");
      const ids = state.placed.filter((id) => state.cards[id].cat === cat.id);
      if (!ids.length) slots.innerHTML = `<span class="empty">Nothing here yet</span>`;
      for (const id of ids) {
        const c = state.cards[id];
        const missing = active.has(id) ? null : c.requires.filter((r) => !provided.has(r));
        const el = cardEl(c, { placed: true, inactiveNeeds: missing });
        el.addEventListener("click", () => { state.placed = state.placed.filter((x) => x !== id); render(); });
        slots.appendChild(el);
      }
      board.appendChild(lane);
    }

    $("req-list").innerHTML = sc.requires.map((r) => `<li class="${provided.has(r) ? "met" : ""}">${esc(tagLabel(r))}</li>`).join("");

    const tabs = $("tabs");
    tabs.innerHTML = "";
    for (const cat of state.data.categories) {
      const t = document.createElement("button");
      t.type = "button";
      t.setAttribute("role", "tab");
      t.setAttribute("aria-selected", String(cat.id === state.tab));
      t.textContent = cat.label;
      t.addEventListener("click", () => { state.tab = cat.id; render(); });
      tabs.appendChild(t);
    }
    const hand = $("hand");
    hand.innerHTML = "";
    for (const c of state.data.cards.filter((c) => c.cat === state.tab)) {
      const used = state.placed.includes(c.id);
      const el = cardEl(c, { used, afford: c.cost <= left });
      el.addEventListener("click", () => {
        if (used) return;
        if (c.cost > left) {
          $("toast").textContent = `Not enough budget for ${c.name}. Remove a card to free up credits.`;
          el.classList.remove("shake"); void el.offsetWidth; el.classList.add("shake");
          return;
        }
        $("toast").textContent = "";
        state.placed.push(c.id);
        render();
      });
      hand.appendChild(el);
    }
  }

  function tick() {
    const s = Math.max(0, Math.ceil((state.deadline - Date.now()) / 1000));
    $("time-left").textContent = s;
    $("g-time").classList.toggle("warn", s <= 20);
    if (s === 0) deploy();
  }

  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  function setMe(me) {
    state.me = { ...(state.me || {}), ...me };
    const m = state.me;
    $("who").innerHTML = `Playing as <strong>${esc(m.nickname || state.nick)}</strong>, ${plural(m.rounds_left, "round")} left today`;
  }

  function showDone(message) {
    clearTimeout(state.idle);
    const m = state.me || {};
    $("done-text").textContent = message + (m.best != null ? ` Your best score is ${m.best}, ranked #${m.rank}.` : "");
    show("done");
    $("btn-done-new").focus();
    if (KIOSK) state.idle = setTimeout(newGame, 30000);
  }

  // autoStart skips the "Your scenario is ready" screen and starts the clock at once.
  async function newMatch(autoStart = false) {
    clearTimeout(state.idle);
    try {
      const m = await api("/api/match/start", { token: state.token });
      state.match = m;
      setMe({ rounds_left: m.rounds_left });
      state.scenario = null;
      state.placed = [];
      state.tab = "zone";
      $("brief-time").textContent = m.time_limit;
      if (autoStart === true) return startClock();
      show("brief");
      $("btn-go").focus();
    } catch (e) {
      if (/register/i.test(e.message)) return newGame();
      try { setMe(await api(`/api/me?token=${encodeURIComponent(state.token)}`)); } catch {}
      showDone(e.message);
    }
  }

  async function startClock() {
    let c;
    $("btn-go").disabled = true;
    try { c = await api("/api/match/clock", { token: state.token, match_id: state.match.match_id }); }
    catch (e) { $("btn-go").disabled = false; return alert(e.message); }
    finally { $("btn-go").disabled = false; }
    state.scenario = state.data.scenarios.find((s) => s.id === c.scenario_id);
    state.deadline = Date.now() + c.seconds_left * 1000;
    $("play-title").textContent = state.scenario.title;
    $("play-text").textContent = state.scenario.brief;
    $("toast").textContent = "";
    $("btn-deploy").disabled = false;
    render();
    show("play");
    clearInterval(state.timer);
    state.timer = setInterval(tick, 250);
    tick();
  }

  async function deploy() {
    if (!state.match || $("btn-deploy").disabled) return;
    $("btn-deploy").disabled = true;
    clearInterval(state.timer);
    try {
      const r = await api("/api/match/finish", { token: state.token, match_id: state.match.match_id, cards: state.placed });
      state.match = null;
      showResult(r);
    } catch (e) {
      $("toast").textContent = e.message;
      $("btn-deploy").disabled = false;
    }
  }

  function showResult(r) {
    const b = r.breakdown;
    $("res-scenario").textContent = state.scenario.title;
    $("res-score").textContent = r.score;
    setMe(r);
    $("res-rank").textContent = r.rank ? `Your best score is ${r.best}, ranked #${r.rank} overall.` : "";
    $("btn-again").disabled = r.rounds_left < 1;
    $("res-rounds").textContent = r.rounds_left > 0 ? `${plural(r.rounds_left, "round")} left today.` : "That was your last round for today.";
    $("res-lines").innerHTML = b.lines.map((l) => `<tr><td>${esc(l.label)}</td><td>${l.points > 0 ? "+" : ""}${l.points}</td></tr>`).join("");
    $("res-incident").classList.toggle("survived", b.incident.survived);
    $("inc-title").textContent = b.incident.title;
    $("inc-verdict").textContent = b.incident.survived ? "Your cloud survived." : "Your cloud went down.";
    $("inc-text").textContent = b.incident.text;
    const lessons = [];
    if (b.cost > b.budget) lessons.push("The design went over budget, so it couldn't be deployed.");
    if (!state.data.learn) for (const m of b.missing) lessons.push(`Missing: ${tagLabel(m)}.`);
    for (const [id, needs] of Object.entries(b.inactive)) lessons.push(`${state.cards[id].name} couldn't run without ${needs.map(tagLabel).join(" and ")}.`);
    renderLearn(b);
    renderShapeBlueFor(b);
    $("res-lessons").innerHTML = lessons.length ? `<h3>What to try next time</h3><ul>${lessons.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : "";
    show("result");
    ($("btn-again").disabled ? $("btn-next") : $("btn-again")).focus();
    if (KIOSK) { clearTimeout(state.idle); state.idle = setTimeout(newGame, 60000); }
  }

  // "Learn more": the lost incident first, then missing requirements, each linked to
  // the illustrated guide (beginners) and the official docs (architects).
  function renderLearn(b) {
    const box = $("res-learn");
    if (!state.data.learn) { box.innerHTML = ""; return; }
    const topics = [];
    if (!b.incident.survived) {
      const inc = state.data.incidents[b.incident.id];
      const c = Array.isArray(inc.counter) ? inc.counter[0] : inc.counter;
      topics.push({ tag: c, why: `To survive "${b.incident.title.toLowerCase()}"` });
    }
    for (const m of b.missing) if (!topics.some((t) => t.tag === m)) topics.push({ tag: m, why: "Missing requirement" });
    const rows = topics.map((t) => ({ ...t, links: Learn.links(t.tag) })).filter((t) => t.links).slice(0, 4);
    if (!rows.length) {
      box.innerHTML = `<h3>Keep exploring</h3><p class="muted">Nice design. Scan to learn about the features you didn't need this time.</p>` + Learn.qrBlock(Learn.home());
      return;
    }
    const e = Learn.esc;
    const list = rows.map((t) => `<li><strong>${e(tagLabel(t.tag))}</strong> <span class="muted">${e(t.why)}</span><br>` +
      [t.links.guide && `<a href="${e(t.links.guide.url)}" target="_blank" rel="noopener">Story: ${e(t.links.guide.title)}</a>`,
       t.links.docs && `<a href="${e(t.links.docs.url)}" target="_blank" rel="noopener">${e(t.links.docs.title)}</a>`].filter(Boolean).join(" &nbsp;|&nbsp; ") + `</li>`).join("");
    const top = rows[0].links;
    const qrs = [top.guide && { url: top.guide.url, label: "Read the story", sub: top.guide.title },
                 top.docs && { url: top.docs.url, label: top.docs.title, sub: tagLabel(rows[0].tag) }].filter(Boolean);
    box.innerHTML = `<h3>Learn more</h3><ul class="learn-list">${list}</ul>` +
      `<p class="muted" style="margin:0.8rem 0 0.4rem">Scan to read about ${e(tagLabel(rows[0].tag))} on your phone:</p>` + Learn.qrBlock(qrs);
  }

  // ShapeBlue services: all six on the registration page, the two most relevant after a round.
  const sb = () => state.data.shapeblue;
  const sbService = (id) => sb().services.find((x) => x.id === id);
  const sbCard = (x) => `<a class="sb-service" href="${Learn.esc(x.url)}" target="_blank" rel="noopener"><strong>${Learn.esc(x.title)}</strong><span>${Learn.esc(x.text)}</span></a>`;

  // Registration: one "New to CloudStack?" panel with the guide, the docs and ShapeBlue services.
  function renderHelpPanel() {
    const codes = Learn.home();
    if (sb()) codes.push({ url: sb().contact_url, label: "Talk to ShapeBlue", sub: "Expert help building your cloud" });
    if (!codes.length) return $("reg-learn").remove();
    $("reg-qr").innerHTML = Learn.qrBlock(codes);
    $("reg-sb").innerHTML = sb()
      ? `<h4>ShapeBlue services</h4><div class="sb-grid">${sb().services.map(sbCard).join("")}</div>` : "";
  }

  function renderShapeBlueFor(b) {
    const box = $("res-sb");
    if (!sb()) { box.innerHTML = ""; return; }
    const first = sbService(sb().scenario_service[state.scenario.id] || sb().default_service);
    const met = state.scenario.requires.length - b.missing.length;
    const secondId = !b.incident.survived ? "support" : met < state.scenario.requires.length / 2 ? "training" : "consulting";
    const picks = [first, sbService(secondId)].filter((x, i, a) => x && a.findIndex((y) => y && y.id === x.id) === i);
    const why = first.id === "migration" ? "Planning a real VMware exit?" : !b.incident.survived ? "Want your cloud to survive incidents like this one?" : "Want to build this for real?";
    box.innerHTML = `<h3>${Learn.esc(why)} ShapeBlue can help.</h3>
      <div class="sb-grid sb-grid-2">${picks.map(sbCard).join("")}</div>
      <div class="sb-contact">${Learn.qrBlock([{ url: first.url, label: first.title, sub: "Scan to read more" }, { url: sb().contact_url, label: "Talk to ShapeBlue", sub: "Scan to get in touch" }])}</div>`;
  }

  function newGame() {
    clearTimeout(state.idle);
    clearInterval(state.timer);
    state.token = state.nick = state.match = state.me = null;
    store.set("cc_token", null); store.set("cc_nick", null);
    $("register-form").reset();
    $("who").textContent = "";
    show("register");
  }

  function signedIn(token, nick) {
    state.token = token; state.nick = nick;
    store.set("cc_token", token); store.set("cc_nick", nick);
    $("who").innerHTML = `Playing as <strong>${esc(nick)}</strong>`;
  }

  $("register-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("register-error").textContent = "";
    try {
      const r = await api("/api/register", {
        full_name: $("f-name").value, nickname: $("f-nick").value, email: $("f-email").value,
        company: $("f-company").value, role: $("f-role").value,
        consent_rules: $("f-rules").checked, consent_updates: $("f-updates").checked,
      });
      signedIn(r.token, r.nickname);
      newMatch();
    } catch (e) { $("register-error").textContent = e.message; }
  });
  $("btn-go").addEventListener("click", () => startClock());
  $("btn-deploy").addEventListener("click", deploy);
  $("btn-again").addEventListener("click", () => newMatch(true));
  $("btn-next").addEventListener("click", newGame);
  $("btn-done-new").addEventListener("click", newGame);

  (async () => {
    state.data = await api("/data/game.json");
    Learn.setConfig(state.data.learn);
    renderHelpPanel();
    for (const c of state.data.cards) state.cards[c.id] = c;
    try { $("event").textContent = (await api("/api/config")).event; } catch {}
    const token = store.get("cc_token");
    if (token) {
      try { const me = await api(`/api/me?token=${encodeURIComponent(token)}`); signedIn(token, me.nickname); setMe(me); return newMatch(); }
      catch { store.set("cc_token", null); }
    }
    show("register");
  })();
})();
