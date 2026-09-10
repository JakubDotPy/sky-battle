/**
 * sky-battle replay viewer.
 *
 * Loads a replay written by the engine (one JSON header line, then one JSON
 * frame per tick -- contract in docs/plans/2026-09-10-browser-viewer.md) and
 * renders it to a canvas. Holds NO game logic: every fact drawn -- position,
 * heading, hp, alive, ammo, score -- already exists in the stream. If a fact
 * isn't there, it isn't drawn here either.
 *
 * Vanilla ES2020, canvas 2D, no build step, no dependencies.
 */

"use strict";

// Step 1 -- tunables. Rendering-only constants, never derived game facts.
const TICK_HZ = 30; // matches the engine's fixed dt = 1/30 (tech-decisions.md sec 8)
const MARGIN_PX = 28;
const GRID_STEP = 200; // arena units between grid lines
// Track symbology, the HSD idiom: SHAPE says class, COLOUR says squadron, and a
// separate velocity vector says heading. Moving heading onto its own stick is what
// buys the shape channel -- and a 1px stick reads heading more precisely at this
// scale than the rotation of a 7px triangle ever did.
const KIND_SYMBOL = { scout: "circle", fighter: "chevron", bomber: "square" };
const KIND_RADIUS = { scout: 6, fighter: 7.5, bomber: 10 }; // symbol half-extent AND click radius, px
const DEFAULT_RADIUS = 7;
const VECTOR_BASE_PX = 5; // stick length at a standstill
const VECTOR_PER_SPEED = 1.15; // px per unit of speed: the vector's LENGTH encodes speed, as a real one does
const SILHOUETTE_SCALE = 1.75; // the selected plane is promoted to a planform this much larger
const BRACKET_PAD = 7; // gap between the selected plane and its target brackets
const BULLET_RADIUS = 2;
const DEAD_ALPHA = 0.35;
const FOG_ALPHA = 0.3; // enemy plane absent from the selected squadron's visible[] this tick
const SELECT_HIT_PAD = 6; // extra px of click slop beyond a plane's drawn radius
const CONE_FILL_ALPHA = 0.12;
const CONE_EDGE_ALPHA = 0.5;
const BUBBLE_EDGE_ALPHA = 0.22; // subordinate to the cone -- context, not the subject
const TRAIL_LENGTH = 40; // ticks of position history drawn behind each plane
const TRAIL_ALPHA_MAX = 0.55; // alpha of the newest trail segment; fades to 0 with age

const canvas = document.getElementById("arena");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const selectionEl = document.getElementById("selection");
const panelEl = document.getElementById("panel");
const degradedBadgeEl = document.getElementById("degraded-badge");
const degradedTicksEl = document.getElementById("degraded-ticks");
const roundSelect = document.getElementById("round-select");
const tickReadout = document.getElementById("tick-readout");
const frameReadout = document.getElementById("frame-readout");
const scoreEls = [document.getElementById("score-0"), document.getElementById("score-1")];
const botNamesEl = document.getElementById("bot-names");
const scrub = document.getElementById("scrub");
const playBtn = document.getElementById("play");
const stepBackBtn = document.getElementById("step-back");
const stepFwdBtn = document.getElementById("step-fwd");
const speedBtns = [...document.querySelectorAll(".speed-group button")];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Palette lives in index.html as CSS custom properties; read once so the
// canvas and the DOM never disagree about a colour.
const GRID_COLOR = cssVar("--grid");
const BORDER_COLOR = cssVar("--border");
const ACCENT_COLOR = cssVar("--accent");
const SQUADRON_COLORS = [cssVar("--squadron-0"), cssVar("--squadron-1"), "#c792ea", "#8bd450"];

const state = {
  header: null,
  frames: [],
  index: 0,
  playing: false,
  speed: 1,
  scale: 1,
  originX: 0,
  originY: 0,
  selectedId: null, // keyed on plane id, never array index -- persists across ticks and seam copies
};

// Step 2 -- resolve which round to show and load it
async function main() {
  const requested = new URLSearchParams(location.search).get("replay");
  let rounds = [];
  try {
    rounds = await fetchRounds();
  } catch (err) {
    if (!requested) {
      showStatus(`load failed: ${err.message}`);
      console.error(err);
      return;
    }
    console.warn("rounds.json unavailable, loading ?replay= directly:", err);
  }

  const name = requested || (rounds[0] && rounds[0].name);
  if (!name) {
    showStatus("load failed: no replay found (empty /rounds.json and no ?replay= given)");
    return;
  }
  populateRoundSelect(rounds, name);
  try {
    await loadReplay(name);
  } catch (err) {
    showStatus(`load failed: ${err.message}`);
    console.error(err);
  }
}

async function fetchRounds() {
  const res = await fetch("/rounds.json");
  if (!res.ok) throw new Error(`GET /rounds.json -> ${res.status}`);
  const data = await res.json();
  const list = Array.isArray(data) ? data : Array.isArray(data.rounds) ? data.rounds : [];
  return list.map((entry) => {
    if (typeof entry === "string") return { name: entry };
    return { name: entry.name ?? entry.file ?? entry.filename, seed: entry.seed, frames: entry.frames };
  });
}

// "round-001 · seed 7 · 831 frames" -- whatever of seed/frames rounds.json actually gave us.
function roundLabel(r) {
  const base = r.name.replace(/\.fat\.jsonl\.gz$/, "");
  const bits = [];
  if (r.seed !== undefined) bits.push(`seed ${r.seed}`);
  if (r.frames !== undefined) bits.push(`${r.frames} frames`);
  return bits.length ? `${base} · ${bits.join(" · ")}` : base;
}

function populateRoundSelect(rounds, selected) {
  if (rounds.length < 2) return;
  roundSelect.hidden = false;
  roundSelect.replaceChildren(
    ...rounds.map((r) => {
      const opt = document.createElement("option");
      opt.value = r.name;
      opt.textContent = roundLabel(r);
      if (r.name === selected) opt.selected = true;
      return opt;
    }),
  );
  // Swap the replay in place rather than navigating: a full page load would
  // re-fetch everything and throw away the scrub position for no reason. The
  // URL still gets ?replay= updated (via replaceState) so links stay sharable.
  roundSelect.addEventListener("change", async () => {
    const url = new URL(location.href);
    url.searchParams.set("replay", roundSelect.value);
    history.replaceState(null, "", url.toString());
    try {
      await loadReplay(roundSelect.value);
    } catch (err) {
      showStatus(`load failed: ${err.message}`);
      console.error(err);
    }
  });
}

async function loadReplay(name) {
  showStatus(`loading ${name}...`);
  const res = await fetch(`/replay/${name}`);
  if (!res.ok) throw new Error(`GET /replay/${name} -> ${res.status}`);
  // The server sends Content-Encoding: gzip; the browser decompresses this
  // transparently. Never gunzip in JS -- res.text() already sees plain JSONL.
  const text = await res.text();
  const lines = text.split("\n").filter((l) => l.length > 0);
  if (lines.length < 1) throw new Error(`${name} is empty`);

  state.header = JSON.parse(lines[0]);
  state.frames = lines.slice(1).map((l) => JSON.parse(l));
  state.index = 0;
  state.playing = false;
  state.selectedId = null; // a new replay's plane ids mean nothing to the old selection
  playBtn.textContent = "Play";
  scrub.max = String(Math.max(0, state.frames.length - 1));
  scrub.value = "0";
  renderDegradedTicks();

  const frag = document.createDocumentFragment();
  state.header.bots.forEach((b, i) => {
    if (i > 0) frag.appendChild(document.createTextNode("  vs  "));
    const span = document.createElement("span");
    span.className = `bot-${i}`;
    span.textContent = basename(b.path);
    frag.appendChild(span);
  });
  botNamesEl.replaceChildren(frag);

  showStatus("");
  resizeCanvas();
  render();
}

function basename(path) {
  return path.split("/").pop();
}

function showStatus(msg) {
  statusEl.textContent = msg;
}

// Step 3 -- canvas sizing. One arena-to-pixel scale factor, recomputed only
// here, read everywhere else. A stale scale after resize is the obvious bug.
function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (!state.header) return;
  const [arenaW, arenaH] = state.header.arena;
  const availW = Math.max(1, cssW - MARGIN_PX * 2);
  const availH = Math.max(1, cssH - MARGIN_PX * 2);
  state.scale = Math.min(availW / arenaW, availH / arenaH);
  state.originX = (cssW - arenaW * state.scale) / 2;
  state.originY = (cssH - arenaH * state.scale) / 2;
  render();
}

new ResizeObserver(resizeCanvas).observe(canvas);

// World (x right, y up) -> canvas pixel (y down). This is the one flip in
// the whole renderer; every draw call goes through px/py, never raw x/y.
function px(x) {
  return state.originX + x * state.scale;
}
function py(y) {
  const [, arenaH] = state.header.arena;
  return state.originY + (arenaH - y) * state.scale;
}

// The letterboxed arena rect in canvas-relative pixels, shared by render()
// (as a clip) and hitTestPlane() (a click outside it hit nothing, since
// nothing is drawn out there).
function arenaRect() {
  const [arenaW, arenaH] = state.header.arena;
  return { left: px(0), top: py(arenaH), w: arenaW * state.scale, h: arenaH * state.scale };
}

// Step 4 -- draw one frame
function render() {
  if (!state.header || state.frames.length === 0) return;
  const frame = state.frames[state.index];
  const [arenaW, arenaH] = state.header.arena;
  const rect = arenaRect();

  // A selected plane's id can vanish from a frame (round change, truncated
  // replay); when it does, the selection drops rather than pointing at
  // nothing.
  const selected = frame.planes.find((p) => p.id === state.selectedId) ?? null;
  if (state.selectedId !== null && !selected) state.selectedId = null;

  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  drawArena(arenaW, arenaH, rect);

  // The canvas viewport is letterboxed around the (square) arena, so an
  // off-edge seam copy can still land inside the canvas without being near
  // the real border. Clip to the arena rect itself so only the copies that
  // actually straddle the torus seam are visible.
  ctx.save();
  ctx.beginPath();
  ctx.rect(rect.left, rect.top, rect.w, rect.h);
  ctx.clip();
  drawSeamCopies(arenaW, arenaH, () => {
    // Trails first (furthest back), then cones/bubble, so plane/bullet sprites
    // stay crisp on top of both.
    for (const p of frame.planes) drawTrail(p);
    if (selected && selected.alive) {
      drawCones(selected);
      drawBubble(selected);
    }
    for (const b of frame.bullets) drawBullet(b);
    for (const p of frame.planes) drawPlane(p, selected, frame.visible);
  });
  ctx.restore();

  drawReadout(frame);
  drawDegradedBadge(frame);
  drawSelection(selected);
  drawPanel(frame);
}

function drawArena(arenaW, arenaH, rect) {
  const { left, top, w, h } = rect;

  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x <= arenaW; x += GRID_STEP) {
    ctx.moveTo(px(x), top);
    ctx.lineTo(px(x), top + h);
  }
  for (let y = 0; y <= arenaH; y += GRID_STEP) {
    ctx.moveTo(left, py(y));
    ctx.lineTo(left + w, py(y));
  }
  ctx.stroke();

  ctx.strokeStyle = BORDER_COLOR;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(left, top, w, h);
}

// Seam wrap: the arena is a torus, so a sprite near an edge must appear on
// both sides. Draw at (x + ox, y + oy) for the eight neighbouring offsets
// too; canvas clips the ones that land off-screen for free. Shared with
// hitTestPlane below so a click is tested against every drawn copy, not just
// the plane's single arena position.
function seamOffsets(arenaW, arenaH) {
  const offsets = [];
  for (const ox of [-arenaW, 0, arenaW]) {
    for (const oy of [-arenaH, 0, arenaH]) offsets.push([ox, oy]);
  }
  return offsets;
}

function drawSeamCopies(arenaW, arenaH, drawFn) {
  for (const [ox, oy] of seamOffsets(arenaW, arenaH)) {
    ctx.save();
    ctx.translate(ox * state.scale, -oy * state.scale); // -oy: canvas y is flipped
    drawFn();
    ctx.restore();
  }
}

function drawBullet(bullet) {
  const [x, y, squadron] = bullet;
  ctx.fillStyle = squadronColor(squadron);
  ctx.beginPath();
  ctx.arc(px(x), py(y), BULLET_RADIUS, 0, Math.PI * 2);
  ctx.fill();
}

// A fading polyline of `plane`'s last TRAIL_LENGTH positions -- this is what
// makes turn rate and energy bleed visible. Recomputed fresh from the recorded
// frames every render rather than accumulated during playback, so scrubbing
// backwards shows the correct trail instead of one built for forward motion.
function drawTrail(plane) {
  const [arenaW, arenaH] = state.header.arena;
  const start = Math.max(0, state.index - TRAIL_LENGTH);
  let prev = null; // [x, y] of the previous plotted tick, or null to start a fresh segment

  ctx.save();
  ctx.strokeStyle = squadronColor(plane.squadron);
  ctx.lineWidth = 1.25;
  for (let i = start; i <= state.index; i++) {
    const p = state.frames[i].planes.find((pl) => pl.id === plane.id);
    if (!p) {
      prev = null;
      continue;
    }
    // A torus wrap teleports x/y by roughly a whole arena dimension in one
    // tick; a jump that large is the seam, not real motion, so break the
    // polyline instead of drawing a line straight across the arena.
    const wrapped = prev && (Math.abs(p.x - prev[0]) > arenaW / 2 || Math.abs(p.y - prev[1]) > arenaH / 2);
    if (prev && !wrapped) {
      const age = state.index - i; // 0 = current tick, larger = older
      ctx.globalAlpha = TRAIL_ALPHA_MAX * (1 - age / (TRAIL_LENGTH + 1));
      ctx.beginPath();
      ctx.moveTo(px(prev[0]), py(prev[1]));
      ctx.lineTo(px(p.x), py(p.y));
      ctx.stroke();
    }
    prev = [p.x, p.y];
  }
  ctx.restore();
}

// `selected` and `visible` are only passed when a plane is selected; both
// are null/undefined otherwise, which reads as "no dimming, no highlight".
//
// Track symbology: a screen-aligned symbol for class, a velocity vector for
// heading and speed, squadron colour for identity, and fill for whether the
// selected squadron can actually see it. The selected plane is promoted from a
// symbol to an aircraft planform -- which is exactly what a real display does
// for ownship among a field of tracks.
function drawPlane(plane, selected, visible) {
  const size = KIND_RADIUS[plane.kind] ?? DEFAULT_RADIUS;
  const cx = px(plane.x);
  const cy = py(plane.y);
  const color = squadronColor(plane.squadron);
  const isSelected = selected != null && plane.id === selected.id;

  // Fog of war is about ENEMY knowledge: an enemy plane absent from the
  // selected squadron's recorded visible[] list this tick is dimmed.
  // Squadron-mates are never dimmed by this rule.
  let dim = false;
  if (selected && plane.squadron !== selected.squadron) {
    const seen = visible[String(selected.squadron)] ?? []; // visible{} keys are strings in JSON
    dim = !seen.includes(plane.id);
  }

  ctx.save();
  ctx.globalAlpha = plane.alive ? (dim ? FOG_ALPHA : 1) : DEAD_ALPHA;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.25;

  if (!plane.alive) {
    drawWreck(cx, cy, size); // no vector: a wreck is not going anywhere
  } else {
    drawVelocityVector(cx, cy, plane, dim);
    if (isSelected) drawSilhouette(cx, cy, plane, size * SILHOUETTE_SCALE);
    else drawTrackSymbol(cx, cy, plane, size, dim);
  }
  ctx.restore();

  if (isSelected) drawTargetBrackets(cx, cy, size * SILHOUETTE_SCALE + BRACKET_PAD);
}

// Length encodes speed, direction encodes heading -- both facts the stream
// already carries, and the reason the symbols themselves need no rotation.
function drawVelocityVector(cx, cy, plane, dim) {
  const len = VECTOR_BASE_PX + plane.speed * VECTOR_PER_SPEED;
  const rad = (plane.heading_deg * Math.PI) / 180;
  ctx.save();
  ctx.lineWidth = 1;
  if (dim) ctx.setLineDash([2, 2]); // an unseen track is a dead-reckoned guess
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(rad) * len, cy - Math.sin(rad) * len); // -sin: canvas y is flipped
  ctx.stroke();
  ctx.restore();
}

// Filled when the selected squadron can see it, hollow when it cannot. The
// chevron is the one symbol that turns with the aircraft; a circle and a square
// gain nothing from rotating, and staying screen-aligned keeps them readable.
function drawTrackSymbol(cx, cy, plane, size, hollow) {
  const shape = KIND_SYMBOL[plane.kind] ?? "square";
  ctx.beginPath();
  if (shape === "circle") {
    ctx.arc(cx, cy, size * 0.72, 0, Math.PI * 2);
  } else if (shape === "chevron") {
    const rad = (plane.heading_deg * Math.PI) / 180;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-rad);
    ctx.moveTo(size * 0.85, 0);
    ctx.lineTo(-size * 0.5, size * 0.8);
    ctx.lineTo(-size * 0.5, -size * 0.8);
    ctx.closePath();
    hollow ? ctx.stroke() : ctx.fill();
    ctx.restore();
    return;
  } else {
    const h = size * 0.66;
    ctx.rect(cx - h, cy - h, h * 2, h * 2);
  }
  hollow ? ctx.stroke() : ctx.fill();
}

// The selected plane, drawn as a planform: nose, swept wings, tailplane. Points
// are fractions of `s` for the upper half and mirrored for the lower, so the
// silhouette stays symmetric by construction rather than by careful typing.
const SILHOUETTE = [
  [1.15, 0.0],
  [0.34, 0.13],
  [-0.08, 0.82],
  [-0.4, 0.82],
  [-0.28, 0.15],
  [-0.82, 0.15],
  [-0.78, 0.46],
  [-0.98, 0.46],
  [-1.08, 0.0],
];

function drawSilhouette(cx, cy, plane, s) {
  const rad = (plane.heading_deg * Math.PI) / 180;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-rad);
  ctx.beginPath();
  ctx.moveTo(SILHOUETTE[0][0] * s, 0);
  for (const [x, y] of SILHOUETTE) ctx.lineTo(x * s, y * s);
  for (let i = SILHOUETTE.length - 2; i >= 1; i--) {
    ctx.lineTo(SILHOUETTE[i][0] * s, -SILHOUETTE[i][1] * s);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// Target designator: four corner brackets, the display's own selection idiom.
function drawTargetBrackets(cx, cy, r) {
  const arm = r * 0.42;
  ctx.save();
  ctx.strokeStyle = ACCENT_COLOR;
  ctx.globalAlpha = 1;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    const x = cx + sx * r;
    const y = cy + sy * r;
    ctx.moveTo(x - sx * arm, y);
    ctx.lineTo(x, y);
    ctx.lineTo(x, y - sy * arm);
  }
  ctx.stroke();
  ctx.restore();
}

function drawWreck(cx, cy, size) {
  const a = size * 0.7;
  ctx.beginPath();
  ctx.moveTo(cx - a, cy - a);
  ctx.lineTo(cx + a, cy + a);
  ctx.moveTo(cx + a, cy - a);
  ctx.lineTo(cx - a, cy + a);
  ctx.stroke();
}

function squadronColor(squadron) {
  return SQUADRON_COLORS[squadron % SQUADRON_COLORS.length];
}

// Forward cone centred on heading_deg, rear cone (when the class has one)
// centred on heading_deg + 180. Both drawn as a low-alpha filled wedge with
// a brighter edge -- context, not the subject, and kept readable even where
// the two overlap.
function drawCones(plane) {
  const cx = px(plane.x);
  const cy = py(plane.y);
  const color = squadronColor(plane.squadron);
  if (plane.cone_deg > 0 && plane.cone_range > 0) {
    drawConeWedge(cx, cy, plane.heading_deg, plane.cone_deg, plane.cone_range, color);
  }
  if (plane.rear_cone_deg > 0 && plane.rear_cone_range > 0) {
    drawConeWedge(cx, cy, plane.heading_deg + 180, plane.rear_cone_deg, plane.rear_cone_range, color);
  }
}

// Heading-independent awareness radius, drawn as a dashed ring rather than the cone's filled
// wedge -- visually subordinate, since it is context for the cone, not the subject. Always the
// recorded bubble_range; never a number this file invents.
function drawBubble(plane) {
  if (!(plane.bubble_range > 0)) return;
  const cx = px(plane.x);
  const cy = py(plane.y);
  const radiusPx = plane.bubble_range * state.scale;

  ctx.save();
  ctx.globalAlpha = BUBBLE_EDGE_ALPHA;
  ctx.strokeStyle = squadronColor(plane.squadron);
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.arc(cx, cy, radiusPx, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawConeWedge(cx, cy, headingDeg, widthDeg, range, color) {
  const headingRad = (headingDeg * Math.PI) / 180;
  const halfAngle = (widthDeg * Math.PI) / 360; // widthDeg/2, in radians
  const rangePx = range * state.scale;

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-headingRad); // same y-flip as drawPlane's heading rotation
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.arc(0, 0, rangePx, -halfAngle, halfAngle);
  ctx.closePath();
  ctx.globalAlpha = CONE_FILL_ALPHA;
  ctx.fillStyle = color;
  ctx.fill();
  ctx.globalAlpha = CONE_EDGE_ALPHA;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.restore();
}

function drawReadout(frame) {
  tickReadout.textContent = String(frame.tick);
  frameReadout.textContent = `${state.index + 1} / ${state.frames.length}`;
  scrub.value = String(state.index);
  for (let i = 0; i < scoreEls.length; i++) {
    if (!scoreEls[i]) continue;
    const score = frame.scores[String(i)];
    const bot = state.header.bots[i];
    const label = bot ? basename(bot.path) : `SQ${i}`;
    scoreEls[i].textContent = `${label} ${score === undefined ? "--" : score.toFixed(1)}`;
  }
}

// A tick's degraded[] names the squadrons whose bot failed that tick -- crashed, timed out, or
// sent something invalid. Shown prominently rather than left to a log, and by bot filename so
// it says which bot, not which squadron index.
function drawDegradedBadge(frame) {
  if (!frame.degraded || frame.degraded.length === 0) {
    degradedBadgeEl.hidden = true;
    return;
  }
  const names = frame.degraded.map((sqStr) => {
    const bot = state.header.bots[Number(sqStr)];
    return bot ? basename(bot.path) : `SQ${sqStr}`;
  });
  degradedBadgeEl.textContent = `DEGRADED: ${names.join(", ")}`;
  degradedBadgeEl.hidden = false;
}

// The selected plane's own facts -- id, kind, hp, speed, per-gun ammo. Not
// the full side panel (that is V4), just enough to read while scrubbing.
function drawSelection(plane) {
  if (!plane) {
    selectionEl.hidden = true;
    return;
  }
  const color = squadronColor(plane.squadron);
  selectionEl.style.color = color;
  selectionEl.style.borderColor = color;
  selectionEl.textContent =
    `#${plane.id} SQ${plane.squadron} ${plane.kind}${plane.alive ? "" : " (dead)"}\n` +
    `hp ${plane.hp}/${plane.hp_max}  spd ${plane.speed.toFixed(1)}\n` +
    `ammo [${plane.ammo.join(", ")}]`;
  selectionEl.hidden = false;
}

// Step 5 -- timeline: scrub, step, play/pause, speed
function setIndex(i) {
  state.index = Math.max(0, Math.min(state.frames.length - 1, i));
  render();
}

function step(delta) {
  state.playing = false;
  playBtn.textContent = "Play";
  setIndex(state.index + delta);
}

function setPlaying(playing) {
  if (playing && state.index >= state.frames.length - 1) state.index = 0; // replay from the top
  state.playing = playing;
  playBtn.textContent = playing ? "Pause" : "Play";
}

// Small marks under the scrub track for every tick whose degraded[] is
// non-empty -- a bad tick is exactly what a viewer wants to jump to, so it
// belongs on the timeline, not only in the badge that flashes past during
// playback. Built once per replay load (the set never changes), not per render.
function renderDegradedTicks() {
  const total = state.frames.length;
  const marks = [];
  state.frames.forEach((f, i) => {
    if (!f.degraded || f.degraded.length === 0) return;
    const mark = document.createElement("span");
    mark.style.left = `${total > 1 ? (i / (total - 1)) * 100 : 0}%`;
    marks.push(mark);
  });
  degradedTicksEl.replaceChildren(...marks);
}

// Selection: click near a plane to select it, empty space to deselect. The
// arena is a torus, so a plane straddling the seam is drawn multiple times;
// hit-test every drawn copy's screen position, not just the plane's single
// arena position, so a click on either copy selects it.
canvas.addEventListener("click", (ev) => {
  if (!state.header || state.frames.length === 0) return;
  const rect = canvas.getBoundingClientRect();
  state.selectedId = hitTestPlane(ev.clientX - rect.left, ev.clientY - rect.top);
  render();
});

function hitTestPlane(clickX, clickY) {
  // The renderer clips every seam copy to the arena rect, so a copy whose
  // centre falls outside it (e.g. a plane far from the edge, whose ghost
  // copy lands in the letterbox margin) was never actually drawn there --
  // a click in that margin must not "reach through" to it.
  const rect = arenaRect();
  if (clickX < rect.left || clickX > rect.left + rect.w || clickY < rect.top || clickY > rect.top + rect.h) {
    return null;
  }

  const frame = state.frames[state.index];
  const [arenaW, arenaH] = state.header.arena;
  let bestId = null;
  let bestDist = Infinity;
  for (const plane of frame.planes) {
    const radius = (KIND_RADIUS[plane.kind] ?? DEFAULT_RADIUS) + SELECT_HIT_PAD;
    for (const [ox, oy] of seamOffsets(arenaW, arenaH)) {
      const sx = px(plane.x) + ox * state.scale;
      const sy = py(plane.y) - oy * state.scale; // -oy: matches drawSeamCopies' y flip
      const dist = Math.hypot(clickX - sx, clickY - sy);
      if (dist <= radius && dist < bestDist) {
        bestDist = dist;
        bestId = plane.id;
      }
    }
  }
  return bestId;
}

scrub.addEventListener("input", () => {
  state.playing = false;
  playBtn.textContent = "Play";
  setIndex(Number(scrub.value));
});
playBtn.addEventListener("click", () => setPlaying(!state.playing));
stepBackBtn.addEventListener("click", () => step(-1));
stepFwdBtn.addEventListener("click", () => step(1));

for (const btn of speedBtns) {
  btn.addEventListener("click", () => {
    state.speed = Number(btn.dataset.speed);
    for (const b of speedBtns) b.classList.toggle("active", b === btn);
  });
}

window.addEventListener("keydown", (ev) => {
  if (ev.target instanceof HTMLSelectElement) return;
  if (ev.code === "Space") {
    ev.preventDefault();
    setPlaying(!state.playing);
  } else if (ev.code === "ArrowLeft") {
    ev.preventDefault();
    step(-1);
  } else if (ev.code === "ArrowRight") {
    ev.preventDefault();
    step(1);
  }
});

// Step 6 -- playback clock: requestAnimationFrame against a wall-clock
// accumulator, so speed is real time, not frames-per-render-call.
const TICK_MS = 1000 / TICK_HZ;
let lastTs = null;
let accMs = 0;

function tickLoop(ts) {
  if (state.playing) {
    if (lastTs !== null) {
      accMs += Math.min(ts - lastTs, 250) * state.speed; // clamp a backgrounded-tab jump
      while (accMs >= TICK_MS) {
        accMs -= TICK_MS;
        if (state.index >= state.frames.length - 1) {
          setPlaying(false);
          break;
        }
        state.index++;
      }
      render();
    }
    lastTs = ts;
  } else {
    lastTs = null;
    accMs = 0;
  }
  requestAnimationFrame(tickLoop);
}
requestAnimationFrame(tickLoop);

// Step 7 -- squadron panel: per squadron its bot filename and score, per
// plane its kind, an hp bar against hp_max, and per-gun ammo. Clicking a
// plane selects it, reusing state.selectedId rather than a panel-local copy.
function drawPanel(frame) {
  const frag = document.createDocumentFragment();
  state.header.squadrons.forEach((_, sq) => frag.appendChild(buildSquadronBlock(sq, frame)));
  panelEl.replaceChildren(frag);
}

function buildSquadronBlock(sq, frame) {
  const color = squadronColor(sq);
  const block = document.createElement("div");
  block.className = "sq-block";

  const bot = state.header.bots[sq];
  const score = frame.scores[String(sq)];
  const head = document.createElement("div");
  head.className = "sq-head";
  head.style.color = color;
  head.textContent = `${bot ? basename(bot.path) : `SQ${sq}`}  ${score === undefined ? "--" : score.toFixed(1)}`;
  block.appendChild(head);

  for (const plane of frame.planes.filter((p) => p.squadron === sq)) {
    block.appendChild(buildPlaneRow(plane, color));
  }
  return block;
}

function buildPlaneRow(plane, color) {
  const row = document.createElement("div");
  row.className = "plane-row" + (plane.alive ? "" : " dead") + (plane.id === state.selectedId ? " selected" : "");
  row.dataset.planeId = String(plane.id);

  const label = document.createElement("div");
  label.className = "plane-label";
  label.textContent = `#${plane.id} ${plane.kind}`;
  const deadTag = document.createElement("span");
  deadTag.textContent = plane.alive ? "" : "DEAD";
  label.appendChild(deadTag);
  row.appendChild(label);

  const hpBar = document.createElement("div");
  hpBar.className = "hp-bar";
  const hpFill = document.createElement("div");
  hpFill.className = "hp-fill";
  hpFill.style.width = `${plane.hp_max > 0 ? Math.max(0, plane.hp / plane.hp_max) * 100 : 0}%`;
  hpFill.style.background = color;
  hpBar.appendChild(hpFill);
  row.appendChild(hpBar);

  const sub = document.createElement("div");
  sub.className = "plane-sub";
  sub.textContent = `hp ${plane.hp}/${plane.hp_max}  ammo [${plane.ammo.join(", ")}]`;
  row.appendChild(sub);

  return row;
}

panelEl.addEventListener("click", (ev) => {
  const row = ev.target.closest("[data-plane-id]");
  if (!row) return;
  state.selectedId = Number(row.dataset.planeId);
  render();
});

main();
