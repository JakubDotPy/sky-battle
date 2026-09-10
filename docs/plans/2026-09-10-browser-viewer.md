# Browser Viewer Implementation Plan

**Goal:** Watch a dogfight in a browser — scrub a finished round, click a plane, and see exactly what it could see.

**Architecture:** The engine already writes a "fat" replay carrying every derived field a viewer needs, so the viewer
holds **no game logic at all**. `sky-battle serve <dir>` runs a stdlib `http.server` that hands out the viewer page
(from package data), a JSON index of rounds, and the replay files themselves. Replays are already gzipped and are
served with `Content-Encoding: gzip`, so the browser decompresses natively and no gunzip exists in JavaScript.

**Tech stack:** Python 3.13+ stdlib only (`http.server`, `json`, `webbrowser`, `functools`); vanilla ES2020 and
canvas 2D with no build step.

**Spec:** `docs/design/tech-decisions.md` §3 (viewer), §1 (the stream-as-architecture decision).

## Global constraints

- **`dependencies = []` still holds.** No runtime dependency, and no JS bundler, framework or CDN.
- No camera, no pan, no zoom. The whole arena renders at once — that is what removes the camera problem on a torus.
- Seam-straddling sprites draw nine times at ±W/±H offsets; canvas clips the eight off-screen copies for free.
- The viewer never recomputes anything the replay records. If it needs a fact, the fact belongs in the stream.
- **Instrument look:** near-black ground, thin bright strokes, monospace labels. Legibility over decoration.
- Live SSE streaming is explicitly out of scope for this plan.

## The replay contract this reads

```text
header  seed, arena[w,h], squadrons[[kind,...],...], bots[{path,sha256}],
        class_table_sha256, class_table_source, engine_version, api_version, python_version
frame   tick, planes[], bullets[[x,y,squadron],...], visible{squadron:[plane_id,...]},
        scores{squadron:points}, degraded[squadron,...]
plane   id, squadron, kind, x, y, heading_deg, speed, hp, hp_max, alive,
        ammo[], cooldown[], cone_deg, cone_range, rear_cone_deg, rear_cone_range
```

A representative round: 831 frames, 41 KB gzipped.

## Files

| File | Responsibility |
|---|---|
| `src/skybattle/cli.py` | `serve` subcommand: request handler, round index, browser launch |
| `src/skybattle/viewer/index.html` | Markup and the instrument palette |
| `src/skybattle/viewer/viewer.js` | Load, parse, render, interact. No game logic |
| `tests/test_serve.py` | Server tests: page, index, replay bytes, gzip header, 404s, path safety |

## Tasks

### V1 — the `serve` subcommand

`sky-battle serve <replay-dir> [--port N] [--no-open]`. Serves `/` (the page), `/viewer.js`, `/rounds.json` (an
index of `*.fat.jsonl.gz` in the directory, newest first, with tick counts read from the header where cheap), and
`/replay/<name>` (the gzipped bytes, `Content-Type: application/json`, `Content-Encoding: gzip`). Opens a browser
unless `--no-open`. Refuses any path escaping the replay directory. Viewer files come from package data so an
installed wheel works.

Testable end to end: spawn the server on port 0, fetch each route, assert the page is served, the index lists the
round, the replay decodes to the expected frame count, and a `../` traversal attempt is refused.

### V2 — render and scrub

Load the replay, draw the arena and planes (heading-oriented triangles, per-squadron colour, dead planes marked),
bullets as points, and wire the timeline: scrub, play/pause, step one tick, and 1x/2x/4x speed. Draw the seam
copies. Show tick number and both scores.

### V3 — click a plane, see its world

Select a plane by clicking it. Draw its forward vision cone from `cone_deg`/`cone_range`, and its rear cone when
the class has one. Dim every enemy absent from that frame's `visible[squadron]`. Deselect by clicking empty space.
**This is the feature the whole architecture was shaped around.**

### V4 — trails, panel, and degraded ticks

Fading position trails over the last N ticks, which is what makes turn rate and energy bleed legible. A side panel
listing each squadron, its bot filename, its planes with hp and per-gun ammo bars, and its score. A visible badge on
any tick whose `degraded` list is non-empty, so a bot's bad tick is seen rather than buried in a log.

## Verification

The server is unit-tested. Rendering is not unit-testable without a browser, so each of V2–V4 is verified by driving
the page in Chrome and capturing a screenshot — not by asserting coverage that does not exist.
