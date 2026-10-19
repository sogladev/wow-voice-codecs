// One comparison, several samples: every player shares the selected sample, and
// switching a configuration keeps the playback position so the same moment of
// speech can be compared between codecs.

const state = { data: null, itemIndex: 0, players: [], chips: [] };

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const GROUP_LABELS = { reference: "reference", codec: "codecs", loss: "packet loss" };

function fmt(value) {
  return value === null || value === undefined || value === "" ? "–" : value;
}

function shuffle(list) {
  const a = list.slice();
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function bestWorst(values) {
  const nums = values.filter((v) => v !== null && v !== undefined).map(Number);
  if (!nums.length) return { best: null, worst: null };
  return { best: Math.max(...nums), worst: Math.min(...nums) };
}

// ---------------------------------------------------------------- sample picker

function buildSampleChips(items) {
  const host = document.querySelector("#sample-chips");
  state.chips = items.map((item, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.setAttribute("aria-pressed", String(index === 0));
    chip.textContent = item.label || `sample ${index + 1}`;
    chip.title = item.text || "";
    chip.addEventListener("click", () => selectSample(index));
    host.append(chip);
    return chip;
  });
  updateSampleText();
}

function updateSampleText() {
  const item = state.data.items[state.itemIndex];
  document.querySelector("#sample-text").textContent = item && item.text ? `“${item.text.toLowerCase()}”` : "";
  state.chips.forEach((chip, i) => chip.setAttribute("aria-pressed", String(i === state.itemIndex)));
}

function selectSample(index) {
  state.itemIndex = index;
  updateSampleText();
  for (const player of state.players) player.applyClip({ keepPlaying: true });
}

// ---------------------------------------------------------------------- player

function buildPlayer(root, configs) {
  const audio = new Audio();
  audio.preload = "auto";

  const playBtn = root.querySelector(".play");
  const seek = root.querySelector(".seek");
  const timeEl = root.querySelector(".time");
  const list = root.querySelector(".variants");
  const nowPlaying = root.querySelector(".now-playing");
  const note = root.querySelector(".config-note");
  const blindToggle = root.querySelector(".blind-toggle");
  const loopToggle = root.querySelector(".loop-toggle");
  const revealBtn = root.querySelector(".reveal");

  const blindOrder = shuffle(configs.map((c) => c.id));
  const blindLabel = new Map(blindOrder.map((id, i) => [id, LETTERS[i] || `#${i + 1}`]));

  const player = {
    configs,
    audio,
    current: configs[0].id,
    buttons: new Map(),
    blind: false,
  };

  const labelFor = (cfg) => (player.blind ? blindLabel.get(cfg.id) : cfg.label);

  player.applyClip = ({ keepPlaying = true } = {}) => {
    const item = state.data.items[state.itemIndex];
    const clip = item && item.clips[player.current];
    if (!clip) return;

    const wasPlaying = !audio.paused;
    const at = audio.currentTime || 0;
    audio.src = clip.mp3;
    audio.load();
    audio.addEventListener("loadedmetadata", () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        audio.currentTime = Math.min(at, Math.max(0, audio.duration - 0.05));
      }
      if (keepPlaying && (wasPlaying || player.firstStart)) audio.play().catch(() => {});
    }, { once: true });
    refreshLabels();
  };

  const select = (id) => {
    if (id === player.current && audio.src) return;
    player.current = id;
    player.applyClip({ keepPlaying: true });
  };

  function refreshLabels() {
    for (const cfg of configs) {
      const btn = player.buttons.get(cfg.id);
      if (!btn) continue;
      btn.querySelector(".name").textContent = labelFor(cfg);
      btn.setAttribute("aria-pressed", String(cfg.id === player.current));
      btn.disabled = !(state.data.items[state.itemIndex] || {}).clips[cfg.id];
    }
    revealBtn.hidden = !player.blind;
    const current = configs.find((c) => c.id === player.current);
    nowPlaying.textContent = current ? `now playing: ${labelFor(current)}` : "";
    if (note) note.textContent = current && !player.blind ? current.note || "" : "";
  }

  // group the buttons so the ladder from 8 kHz to 16 kHz is visible
  let lastGroup = null;
  for (const cfg of configs) {
    if (cfg.group !== lastGroup) {
      const heading = document.createElement("div");
      heading.className = "variant-group";
      heading.textContent = GROUP_LABELS[cfg.group] || cfg.group;
      list.append(heading);
      lastGroup = cfg.group;
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(cfg.id === player.current));

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = labelFor(cfg);

    const meta = document.createElement("span");
    meta.className = "meta";
    const parts = [];
    if (cfg.band) parts.push(cfg.band);
    if (cfg.wireKbps) parts.push(`${cfg.wireKbps} kbit/s wire`);
    if (cfg.pesq) parts.push(`PESQ ${cfg.pesq}`);
    meta.textContent = parts.join(" · ");

    btn.append(name, meta);
    btn.addEventListener("click", () => {
      player.firstStart = true;
      select(cfg.id);
    });
    player.buttons.set(cfg.id, btn);
    list.append(btn);
  }

  playBtn.addEventListener("click", () => {
    player.firstStart = true;
    if (audio.paused) {
      if (!audio.src) player.applyClip({ keepPlaying: false });
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  });

  if (loopToggle) {
    loopToggle.addEventListener("change", () => {
      audio.loop = loopToggle.checked;
    });
  }

  audio.addEventListener("play", () => { playBtn.textContent = "Pause"; });
  audio.addEventListener("pause", () => { playBtn.textContent = "Play"; });
  audio.addEventListener("ended", () => { audio.currentTime = 0; });
  audio.addEventListener("timeupdate", () => {
    const d = audio.duration || 0;
    seek.value = d ? String(Math.round((audio.currentTime / d) * 1000)) : "0";
    timeEl.textContent = `${formatTime(audio.currentTime)} / ${formatTime(d)}`;
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

  player.preloadForCurrentSample = () => {
    const item = state.data.items[state.itemIndex];
    if (!item) return;
    const conn = navigator.connection || {};
    if (conn.saveData || conn.effectiveType === "slow-2g" || conn.effectiveType === "2g") return;
    const queue = player.configs.filter((c) => c.id !== player.current && item.clips[c.id]);
    const next = () => {
      const cfg = queue.shift();
      if (!cfg) return;
      const probe = new Audio();
      probe.preload = "auto";
      probe.addEventListener("canplaythrough", next, { once: true });
      probe.addEventListener("error", next, { once: true });
      probe.src = item.clips[cfg.id].mp3;
    };
    next();
  };

  audio.addEventListener("playing", () => player.preloadForCurrentSample(), { once: true });

  player.applyClip({ keepPlaying: false });
  refreshLabels();
  return player;
}

// ----------------------------------------------------------------------- table

function renderTable(configs) {
  const table = document.querySelector("#main-table");
  const header = document.createElement("tr");
  for (const [label, cls] of [["configuration", ""], ["band", ""], ["wire kbit/s", "num"],
    ["pkt/s", "num"], ["max packet", "num"], ["PESQ-WB", "num"], ["STOI", "num"]]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    if (cls) th.className = cls;
    header.append(th);
  }
  const thead = document.createElement("thead");
  thead.append(header);

  const codecPesq = bestWorst(configs.filter((c) => c.group === "codec").map((c) => c.pesq));

  const tbody = document.createElement("tbody");
  for (const cfg of configs) {
    const tr = document.createElement("tr");
    if (cfg.group === "reference") tr.className = "row-reference";

    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = cfg.label;
    tr.append(th);

    for (const value of [cfg.band, cfg.wireKbps, cfg.packetsPerSecond, cfg.maxPacketBytes, cfg.pesq, cfg.stoi]) {
      const td = document.createElement("td");
      td.textContent = fmt(value);
      if (value === null || value === undefined) td.classList.add("missing");
      tr.append(td);
    }

    if (cfg.pesq !== null && cfg.pesq !== undefined) {
      const cell = tr.children[5];
      if (Number(cfg.pesq) === codecPesq.best) cell.classList.add("best");
      if (Number(cfg.pesq) === codecPesq.worst) cell.classList.add("worst");
    }
    tbody.append(tr);
  }

  table.append(thead, tbody);
}

// ------------------------------------------------------------------- bootstrap

function emptyBuildNotice() {
  const notice = document.createElement("section");
  notice.className = "panel notice";
  notice.innerHTML =
    "<h2>data.json has no clips</h2>" +
    "<p>The page loaded, but the file it reads contains no measurements, so there is nothing to play. " +
    "Restore the committed version, or rebuild the clips:</p>" +
    "<pre><code>git checkout -- data.json\n\n" +
    "DECOMP=/path/to/wowdecomp ./tools/build.sh\n" +
    "./tools/run_matrix.sh\n" +
    "./tools/build_site.py</code></pre>";
  document.querySelector("main").prepend(notice);
}

async function main() {
  let data;
  try {
    const res = await fetch("data.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`data.json: HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.querySelector(".lede").textContent =
      `Could not load data.json (${err.message}). Run ./serve.sh from the repository root.`;
    return;
  }

  state.data = data;
  document.querySelector("#generated").textContent = data.generated || "";
  document.querySelector("#corpus").textContent = data.corpus || "";
  document.querySelector("#delivery").textContent = data.deliveryCodec || "";

  if (!(data.items || []).length || !(data.configs || []).length) {
    emptyBuildNotice();
    return;
  }

  const compareConfigs = data.configs.filter((c) => c.group !== "loss");
  const lossConfigs = data.configs.filter((c) => c.group === "loss");

  buildSampleChips(data.items);

  const compareRoot = document.querySelector('.player[data-player="compare"]');
  const lossRoot = document.querySelector('.player[data-player="loss"]');

  state.players.push(buildPlayer(compareRoot, compareConfigs));
  state.players.push(buildPlayer(lossRoot, lossConfigs.length ? lossConfigs : compareConfigs));

  renderTable(data.configs);

  // keyboard: space toggles the visible player, 1-9 switch configuration
  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    const playing = state.players.find((p) => !p.audio.paused) || state.players[0];
    if (!playing) return;

    if (event.code === "Space") {
      event.preventDefault();
      playing.firstStart = true;
      if (playing.audio.paused) {
        if (!playing.audio.src) playing.applyClip({ keepPlaying: false });
        playing.audio.play().catch(() => {});
      } else {
        playing.audio.pause();
      }
      return;
    }

    const n = Number(event.key);
    if (Number.isInteger(n) && n >= 1 && n <= 9) {
      const cfg = playing.configs[n - 1];
      const btn = cfg && playing.buttons.get(cfg.id);
      if (btn && !btn.disabled) {
        event.preventDefault();
        btn.click();
      }
    }
  });
}

main();
