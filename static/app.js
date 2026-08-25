const TABS = [
  ["health", "За здравие"],
  ["repose", "За упокой"],
  ["thanks", "В благодарность"],
  ["event", "С важным событием"],
  ["other", "Другое"],
];

const BODY_H = 86;
const FLAME_H = 28;
const LABEL_GAP = 16;

const canvas = document.getElementById("board");
const ctx = canvas.getContext("2d");
const tabsEl = document.getElementById("tabs");
const whoEl = document.getElementById("who");
const loginEl = document.getElementById("login");
const logoutEl = document.getElementById("logout");

let state = emptyState();
let drag = null;
let userId = null;

function emptyState() {
  const tabs = {};
  for (const [id] of TABS) tabs[id] = [];
  return { active: "health", tabs };
}

function thicknessOf(c) {
  return c.size === "large" ? 2.25 : 1.5;
}

/** При сгорании уменьшается только высота; толщина как у новой свечи. */
function heightScaleOf(c) {
  return thicknessOf(c) * remainingOf(c);
}

function colorsOf(c) {
  if (c.size === "large") return ["#f0c85e", "#d4a338", "#ffe08a"];
  return ["#e2b34a", "#c4922c", "#f3d27a"];
}

let candleSettings = {
  life_small_sec: 5400,
  life_large_sec: 10800,
  check_interval_sec: 300,
};
let burnTimer = null;

function lifeSec(c) {
  return c.size === "large" ? candleSettings.life_large_sec : candleSettings.life_small_sec;
}

function remainingOf(c) {
  const created = Date.parse(c.created_at);
  if (!Number.isFinite(created)) return 1;
  const lifeMs = Math.max(lifeSec(c), 1) * 1000;
  const rem = 1 - (Date.now() - created) / lifeMs;
  return Math.max(0, Math.min(1, rem));
}

function utcNowIso() {
  return new Date().toISOString();
}

function currentCandles() {
  return state.tabs[state.active];
}

/** Пиксели ↔ доли от центра; мера — min(ширина, высота), чтобы на wide/tall не разъезжалось. */
function refSize() {
  return Math.max(Math.min(canvas.width, canvas.height), 1);
}

function screenOf(c) {
  const s = refSize();
  return {
    x: canvas.width * 0.5 + c.nx * s,
    y: canvas.height * 0.5 + c.ny * s,
  };
}

function storeFromScreen(c, x, y) {
  const s = refSize();
  c.nx = (x - canvas.width * 0.5) / s;
  c.ny = (y - canvas.height * 0.5) / s;
  c.x = x;
  c.y = y;
}

function syncScreen(c) {
  const p = screenOf(c);
  c.x = p.x;
  c.y = p.y;
}

function normalizeCandle(raw) {
  const c = {
    caption: typeof raw.caption === "string" ? raw.caption : "",
    size: raw.size === "large" ? "large" : "small",
    created_at: typeof raw.created_at === "string" && raw.created_at ? raw.created_at : utcNowIso(),
    nx: 0,
    ny: 0,
    x: 0,
    y: 0,
  };
  const nx = Number(raw.nx);
  const ny = Number(raw.ny);
  const x = Number(raw.x);
  const y = Number(raw.y);
  if (Number.isFinite(nx) && Number.isFinite(ny)) {
    c.nx = nx;
    c.ny = ny;
    syncScreen(c);
  } else if (Number.isFinite(x) && Number.isFinite(y)) {
    storeFromScreen(c, x, y);
  } else {
    c.nx = 0;
    c.ny = 0.12;
    syncScreen(c);
  }
  return c;
}

function normalizeState(loaded) {
  const next = emptyState();
  if (loaded && loaded.active && TABS.some(([id]) => id === loaded.active)) {
    next.active = loaded.active;
  }
  const tabs = (loaded && loaded.tabs) || {};
  for (const [id] of TABS) {
    const items = Array.isArray(tabs[id]) ? tabs[id] : [];
    next.tabs[id] = items.map(normalizeCandle);
  }
  return next;
}

function pruneBurnedLocal() {
  let removed = false;
  for (const [id] of TABS) {
    const before = state.tabs[id].length;
    state.tabs[id] = state.tabs[id].filter((c) => remainingOf(c) > 0);
    if (state.tabs[id].length !== before) removed = true;
  }
  return removed;
}

function applySettings(settings) {
  if (!settings || typeof settings !== "object") return;
  candleSettings = {
    life_small_sec: Math.max(60, Number(settings.life_small_sec) || 5400),
    life_large_sec: Math.max(60, Number(settings.life_large_sec) || 10800),
    check_interval_sec: Math.max(60, Number(settings.check_interval_sec) || 300),
  };
  if (burnTimer) clearInterval(burnTimer);
  burnTimer = setInterval(() => {
    if (pruneBurnedLocal()) save();
  }, candleSettings.check_interval_sec * 1000);
}

async function ingestStateResponse(data) {
  const payload = data && data.state ? data : { state: data, settings: null };
  if (payload.settings) applySettings(payload.settings);
  state = normalizeState(payload.state || payload);
  if (pruneBurnedLocal()) await save();
  renderTabs();
}

function hit(c, x, y) {
  const tw = thicknessOf(c);
  const th = heightScaleOf(c);
  const top = c.y - (BODY_H + FLAME_H) * th;
  const bottom = c.y + LABEL_GAP + 18;
  return Math.abs(x - c.x) <= 22 * tw && y >= top && y <= bottom;
}

function candleAt(x, y) {
  const list = currentCandles();
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (hit(list[i], x, y)) return list[i];
  }
  return null;
}

function clamp(c) {
  const tw = thicknessOf(c);
  const th = heightScaleOf(c);
  const margin = 24 * tw;
  const x = Math.min(Math.max(c.x, margin), canvas.width - margin);
  const y = Math.min(Math.max(c.y, (BODY_H + FLAME_H) * th + 8), canvas.height - 36);
  storeFromScreen(c, x, y);
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(rect.width, 40);
  canvas.height = Math.max(rect.height, 40);
  for (const [, list] of Object.entries(state.tabs)) {
    for (const c of list) syncScreen(c);
  }
}

function point(ev) {
  const rect = canvas.getBoundingClientRect();
  const src = ev.touches && ev.touches[0] ? ev.touches[0] : ev;
  return { x: src.clientX - rect.left, y: src.clientY - rect.top };
}

const churchBg = new Image();
churchBg.src = "/church-bg.png";

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawScene() {
  if (churchBg.naturalWidth) {
    const iw = churchBg.naturalWidth;
    const ih = churchBg.naturalHeight;
    const scale = Math.max(canvas.width / iw, canvas.height / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    ctx.drawImage(churchBg, (canvas.width - dw) / 2, (canvas.height - dh) / 2, dw, dh);
    ctx.fillStyle = "rgba(8, 5, 4, 0.28)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  } else {
    ctx.fillStyle = "#140f0c";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
}

function drawCandle(c, t) {
  const tw = thicknessOf(c);
  const th = Math.max(heightScaleOf(c), 0.05);
  const [wax, dark, light] = colorsOf(c);
  const top = c.y - BODY_H * th;
  const wobble = 1.2 * tw * Math.sin(t * 0.007 + c.x * 0.04);
  const height = (20 + 4 * Math.sin(t * 0.011 + c.y * 0.03)) * th;
  const halfBot = 3.4 * tw;
  const halfTop = 2.1 * tw;
  const dripSide = Math.round(c.nx * 1000) % 2 === 0 ? 1 : -1;

  const glow = ctx.createRadialGradient(c.x + wobble, top - 8 * th, 2 * tw, c.x, top, 38 * Math.max(tw, th));
  glow.addColorStop(0, "rgba(255, 180, 70, 0.38)");
  glow.addColorStop(0.45, "rgba(180, 90, 20, 0.12)");
  glow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.ellipse(c.x, top - 4 * th, 28 * tw, 32 * th, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#ff9a3a";
  ctx.beginPath();
  ctx.moveTo(c.x + wobble, top - 7 * th - height);
  ctx.quadraticCurveTo(c.x + 6 * tw + wobble, top - 2 * th, c.x + wobble * 0.3, top - 2 * th);
  ctx.quadraticCurveTo(c.x - 6 * tw + wobble, top - 2 * th, c.x + wobble, top - 7 * th - height);
  ctx.fill();

  ctx.fillStyle = "#ffe9a0";
  ctx.beginPath();
  ctx.moveTo(c.x + wobble * 0.6, top - 5 * th - height * 0.62);
  ctx.quadraticCurveTo(c.x + 2.6 * tw, top - 2 * th, c.x, top - 1.5 * th);
  ctx.quadraticCurveTo(c.x - 2.6 * tw, top - 2 * th, c.x + wobble * 0.6, top - 5 * th - height * 0.62);
  ctx.fill();

  const body = ctx.createLinearGradient(c.x - halfBot, top, c.x + halfBot, c.y);
  body.addColorStop(0, light);
  body.addColorStop(0.45, wax);
  body.addColorStop(1, dark);
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.moveTo(c.x - halfBot, c.y);
  ctx.lineTo(c.x + halfBot, c.y);
  ctx.lineTo(c.x + halfTop, top);
  ctx.lineTo(c.x - halfTop, top);
  ctx.closePath();
  ctx.fill();

  // капля воска только пока свеча ещё достаточно высокая
  if (th > 0.35 * tw) {
    const dripH = Math.min(1, th / tw);
    ctx.fillStyle = dark;
    ctx.beginPath();
    ctx.moveTo(c.x + dripSide * (halfTop + 0.4 * tw), top + 10 * th);
    ctx.quadraticCurveTo(
      c.x + dripSide * (halfBot + 1.8 * tw),
      top + 28 * th * dripH,
      c.x + dripSide * halfBot,
      top + 46 * th * dripH,
    );
    ctx.quadraticCurveTo(
      c.x + dripSide * (halfBot - 0.6 * tw),
      top + 24 * th * dripH,
      c.x + dripSide * halfTop,
      top + 12 * th,
    );
    ctx.fill();
  }

  ctx.fillStyle = light;
  ctx.beginPath();
  ctx.ellipse(c.x, top + 1.2 * th, 2.6 * tw, 2.2 * tw, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = "#1a120c";
  ctx.lineWidth = Math.max(1, 1.2 * tw);
  ctx.beginPath();
  ctx.moveTo(c.x, top - 1 * th);
  ctx.lineTo(c.x, top - 8 * th);
  ctx.stroke();
  ctx.fillStyle = "#3a2214";
  ctx.beginPath();
  ctx.arc(c.x, top - 8 * th, 0.7 * tw, 0, Math.PI * 2);
  ctx.fill();

  if (c.caption) {
    ctx.font = "600 14px 'Source Sans 3', sans-serif";
    ctx.textAlign = "center";
    const label = c.caption;
    const w = Math.min(ctx.measureText(label).width + 16, 140);
    ctx.fillStyle = "rgba(12, 8, 6, 0.62)";
    roundRect(c.x - w / 2, c.y + 8, w, 22, 4);
    ctx.fill();
    ctx.fillStyle = "#f3e6c8";
    ctx.fillText(label, c.x, c.y + 24, 128);
  }
}

function frame(t) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawScene();
  for (const c of currentCandles()) drawCandle(c, t);
  requestAnimationFrame(frame);
}

function renderTabs() {
  tabsEl.innerHTML = "";
  for (const [id, title] of TABS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = title;
    if (id === state.active) btn.classList.add("active");
    btn.addEventListener("click", () => {
      state.active = id;
      renderTabs();
      save();
    });
    tabsEl.appendChild(btn);
  }
}

function payloadForSave() {
  const tabs = {};
  for (const [id] of TABS) {
    tabs[id] = state.tabs[id].map((c) => ({
      nx: Math.round(c.nx * 1e5) / 1e5,
      ny: Math.round(c.ny * 1e5) / 1e5,
      x: Math.round(c.x * 10) / 10,
      y: Math.round(c.y * 10) / 10,
      caption: c.caption,
      size: c.size,
      created_at: c.created_at,
    }));
  }
  return { state: { active: state.active, tabs } };
}

function addCandle(size) {
  if (!userId) return needLogin();
  const text = prompt("Как подписать эту свечу?", "");
  if (text === null) return;
  const n = currentCandles().length;
  const c = normalizeCandle({
    nx: ((n % 6) - 2.5) * 0.08,
    ny: 0.12 + Math.floor(n / 6) * 0.06,
    caption: text.trim(),
    size,
    created_at: utcNowIso(),
  });
  clamp(c);
  currentCandles().push(c);
  save();
}

async function save() {
  if (!userId) return;
  const res = await fetch("/api/state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payloadForSave()),
  });
  if (!res.ok) return;
  const data = await res.json();
  if (data && data.state) {
    state = normalizeState(data.state);
    if (data.settings) applySettings(data.settings);
    renderTabs();
  }
}

function needLogin() {
  alert("Сначала войди через Яндекс.");
}

function startDrag(ev) {
  const p = point(ev);
  const c = candleAt(p.x, p.y);
  if (!c) return false;
  drag = { c, dx: p.x - c.x, dy: p.y - c.y, moved: false };
  return true;
}

function moveDrag(ev) {
  if (!drag) return;
  const p = point(ev);
  storeFromScreen(drag.c, p.x - drag.dx, p.y - drag.dy);
  clamp(drag.c);
  drag.moved = true;
}

function endDrag() {
  if (drag && drag.moved) save();
  drag = null;
}

canvas.addEventListener("mousedown", (ev) => {
  if (ev.button !== 0) return;
  startDrag(ev);
});

canvas.addEventListener("mousemove", (ev) => moveDrag(ev));
window.addEventListener("mouseup", () => endDrag());

canvas.addEventListener(
  "touchstart",
  (ev) => {
    if (startDrag(ev)) ev.preventDefault();
  },
  { passive: false },
);
canvas.addEventListener(
  "touchmove",
  (ev) => {
    if (!drag) return;
    ev.preventDefault();
    moveDrag(ev);
  },
  { passive: false },
);
canvas.addEventListener("touchend", () => endDrag());
canvas.addEventListener("touchcancel", () => endDrag());

canvas.addEventListener("dblclick", (ev) => {
  const p = point(ev);
  const c = candleAt(p.x, p.y);
  if (!c) return;
  const text = prompt("Текст у этой свечи:", c.caption || "");
  if (text === null) return;
  c.caption = text.trim();
  save();
});

canvas.addEventListener("contextmenu", (ev) => {
  ev.preventDefault();
  const p = point(ev);
  const c = candleAt(p.x, p.y);
  if (!c) return;
  const name = c.caption || "без подписи";
  const title = TABS.find((t) => t[0] === state.active)[1];
  if (!confirm(`Убрать эту свечу (${name}) с вкладки «${title}»?`)) return;
  state.tabs[state.active] = currentCandles().filter((item) => item !== c);
  save();
});

document.getElementById("add-small").addEventListener("click", () => addCandle("small"));
document.getElementById("add-large").addEventListener("click", () => addCandle("large"));
document.getElementById("clear-all").addEventListener("click", () => {
  if (!userId) return needLogin();
  const title = TABS.find((t) => t[0] === state.active)[1];
  if (!currentCandles().length) return;
  if (!confirm(`Убрать все свечи только на вкладке «${title}»?`)) return;
  state.tabs[state.active] = [];
  save();
});
logoutEl.addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  location.reload();
});

async function boot() {
  resize();
  window.addEventListener("resize", resize);
  renderTabs();
  requestAnimationFrame(frame);
  try {
    const pub = await (await fetch("/api/settings")).json();
    applySettings(pub);
  } catch (_e) {
    /* defaults */
  }
  const me = await (await fetch("/api/me")).json();
  const adminLink = document.getElementById("admin-link");
  if (adminLink) adminLink.hidden = false;
  if (me.user_id) {
    userId = me.user_id;
    const label = me.email || me.login || me.display_name || "вход выполнен";
    whoEl.textContent = label;
    loginEl.hidden = true;
    logoutEl.hidden = false;
    const loaded = await (await fetch("/api/state")).json();
    await ingestStateResponse(loaded);
  } else {
    whoEl.textContent = me.auth_configured ? "нужен вход" : "в .env ещё нет ключей Яндекса";
  }
}

boot();
