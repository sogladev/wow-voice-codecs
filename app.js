// Listening comparison page: one audio element per section, switching keeps the
// playback position so two codecs can be compared on the same moment of speech.

const state = { data: null, players: {} };

function fmt(x) {
  return x === null || x === undefined || x === "" ? "–" : x;
}

function bestWorst(values) {
  const nums = values.filter((v) => v !== null && v !== undefined && v !== "").map(Number);
  if (!nums.length) return { best: null, worst: null };
  return { best: Math.max(...nums), worst: Math.min(...nums) };
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function buildPlayer(root, variants) {
  if (!variants.length) {
    root.closest(".panel").hidden = true;
    return null;
  }

  const audio = new Audio();
  audio.preload = "auto";
  const playBtn = root.querySelector(".play");
  const seek = root.querySelector(".seek");
  const timeEl = root.querySelector(".time");
  const list = root.querySelector(".variants");
  const nowPlaying = root.querySelector(".now-playing");
  const blindToggle = root.querySelector(".blind-toggle");
  const revealBtn = root.querySelector(".reveal");

  // blind labels: a stable random order per page load
  const blindOrder = shuffle(variants.map((v) => v.id));
  const blindLabel = new Map(blindOrder.map((id, i) => [id, LETTERS[i] || `#${i + 1}`]));

  const player = {
    variants,
    audio,
    current: variants[0].id,
    buttons: new Map(),
    blind: false,
  };

  function labelFor(v) {
    return player.blind ? blindLabel.get(v.id) : v.label;
  }

  function refreshLabels() {
    for (const v of variants) {
      const btn = player.buttons.get(v.id);
      const strong = btn.querySelector(".name");
      strong.textContent = labelFor(v);
      btn.setAttribute("aria-pressed", String(v.id === player.current));
    }
    revealBtn.hidden = !player.blind;
    const cur = variants.find((v) => v.id === player.current);
    nowPlaying.textContent = cur ? `now playing: ${labelFor(cur)}` : "";
  }

  function select(id, { keepPlaying = true } = {}) {
    const v = variants.find((x) => x.id === id);
    if (!v) return;
    if (id === player.current && audio.src) {
      refreshLabels();
      return;
    }

    const wasPlaying = !audio.paused;
    const at = audio.currentTime || 0;
    player.current = id;

    audio.src = v.mp3;
    audio.load();

    const resume = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        audio.currentTime = Math.min(at, Math.max(0, audio.duration - 0.05));
      }
      if (keepPlaying && (wasPlaying || player.firstStart)) {
        audio.play().catch(() => {});
      }
    };
    audio.addEventListener("loadedmetadata", resume, { once: true });
    refreshLabels();
  }

  function buildButton(v, index) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(v.id === player.current));

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = labelFor(v);

    const meta = document.createElement("span");
    meta.className = "meta";
    const parts = [];
    if (v.wireKbps) parts.push(`${v.wireKbps} kbit/s wire`);
    if (v.pesq) parts.push(`PESQ ${v.pesq}`);
    if (index < 9) parts.push(`${index + 1}`);
    meta.textContent = parts.join(" · ");

    const wavLink = document.createElement("a");
    wavLink.className = "exact";
    wavLink.href = v.wav;
    wavLink.download = `${v.id}.wav`;
    wavLink.textContent = "wav";
    wavLink.addEventListener("click", (event) => event.stopPropagation());
    meta.append(meta.textContent ? " · " : "", wavLink);

    btn.append(name, meta);
    btn.addEventListener("click", () => {
      player.firstStart = true;
      select(v.id);
    });
    player.buttons.set(v.id, btn);
    return btn;
  }

  variants.forEach((v, i) => list.append(buildButton(v, i)));

  playBtn.addEventListener("click", () => {
    player.firstStart = true;
    if (audio.paused) {
      if (!audio.src) {
        select(player.current);
        return;
      }
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  });

  audio.addEventListener("play", () => { playBtn.textContent = "Pause"; });
  audio.addEventListener("pause", () => { playBtn.textContent = "Play"; });

  audio.addEventListener("timeupdate", () => {
    const d = audio.duration || 0;
    seek.value = d ? String(Math.round((audio.currentTime / d) * 1000)) : "0";
    timeEl.textContent = `${formatTime(audio.currentTime)} / ${formatTime(d)}`;
  });

  audio.addEventListener("ended", () => {
    audio.currentTime = 0;
  });

  seek.addEventListener("input", () => {
    const d = audio.duration || 0;
    if (d) audio.currentTime = (Number(seek.value) / 1000) * d;
  });

  blindToggle.addEventListener("change", () => {
    player.blind = blindToggle.checked;
    refreshLabels();
  });

  revealBtn.addEventListener("click", () => {
    player.blind = false;
    blindToggle.checked = false;
    refreshLabels();
  });

  // preload the rest once the user has started, so switching is instant
  audio.addEventListener("playing", () => {
    for (const v of variants) {
      if (v.id === player.current) continue;
      const a = new Audio();
      a.preload = "auto";
      a.src = v.mp3;
    }
  }, { once: true });

  select(variants[0].id, { keepPlaying: false });
  refreshLabels();
  return player;
}

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderTable(variants, selector = "#nb-table") {
  const table = document.querySelector(selector);
  if (!table) return;
  const measures = [
    ["wireKbps", "wire kbit/s"],
    ["packetsPerSecond", "pkt/s"],
    ["maxPacketBytes", "max packet"],
    ["payloadKbps", "payload kbit/s"],
    ["pesq", "PESQ"],
    ["stoi", "STOI"],
  ];

  const pesqStats = bestWorst(variants.filter((v) => v.pesq).map((v) => v.pesq));

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(Object.assign(document.createElement("th"), { textContent: "configuration", scope: "col" }));
  for (const [, label] of measures) {
    const th = document.createElement("th");
    th.textContent = label;
    th.scope = "col";
    headRow.append(th);
  }
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  for (const v of variants) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = v.label;
    tr.append(th);
    for (const [key] of measures) {
      const td = document.createElement("td");
      const value = v[key];
      td.textContent = fmt(value);
      if (value === null || value === undefined || value === "") td.classList.add("missing");
      if (key === "pesq" && v.pesq) {
        const n = Number(v.pesq);
        if (n === pesqStats.best) td.classList.add("best");
        if (n === pesqStats.worst) td.classList.add("worst");
      }
      tr.append(td);
    }
    tbody.append(tr);
  }

  table.append(thead, tbody);
}

function renderFooter(data) {
  document.querySelector("#generated").textContent = data.generated || "";
  document.querySelector("#corpus").textContent = data.corpus || "";
  document.querySelector("#delivery").textContent = data.deliveryCodec || "";
}

function wirePlayers(data) {
  for (const root of document.querySelectorAll(".player")) {
    const group = root.dataset.group;
    const variants = group === "wideband" ? data.wideband : data.narrowband.filter((v) => v.group === group);
    const player = buildPlayer(root, variants || []);
    if (player) state.players[group] = player;
  }

  if ((data.wideband || []).length) {
    document.querySelector("#wb-section").hidden = false;
    document.querySelector("#wb-pending").hidden = true;
  }

  // keyboard: space toggles the player in view, digits switch variant
  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;

    const groups = Object.entries(state.players);
    if (!groups.length) return;

    if (event.code === "Space") {
      const [, player] = groups.find(([, p]) => !p.audio.paused) || groups[0];
      event.preventDefault();
      player.firstStart = true;
      if (player.audio.paused) {
        if (!player.audio.src) {
          player.select(player.current);
          return;
        }
        player.audio.play().catch(() => {});
      } else {
        player.audio.pause();
      }
      return;
    }

    const n = Number(event.key);
    if (Number.isInteger(n) && n >= 1 && n <= 9) {
      const [, player] = groups.find(([, p]) => !p.audio.paused) || groups[0];
      const v = player.variants[n - 1];
      if (v) {
        event.preventDefault();
        player.firstStart = true;
        // reuse the internal selector through a synthetic click on its button
        player.buttons.get(v.id).click();
      }
    }
  });
}

async function main() {
  let data;
  try {
    const res = await fetch("data.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`data.json: HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.querySelector(".lede").textContent =
      `Could not load data.json (${err.message}). Build the clips with ./site/build_site.py first.`;
    return;
  }

  state.data = data;
  renderFooter(data);
  renderTable(data.narrowband.filter((v) => v.group === "nb"), "#nb-table");
  renderTable(data.narrowband.filter((v) => v.group === "loss"), "#loss-table");
  wirePlayers(data);
}

main();
