# Running a game

This page is for the person hosting a match or a small tournament, not for the person writing a
bot — see [Writing a bot](writing-a-bot.md) for that side.

## Install

Sky Battle has **no runtime dependencies** — the engine, the bot protocol, the replay format and
the viewer are all standard library. Clone the repository and install it with `uv`:

```console
uv sync
uv run sky-battle --help
```

`sky-battle` is also registered as a console script, so `uv run sky-battle ...` works from
anywhere inside the project, or `uv tool install .` makes the `sky-battle` command available
outside a `uv run` prefix.

## Running one match

```console
sky-battle duel bots/alice.py bots/bob.py --seed 7 --rounds 11
```

- `bot_a` and `bot_b` are paths to two bot files.
- `--seed` (default `1`) seeds the match; each round within the match uses `seed`, `seed + 1`,
  `seed + 2`, ... in order, so the same seed always produces the same sequence of rounds.
- `--rounds` (default `11`) is the number of rounds in the match, each with a fresh spawn and
  its own seed, scores summed into a match total.
- `--arena W H` (default `2000 2000`) sets the arena size. Every class's cone and bubble ranges
  are checked against whatever arena you pick — see [The game](index.md#the-arena) — so an
  arena that is too small for the current balance table is rejected at startup rather than
  silently producing a broken fog of war.
- `--deadline` (default `0.05` seconds) is the per-tick budget given to each bot; the first tick
  of a round always gets a larger allowance, since that is where a bot's own module-level
  imports land.
- `--replay-dir DIR` writes one pair of replay files per round into `DIR` — see
  [Watching a match](#watching-a-match-the-browser-viewer) below.
- `--rules` prints the raw balance table (`classes.toml`) and exits, without running a match.
  The numbers *are* the game, so nobody hosting or playing should have to go spelunking through
  source to find them:

  ```console
  $ sky-battle duel --rules
  # Sky Battle balance table.
  # Speeds are units/tick, angles degrees, times ticks. Edit freely: this file is the game.
  ...
  ```

Both bots always fly a scout and a fighter (that is the CLI's fixed default squadron); a bomber
is engine-complete and fully playable, but reaching one currently means calling
`skybattle.match.run_match` with an explicit `squadrons` argument from a short Python script
rather than through the `duel` subcommand, which has no flag for it yet.

## Reading the result line

```text
squadron 0 (alice.py):    724.4 points  accepted 2580/2580  strikes 0  forfeits 0
squadron 1 (bob.py):      436.0 points  accepted 2580/2580  strikes 0  forfeits 0
winner: squadron 0
```

The important number is **`accepted N/total`**, not a timeout count. That distinction matters
because a bot that is only *occasionally* slow degrades gracefully, one skipped tick at a time —
but a bot that is *consistently* a little over its deadline never lands a single action: every
reply arrives after the tick it was for has already moved on, so it is discarded as stale, and
the bot ends up holding its very first action for the entire match while its miss count climbs.
`timeouts: 900/3000` would invite you to assume the other 2100 ticks used the bot's actual
choices — false in that scenario. `accepted: 1140/3000` is the honest number, and the one that
actually explains a bot's final score. `strikes` counts every miss (timeout, crash, or malformed
reply); `forfeits` counts rounds where a squadron hit the strike limit and was disabled for the
rest of that round — its planes keep existing and keep coasting rather than vanishing, so the
round's physics stay fair to the other player.

## Watching a match: the browser viewer

```console
$ sky-battle duel bots/alice.py bots/bob.py --replay-dir replays/
$ sky-battle serve replays/
serving replays at http://127.0.0.1:8765/
```

`serve` starts a local-only web server (loopback interface only — it is never reachable from the
network) over the replay directory and opens it in a browser. It has no build step and no
framework: canvas 2D and vanilla JavaScript, reading the newline-delimited JSON replay files
directly. In the viewer:

- The **timeline scrubber and step/play controls** move through the round tick by tick, at 1x,
  2x or 4x real time (space to play/pause, arrow keys to step).
- **Click a plane** to select it. A selected plane gets its own facts panel (id, squadron, kind,
  hit points, speed, per-gun ammo) and, if it is alive, its vision cones and bubble are drawn —
  this is the single most useful debugging view the game has, since fog of war is the core
  mechanic and "what could this plane actually see at tick 431" is otherwise invisible.
- Enemy planes the selected squadron **cannot currently see** are dimmed, using the same
  visibility the engine itself recorded for that tick — the viewer never recomputes fog of war,
  it only draws what the replay already says.
- If more than one round's replay is in the directory, a dropdown in the header switches between
  them.

The replay directory holds two files per round: a small `.thin.jsonl.gz` (the canonical,
bit-exact action stream — what a re-simulation would need) and a larger `.fat.jsonl.gz` (full
per-tick state plus every derived fact a viewer needs, so nothing that displays a match has to
re-implement the physics). Both are already gzip-compressed on disk; the server forwards the
bytes unchanged and lets the browser's own `fetch` decompress them.

## Running a small tournament

There is no built-in tournament subcommand today — running one is a shell loop over `duel`, once
per ordered pair of bots:

```console
#!/usr/bin/env bash
set -euo pipefail
bots=(bots/*.py)
for a in "${bots[@]}"; do
  for b in "${bots[@]}"; do
    [ "$a" = "$b" ] && continue
    sky-battle duel "$a" "$b" --seed 1 --rounds 11 --replay-dir "replays/$(basename "$a")-vs-$(basename "$b")"
  done
done
```

That is a **double round-robin**: every ordered pair plays once, so ties in who-played-white are
resolved by giving everyone both sides. For up to about a dozen bots this is the whole ranking
method — sum each bot's total score across all its matches and sort. There is no rating system
(Elo, TrueSkill or otherwise) built in; for a small, fixed group of friends, exhaustive
round-robin needs no explaining and produces a standing nobody has to trust a formula for.

## The honest limits

Sky Battle is built to survive **broken** bots, not malicious ones. A crash, an infinite loop, a
garbage reply, actions for a plane that no longer exists — all of that is handled, logged, and
the match continues; see [When a bot misbehaves](writing-a-bot.md#when-a-bot-misbehaves) for the
full list. What it does **not** do is sandbox untrusted code: a bot runs as an ordinary
subprocess with ordinary OS permissions, so it can read the filesystem, open a socket, or spawn
its own children if the author wants it to. There is a per-tick wall-clock deadline that
enforces fairness about *time*, and nothing at all that enforces anything about *behaviour*.

Run this among people you already trust — colleagues, friends, a class. If you ever need to run
someone else's bot without trusting them, that is a different, unbuilt feature: it would need at
minimum a filesystem and network sandbox (`bubblewrap` and a distinct UID per bot are the
obvious starting points), and nothing here provides one today.
