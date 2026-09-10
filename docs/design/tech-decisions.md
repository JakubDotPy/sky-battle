# Sky Battle — technology decisions

**Status:** working draft, following research verified 2026-09-09. Figures below were measured, not estimated.
**Companion to:** [game-design.md](game-design.md)

## 1. The decision that makes every other one reversible

**The engine emits a per-tick state stream as JSONL. Every renderer is a consumer of that stream.** Native window,
terminal, browser, mp4 export — all become interchangeable downstream readers, so the renderer choice is never a
trap.

Corollary: **seed the RNG and keep ticks integer-indexed.** Replays and unattended tournament matches are only
meaningful if a match is bit-reproducible from `(seed, bot versions, stats file)`. The stats file gets stamped into
the replay header for the same reason.

This is what the prior art converged on independently. Robocode Tank Royale went furthest and made "observer" a
first-class role in its protocol precisely so the UI could be swapped out.

## 2. Runtime dependencies: none

The whole simulation, bot protocol, replay format and live viewer are achievable with the standard library alone.

| Concern | Chosen | Notes |
|---|---|---|
| Maths, integration | `math` | Plain floats. See §5 |
| Randomness | `random`, explicitly seeded | Reproducibility is the entire CI story |
| State objects | `typing.NamedTuple` | See §4 |
| Class stats | `tomllib` | Read-only stdlib TOML parser; humans write, engine reads |
| Bot protocol | `json` + `subprocess` | JSONL over stdio, Halite's model |
| Replay | `json` + `gzip` | Measured on a real 2v2: 2.19 MB raw to 0.25 MB compressed, **8.67x**, ~170 B/tick |
| Viewer | ~350 lines of vanilla JS + one `index.html`, canvas 2D | No build step |
| Live viewing | `http.server` + SSE, browser `EventSource` | ~15 lines |
| Tests | `pytest`, dev-only | |

Optional extras, behind a `render` extra so CI installs nothing: **pygame-ce** (2.5.8, actively developed — the
original `pygame` is classified `Development Status :: 6 - Mature` and last released 2024) and **imageio** +
`imageio-ffmpeg` for mp4 export. Verified: pygame-ce draws and saves from a bare `Surface` with **no display server
and no `set_mode()` call**, and `pygame.image.tobytes()` is the numpy-free readback path.

## 3. Viewer: replay file plus a static HTML canvas page

**Decided: browser, with both replay playback and live streaming.** The author's two use cases are debugging their
own bot and spectating with friends, and one page serves both; live adds ~15 stdlib lines (`http.server` + SSE +
`EventSource`, verified byte-by-byte). Desktop was explicitly ruled out.

Every comparable project renders in a browser, and **not one ships a native window as its primary viewer**:

| Project | Replay artefact | Viewer |
|---|---|---|
| Halite III | `.hlt`, zstd-compressed JSON | Electron + official Vue web app |
| Lux AI S1–S3 | `replay.json` | Web (`Lux Eye`) |
| Battlesnake | game JSON, CLI `replay` | SvelteKit + dynamic SVG |
| Tank Royale | recording per battle | WebSocket observers; community viewer in PixiJS |

**The decisive argument is the vision-cone debugger.** "What could squadron 2's bomber see at tick 431" is
fundamentally a UI problem — scrub a timeline, click a plane, toggle an overlay. The browser gives those affordances
for free; in pygame you would hand-roll a widget toolkit. Given fog of war is this game's core mechanic, seeing
through a specific plane's eyes at a specific tick is the single most valuable debugging feature the project can
have.

Build order for the viewer: **timeline scrub, then click-a-plane, then draw its cone and highlight only what it
could see**, then trails, then hit points and ammo.

**Torus rendering:** Halite, Lux and Battlesnake all draw the whole arena at once with no camera. Doing the same
makes the camera problem vanish. Seam-straddling sprites are handled by drawing nine copies at
`(x + ox, y + oy)` for `ox, oy` in `(-W, 0, W)`; canvas clips the eight off-screen ones for free.

**Textual was seriously considered and rejected for the arena** — a torus with cone fog needs sub-character
resolution, and SVG is its only export. **It is, however, the right tool for the tournament scoreboard,** which is a
table.

**Do not poll a growing `.jsonl` over HTTP:** `SimpleHTTPRequestHandler` does not honour `Range`, so every poll
re-downloads the entire file. Use SSE.

## 4. State objects: `NamedTuple`

Construction cost for 300 objects per tick — construction is what happens every tick, access is a wash:

| Shape | Per tick |
|---|---|
| plain `dict` | 24.3 µs |
| mutable slots dataclass | 27.1 µs |
| **`NamedTuple`** | **35.0 µs** |
| `@dataclass(frozen=True, slots=True)` | 95.8 µs |

The frozen dataclass — the option most people reach for — is **2.7× slower to build**, because every field goes
through `object.__setattr__`. A realistic squadron-shaped payload costs 22 µs per tick, which is 0.07% of the
budget, so **speed is not the deciding factor.**

**Ergonomics decide it.** `state.planes[0].heading` autocompletes, and a typo raises `AttributeError` at the
mistake; `state["planes"][0]["heading"]` gives a `KeyError` and no autocomplete. Being a `tuple` also means
`json.dumps` emits compact positional arrays with no custom encoder — 817 bytes versus 1242 self-describing, which
compounds over 1800 ticks — and `_asdict()` is available when a self-describing form is wanted.

Immutability was verified to block both field rebinding and roster growth. **Be honest about what that buys:** it
stops accidents, not a hostile bot, which can reach engine internals through any reference it holds. Real isolation
is the subprocess boundary — the same mechanism that enforces the deadline.

Runner-up: frozen slots dataclass, worth switching to for field defaults, validation, inheritance across plane
classes, or more than about eight fields where positional construction gets error-prone. **pydantic: no** —
per-tick validation of the engine's own correct output is pure overhead.

## 5. Plain floats, not numpy

Integration is 31.3 µs per tick in pure Python against 6.7 µs with numpy — a 4.7× win on 0.09% of the budget, so
irrelevant. Against it: **numpy's import costs 71–141 ms** (measured with `-X importtime`) versus 0.3 ms for the
standard library, on a 15.9 MiB wheel. For a process-per-match tournament the import tax exceeds the integration
saving by roughly 1500×.

**The real crossover is fog of war, and the game-design decision already settled it.** Filtering visibility costs
12.5 s per match in pure Python if bullets are visible, against 0.79 s with numpy — a 15.8× gap that would genuinely
justify the dependency. With bullets excluded from what a bot can see, the same filter costs **0.4 s** and plain
floats win comfortably. The two decisions are coupled, and both landed the same way.

## 6. Torus geometry: the minimum image convention

Standard practice from periodic boundary conditions in molecular simulation, not an invention. Reduce to the
shortest signed offset *first*, then every downstream geometry routine works unmodified:

```python
def wrap_delta(d, L):
    return (d + L / 2) % L - L / 2          # shortest signed offset
```

`wrap_delta` does **double duty**: with `L = 2 * pi` it is also the angle-difference function, which is the other
classic source of bugs here.

Three verified traps:

1. **Rear-gun bearings must rotate the frame, not the wrapped bearing.** Compute
   `torus_bearing(..., heading + pi, ...)`. Because `wrap_delta` maps onto `[-pi, +pi)`, an exactly-astern contact
   returns `-pi` in the forward frame; adding `pi` to *that* and taking the absolute value lands on the wrong side
   of the discontinuity. Rotating the frame before wrapping is correct at every angle. Gun mounts are then simply
   bearing offsets in the stats file, and a rear gun is `bearing = 180.0` rather than a subclass.
1. **Swept collision must be done in minimum-image relative coordinates, and the displacement vector must never be
   wrapped — only the start offset.** That one rule is the entire fix. Tunnelling is real at these speeds: a round
   travelling 30 units per tick against a 24-unit plane was **missed entirely** by naive point sampling, caught
   correctly by the swept test, with no false positive at 5 units of clearance and a 1-unit graze still detected.
1. **Precondition worth a comment in the code:** travel plus radius must stay below half the arena width (42 versus
   500 here, an order of magnitude of headroom). Otherwise substep with `n = ceil((step + r) / (W / 2))`.

## 7. Collision broad phase: none needed

Naive all-pairs with a squared-distance early-out, no `sqrt`, no spatial hash. The torus adds a ~5.5× tax to the
inner loop, and it still holds:

| Scale | Tests/tick | Per tick | % of a 30 Hz frame |
|---|---|---|---|
| 8 planes × 300 bullets | 2,400 | 833 µs | 2.5% |
| 16 × 300 (squadrons of 2) | 4,800 | 1,591 µs | 4.8% |
| 32 × 600 (squadrons of 4, rear guns) | 19,200 | 2,895 µs | 8.7% |

Cost is linear in planes × bullets. A spatial hash is awkward on a torus and only worth revisiting past roughly 100
planes or 5,000 bullets.

**Per-tick budget.** Terminology follows [game-design.md](game-design.md): a **round** is one fight of up to 3000
ticks, a **match** is 11 rounds.

| Scale | Integration | Collision | Fog | Snapshot | Per tick | Per full 3000-tick round |
|---|---|---|---|---|---|---|
| 8 planes / 300 bullets — a generous 2v2 | 45 µs | 833 µs | 221 µs | 22 µs | **1.12 ms** | **3.4 s** |
| 32 planes / 600 bullets — headroom case | 45 µs | 2,895 µs | 221 µs | 22 µs | 3.2 ms | 9.6 s |

Add ~0.27 s of protocol per round (§11), so a full-length 2v2 round costs about **3.7 s**, and most rounds end early
on a kill. A **double round-robin over 10 bots is 90 matches = 990 rounds ≈ 61 minutes on one core, ~8 minutes
across eight.** Collision is the only hot spot; everything else is noise.

## 8. Tick model: turn-based, as fast as possible, with a wall-clock deadline

Prior art: Robocode is turn-based with a compute allowance and skipped turns; Battlesnake enforces a hard ~500 ms
HTTP deadline; Halite III gives a per-turn budget with the bot as a subprocess over stdio; Screeps runs at about
1 Hz with a CPU allowance.

Fixed `dt = 1/30` is **game time, not a real-time obligation**. Enforce roughly 50 ms per tick per bot, but treat
the *timeout event*, not the elapsed time, as game input: on overrun, reuse the bot's last action and log a
`skipped_tick`. **Measured wall-clock must never affect simulated state** — that would destroy reproducibility,
which is the whole point of §1. Real-time pacing belongs only in the viewer, which then gets scrubbing and slow
motion for free.

Bots run as **subprocesses speaking JSONL over stdio**. One mechanism buys the deadline, crash containment,
isolation from engine internals, and language-agnosticism. Development can start in-process for iteration speed; the
snapshot serialises identically either way, so switching is a launcher change rather than a rewrite.

## 9. Packaging

`src/` layout, `requires-python = ">=3.13"`, and the headline `dependencies = []`. `[project.scripts]` exposes
`sky-battle` so `uvx sky-battle` works (or `uvx --from git+…` before publication), with subcommands `run`, `replay`,
`serve`, `tournament`. Ship `classes.toml` and `viewer/` as package data so `serve` hands the viewer out of the
wheel. Pin `ruff` and `ty` in `[dependency-groups]`.

**A bot is a single file with no I/O in it.** The engine's runner shim owns the protocol (see
[bot-api.md](bot-api.md)), so the author writes only a class with an `act` method — no `json`, no `flush=True`
deadlock to fall into, no stdout discipline to learn. The file can still carry PEP 723 inline metadata with
`dependencies = []` for the authors who want `uv run` to work on it directly.

## 10. Rejected

**Permanently:** pydantic (per-tick validation of our own output), Box2D / pybox2d (effectively dead, last release
2020), moderngl (no shader problem here), Ursina and Panda3D (overkill by an order of magnitude), matplotlib
animation, pysdl2, tcod (grid-native, wrong shape), and any SDL3 Python binding until pygame-ce 3.0 ships —
pygame-ce still bundles SDL 2.32.10 and is migrating module by module.

**No physics engine.** pymunk 7.3.0 is perfectly good and entirely unnecessary: there is no stacking, no joints, no
friction, no restitution. The time would go into disabling gravity and forcing velocities. Revisit only if terrain
or ramming gets added.

**Deferred, with the trigger that would change the answer:** numpy (if bots ever need to see bullets — 15.8× on
that filter — or past ~5,000 bullets), zstd (when gzip is outgrown), a spatial hash (past ~100 planes), pymunk (see
above).

## 11. The bot process boundary, measured

All figures measured on the development machine (Ryzen 7 250, kernel 6.17, Python 3.14, `powersave` governor,
min-of-N interleaved, pinned cores). They are measurements, not citations.

### One process per bot per *match*, never per tick

| Operation | Cost |
|---|---|
| Bot round-trip, squadron of 2, JSONL over pipes | **44 µs** |
| Bare `Popen` + interpreter start + first reply | 22–31 ms |
| Same, but the bot does `import numpy` at module level | 116–120 ms |
| `docker run` per bot, warm daemon, image already local | ~500 ms |

Spawning per tick costs **500×** a round-trip before the bot has thought at all, and it throws away the bot's memory
between ticks — which destroys any bot that tracks a target or remembers where it last saw an enemy. Per-tick
containers are off the table by three orders of magnitude.

### Protocol: newline-delimited JSON, and the margin is not close

Full tick cost — serialise, write, bot decodes and thinks and encodes, read, deserialise:

| Payload | Protocol | Bytes | Mean | Round-trips/s |
|---|---|---|---|---|
| FFA (squadron 1, 4 contacts) | JSONL | 1,174 | 32.7 µs | 30,581 |
| **Duo (squadron 2, 6 contacts)** | **JSONL** | **1,802** | **44.2 µs** | **22,624** |
| Duo (squadron 2, 6 contacts) | msgpack | 1,433 | 27.4 µs | 36,496 |
| Wing (squadron 4, 10 contacts) | JSONL | 3,316 | 69.4 µs | 14,409 |

At the target shape — two bots, squadrons of two — IPC costs **88 µs per tick, 0.53% of a 60 Hz frame**, and a
3000-tick match spends **0.27 s total** in the protocol.

What was measured *not* to matter: text versus binary mode (51.2 vs 51.4 µs, irrelevant), length-prefix framing
(52.0 µs — buys nothing over newlines, so protobuf and CBOR are pure schema burden for zero gain), and unix sockets,
which came out **slower** than pipes (58.8 µs) and add a rendezvous dance. The cost is JSON encoding, not the pipe.

**Keep JSON.** msgpack is a genuine 1.8× but worth ~20 µs per tick, which is irrelevant here, and it costs a
dependency, opacity, and `strict_map_key` / bytes-versus-str papercuts. If headless ladder throughput ever matters
it is a two-line change, because framing is already behind a function.

**HTTP (Battlesnake's model) is rejected**, though its real virtue is worth recording: the engine never executes
player code at all, because players self-host. That is the cheapest possible answer to a hostile threat model and
the worst possible ergonomics for "several friends each write one `.py`".

**Shared memory is actively harmful** — it would remove ~20 µs of serialisation nobody cares about while
reintroducing exactly what the process boundary bought: a bot that can scribble on engine state.

### Deadline mechanics: three traps

1. **`RLIMIT_CPU` cannot express a per-tick deadline** — its soft limit is denominated in whole seconds. Use a
   wall-clock read deadline on the pipe via `selectors`. `RLIMIT_CPU` is still worth setting as a *per-match*
   backstop, with **both** limits: the soft limit raises a catchable `SIGXCPU` (verified — a bot that does
   `signal.signal(SIGXCPU, SIG_IGN)` survives it, `rc=-24` becomes `rc=-9` only once the hard limit fires), so a
   soft limit alone is merely advisory.
1. **`communicate(timeout=…)` does not kill the child.** The docs are explicit about it. You must kill it yourself.
1. **Kill the process *group*, not the pid.** Spawn with `start_new_session=True` and use
   `os.killpg(pid, SIGKILL)`, so a bot that spawned helpers leaves no orphans. Verified: a `while True: pass` bot is
   reaped in 0.50 s.

`preexec_fn` is the usual way to apply rlimits and is fine for a single-threaded engine, but it is documented as
**not safe in the presence of threads** — the child can deadlock before `exec`. If the engine ever goes threaded,
wrap the command in a tiny launcher instead.

### Verified behaviour against seven misbehaving bots

50 ms deadline, forfeit after 3 strikes:

| Bot | Outcome |
|---|---|
| Well-behaved | Survived, 0 strikes |
| **Prints debug text** | **Survived, 0 strikes** — print landed on stderr |
| **Prints protocol-shaped JSON every tick** | **Survived, 0 strikes** — fake line landed on stderr |
| Raises an exception | Forfeited after 3; real traceback on stderr |
| `while True: pass` | Forfeited after 3, detected in 150 ms |
| Returns a string instead of a dict | Forfeited after 3 |
| Illegal values | Forfeited after 3, named the offending field |

**That table is the engine's test suite.** Add a `chaos` bot returning randomly-malformed replies under a seeded
PRNG for fuzzing.

## 12. Determinism: floats are not the problem, trig is

IEEE-754 requires `+ - * /` and `sqrt` to be correctly rounded, so those are bit-identical everywhere.
**`math.sin`, `cos`, `atan2`, `exp` and `pow` route to the platform libm and are not.** Turning aircraft means
reaching for trig, so **a replay produced on one machine can diverge on another** — which matters here, because
friends will send each other replay files.

**Chosen fix: a precomputed trig table owned by the engine**, on the order of 4096 headings. That turns `sin` and
`cos` into an array index, bit-identical on every platform, and heading is naturally quantised in a dogfight anyway.
The alternative — fixed-point integers at 1/65536 units, with torus wrap as an exact integer modulo — is also
verified exact and is the fallback if the table proves awkward.

**A bot's own maths is unconstrained** — its output is a discrete action, so whatever floats it computes internally
cannot desync the simulation.

**But the derived fields handed *to* the bot are engine maths, and that is where the hole is.** `bearing_deg` and
`range` are computed by the engine with libm `atan2` and `sqrt`. Two machines one ULP apart, and a bot branching on
`bearing_deg > 5.0` takes a different path — divergent match, from a replay that looked deterministic.

**Fix: quantise every bot-visible derived float** — angles to 0.01 degrees, ranges to 0.1 units — or derive them
from the same trig table. Quantising is one `round()` at the serialisation boundary, it makes the JSON smaller, and
no bot has any legitimate use for the 12th decimal place of a bearing. Without it, the honest claim shrinks to
"replays are playback-only" rather than "same inputs reproduce the same match anywhere".

Three more verified determinism hazards:

- **Never iterate a set of strings in engine logic.** `list({'alpha', 'bravo', 'charlie', 'delta', 'echo'})` returns
  a different order per `PYTHONHASHSEED` — three seeds gave three orders. Sets of ints are stable (int hash is
  identity) and `dict` is insertion-ordered regardless. Setting `PYTHONHASHSEED=0` locally masks the bug and hides
  it until somebody else replays the match.
- **Give each bot its own `Random(match_seed, bot_index)` stream**, so one bot drawing a different number of samples
  cannot shift another's — the classic lockstep desync. Record the Python version in the replay header; the
  cross-version stability of `random`'s stream was not verified.
- **The substituted action on a timeout must itself be deterministic and recorded.** Hold-last satisfies both. If
  the fallback were derived from wall-clock timing the replay would diverge from the live match.

### Two replay artifacts, one derived from the other

A renderer can only show what is in the stream, and that tension is resolved in the format rather than in each
viewer.

| | Contents | Size | Purpose |
|---|---|---|---|
| **Thin** | Header (seed, class-table hash, engine/API/Python versions, arena, squadrons) plus the validated, post-substitution action stream, with a state hash every ~100 ticks as a desync tripwire | Tiny | **Canonical truth.** Bit-exact reproduction, CI, the ladder. Replays without bots or a sandbox |
| **Fat** | Full per-tick state — positions, headings, speeds, HP, ammo, bullets in flight — **plus the derived fields**: each plane's cone geometry, what each squadron could actually see, and a badge on any degraded tick | ~0.25 MB gzipped per 1800 ticks of a 2v2 (measured: 2.19 MB raw, 8.67x) | **Anything that displays.** Requires no game logic at all |

The engine regenerates the fat stream from the thin one on demand, so there is one source of truth and no
duplication.

**The point of the fat stream is that a presentation layer needs zero engine.** A second web viewer, an mp4
exporter, a Textual scoreboard or somebody else's tool reads plain JSONL and draws it. That property survives only
if the derived fields are *recorded* rather than recomputed — a viewer that must work out cone geometry and
visibility itself is a viewer that must embed the physics, which in a browser means porting the simulation to
JavaScript. Recording about a kilobyte more per tick buys the whole architecture.

## 13. Isolation: not needed now, and free when it is

Recorded because the threat model could change, not because it is in scope.

**In-process `import` of a bot is not securable, and this is settled by the people who tried hardest.** CPython's own
security policy states that "CPython does not support sandboxing untrusted Python code as a security boundary".
Victor Stinner wrote `pysandbox` and then withdrew it: "I now think that putting a sandbox directly in Python cannot
be secure. To build a secure sandbox, the whole Python process must be put in an external sandbox." `rexec` and
`Bastion` were removed in Python 2.3 for "known and not readily fixable security holes". `RestrictedPython` says in
its own README that it "is not a sandbox system or a secured environment", and its CVE history is one escape per new
language feature. `sys.settrace` is not a guard — untrusted code simply calls `sys.settrace(None)`. Audit hooks are
observability: PEP 578 says "this is not sandboxing".

**But the process boundary already buys the two things that matter here, for free.** A bot that only ever receives a
serialised snapshot and returns a value cannot mutate engine state to cheat and cannot read the opponent's source —
a consequence of serialisation, not of security engineering. And a subprocess is **the only mechanism that makes
"you have 50 ms" enforceable at all**: a `while True: pass` in the same interpreter cannot be interrupted, because
signals only run between bytecodes on the main thread and a thread cannot be killed. **Robustness, not security, is
what forces the process boundary.**

**When a stranger's bot ever needs to run: `bubblewrap`, measured at +0.6 µs per round-trip** — inside the noise
floor. Verified under it: network unreachable, `/home` absent, `/usr` read-only. Note the boundary is the filesystem
and network view, not the language; the bot can still `import subprocess`.

One trap worth knowing in advance: **`RLIMIT_NPROC` is enforced per real UID, not per process tree**, so if all bots
run as the same user, one bot hitting the cap starves the other bots *and the engine*. The correct forkbomb guard is
cgroups v2 `pids.max`, or a distinct UID per bot.

**WASM: no.** CPython's WASI target is respectable now — Tier 2 in PEP 11 as of 3.13 — and its genuinely attractive
property is *fuel metering*, a deterministic instruction budget that would be fairer across machines than any
wall-clock deadline. But Wasmer's own py2wasm figures put CPython-in-WASM at ~23% of native and py2wasm at ~61%, so
every author would take a 1.6–4× slowdown inside `act()`; `componentize-py` cannot resolve runtime imports, so a
one-file bot would need a build step; and py2wasm pins Python 3.11. It replaces a 30-line subprocess driver that
measurably works with a build pipeline and a slower interpreter, to buy security that is not needed and metering
that is not yet wanted. Revisit only on going public *and* wanting deterministic instruction budgets as a fairness
feature.

## 14. Corrections from the build

Figures replaced by measurements taken while implementing, rather than from the research agent's synthetic payloads.

- **Replay compression: 8.67x, not 3.07x.** A real 2v2 round produced 2.19 MB raw and 0.25 MB gzipped, about 170
  bytes per tick compressed. The originally cited 8.92 MB to 2.94 MB came from a synthetic payload sized for a much
  larger match, and understated the ratio by nearly three times.
- **The default arena is 2000 x 2000.** The design doc's earlier 1800 x 1400 recommendation violated its own
  cone-range constraint, and `load_classes(arena=...)` rejected it.
- **`geom`'s trig table is rounded to 12 decimal places.** The table exists to avoid libm's cross-machine variance
  but is *built* by calling `math.sin`, so its own entries would have differed by ~1 ULP between platforms and that
  difference would have reached simulated positions. Rounding through a decimal string collapses any such
  disagreement to an identical double everywhere.
- **The visibility decision is quantised too, not just the reported values.** `in_cone` originally compared
  unrounded `distance` and `bearing_to`, so a target exactly on a cone boundary could be visible on one machine and
  not another — enough to diverge a replay.
- **The gun model is per-gun, and the engine holds no gun constants.** `MUZZLE_SPEED` and
  `BULLET_LIFETIME` began as engine-wide constants invented during planning; both are now fields on
  each gun, alongside dispersion, cooldown, damage, ammo and mount bearing. Nothing about a gun
  lives outside the balance table.
- **Inherited bullet velocity is a vector sum, and was a scalar.** `spawn` originally computed
  `muzzle + plane_speed` and pointed the total along the firing direction, which is correct only for
  a forward mount. A bomber flying east at 8 firing astern produced a round at speed 38 instead of
  22 — 1.73x too fast, and *faster* as the bomber accelerated when it must get slower. The bug was
  invisible to the test suite because inheritance was only ever tested on a forward gun, where the
  scalar and vector forms agree. A per-mount asymmetry needs a test per mount.
- **Bullet dispersion draws from the engine's RNG, never a squadron's.** Otherwise a bot could burn
  draws to predict its own scatter, and its draws would perturb engine physics. Dispersion is the
  engine's first per-tick RNG consumer, which is what makes seeded reproducibility load-bearing
  rather than theoretical.
- **Each squadron's bot RNG is one long-lived stream, not a fresh `Random` per tick.** The original
  rebuilt it every tick from the same seed, so `state.rng.random()` returned an identical value
  every tick — a constant wearing a stream's clothes.
- **Events cross the wire as their named types; they used to arrive as bare tuples.** The encoder
  always sent `[type_name, fields]`, and the decoder threw the name away "to keep the format
  simple" — saving one line there and charging it back out as a documented trap, a shape-matching
  `match` block in every bot, and arity as the public contract. Worse, it was a divergence between
  the two paths: `World.views()` hands an in-process bot real types, so a bot's harness tests
  passed on `isinstance` while the same code misread a live match. Rebuilding the class costs a
  five-entry dict and one lookup, with an unknown name degrading to a tuple. No wire-format change
  was needed, which is the tell that the saving was never real.
- **A claim withdrawn rather than corrected.** The design doc asserted that finite ammo was "the
  second clock" and made "aimed fire strictly better than spray". That was inferred from research,
  not designed: ammo is finite and each gun has a magazine, and a magazine that does not run dry
  mid-round is simply a magazine. The claim was removed rather than the numbers changed to justify
  it.
