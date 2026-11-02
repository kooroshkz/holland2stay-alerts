(() => {
  const SRC = document.body.dataset.src;
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const TAGS = {
    new: "New", back: "Back", bookable: "Bookable", price: "Price drop",
    lottery: "Lottery", gone: "Taken", building: "Building",
  };
  const HOT = new Set(["new", "back", "bookable", "price", "lottery"]);
  let data = null;

  const $ = (id) => document.getElementById(id);
  // A static demo keeps its timestamps fresh by moving them to the present.
  const at = (iso) => Date.parse(iso) + (data && data.demo ? Date.now() - Date.parse(data.now) : 0);

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  const money = (v) => (v === null || v === undefined ? "" : "€" + Math.round(v).toLocaleString("en-US"));
  const join = (parts) => parts.filter(Boolean).join(" · ");

  function ago(iso) {
    if (!iso) return "";
    const s = Math.max(0, (Date.now() - at(iso)) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  function clock(iso) {
    const d = new Date(at(iso));
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    const today = new Date().toDateString() === d.toDateString();
    return today ? time : `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
  }

  function duration(minutes) {
    if (minutes === null || minutes === undefined) return null;
    if (minutes < 60) return `${minutes} min`;
    if (minutes < 60 * 48) return `${Math.round(minutes / 60)} h`;
    return `${Math.round(minutes / 1440)} days`;
  }

  function countdown(iso) {
    const s = Math.round((at(iso) - Date.now()) / 1000);
    if (s <= 0) return "now";
    const m = Math.floor(s / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s % 60).padStart(2, "0")}`;
  }

  function renderState() {
    const pill = $("state");
    const st = (data && data.status) || {};
    const label = pill.querySelector("span");
    pill.classList.toggle("on", st.state === "watching");
    if (!data) { label.textContent = "Can't reach the watcher"; return; }
    if (data.demo) { pill.classList.add("on"); label.textContent = "Demo · sample data"; return; }
    if (st.state === "watching" && st.next_check) {
      label.textContent = `Watching · next check ${countdown(st.next_check)}`;
    } else if (st.state === "paused" || st.state === "retrying") {
      const when = st.next_check ? ` · again at ${clock(st.next_check)}` : "";
      label.textContent = `${st.state === "paused" ? "Paused" : "Retrying"}${when}`;
      pill.title = st.message || "";
    } else if (st.state === "stopped") {
      label.textContent = "Stopped";
    } else {
      label.textContent = "Starting";
    }
  }

  function stat(label, value, fallback) {
    const box = el("div", "glass stat");
    box.append(el("small", null, label));
    box.append(value === null ? el("strong", "none", fallback) : el("strong", null, value));
    return box;
  }

  function homeRow(h, extra) {
    const li = el("li");
    const a = el("a");
    a.href = h.url; a.target = "_blank"; a.rel = "noopener";
    const left = el("div");
    left.append(el("div", "name", h.name));
    left.append(el("div", "meta", join([h.city, h.bedrooms, h.contract, h.furnishing])));
    const right = el("div", "side");
    right.append(el("div", "price", money(h.price)));
    right.append(el("div", "when", extra || ago(h.since)));
    a.append(left, right);
    li.append(a);
    return li;
  }

  function fill(list, items, make, empty) {
    list.replaceChildren(...items.map(make));
    if (!items.length) list.append(el("p", "empty", empty));
  }

  function renderHeat() {
    const box = $("heat");
    const cells = [el("b")];
    for (let h = 0; h < 24; h++) cells.push(el("b", "h", h % 6 === 0 ? String(h).padStart(2, "0") : ""));
    const max = Math.max(1, ...data.heatmap.flat());
    data.heatmap.forEach((row, d) => {
      cells.push(el("b", null, DAYS[d]));
      row.forEach((n, h) => {
        const cell = el("i");
        if (n) cell.style.background = `color-mix(in srgb, var(--fg) ${Math.round(15 + 70 * (n / max))}%, transparent)`;
        cell.title = `${DAYS[d]} ${String(h).padStart(2, "0")}:00 · ${n}`;
        cells.push(cell);
      });
    });
    box.replaceChildren(...cells);
    const total = data.heatmap.flat().reduce((a, b) => a + b, 0);
    box.nextElementSibling?.remove();
    if (!total) box.after(el("p", "heat-note", "Fills in as new homes appear."));
  }

  function render() {
    renderState();
    $("search").textContent = data.search.summary;
    document.title = `${data.stats.matching} · holland2stay alerts`;
    $("version").textContent = `v${data.version}`;

    const s = data.stats;
    $("stats").replaceChildren(
      stat("Matching now", String(s.matching)),
      stat("New this week", String(s.new_week)),
      stat("Taken this week", String(s.gone_week)),
      stat("Typical time listed", duration(s.median_minutes), "No data yet"),
    );

    $("available-count").textContent = data.available.length ? String(data.available.length) : "";
    fill($("available"), data.available, (h) => homeRow(h), "Nothing matches right now. You'll get a message when something does.");

    $("lottery-box").hidden = !data.lottery.length;
    $("lottery-deadline").textContent = `closes ${clock(data.search.deadline)}`;
    fill($("lottery"), data.lottery, (h) => homeRow(h, "lottery"), "");

    fill($("events"), data.events, (e) => {
      const li = el("li");
      li.append(el("span", `tag${HOT.has(e.kind) ? " hot" : ""}`, TAGS[e.kind] || e.kind));
      const what = el("div", "what");
      what.append(e.name || "");
      let more = join([e.city, money(e.price)]);
      if (e.kind === "gone" && /^\d+$/.test(e.detail || "")) more = join([e.city, `after ${duration(Math.round(e.detail / 60))}`]);
      if (more) what.append(el("span", null, ` · ${more}`));
      const time = el("time", null, clock(e.at));
      time.dateTime = e.at;
      li.append(what, time);
      return li;
    }, "Quiet so far.");

    renderHeat();

    $("cities-box").hidden = data.cities.length < 2;
    const top = Math.max(1, ...data.cities.map((c) => c.count));
    fill($("cities"), data.cities, (c) => {
      const li = el("li");
      li.append(el("span", null, c.name), el("span", "muted", String(c.count)));
      const bar = el("div", "bar");
      const fillBar = el("span");
      fillBar.style.width = `${(100 * c.count) / top}%`;
      bar.append(fillBar);
      li.append(bar);
      return li;
    }, "");

    $("buildings-box").hidden = !data.buildings.length;
    fill($("buildings"), data.buildings, (b) => {
      const li = el("li");
      const row = el("div", "row");
      const left = el("div");
      left.append(el("div", "name", b.street), el("div", "meta", join([b.city, `${b.homes} homes`])));
      row.append(left, el("div", "when", `seen ${ago(b.since)}`));
      li.append(row);
      return li;
    }, "");
  }

  async function load() {
    try {
      const res = await fetch(SRC, { cache: "no-store" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
      render();
    } catch (e) {
      data = null;
      renderState();
    }
  }

  load();
  setInterval(load, 15000);
  setInterval(() => data && renderState(), 1000);
})();
