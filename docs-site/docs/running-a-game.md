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

By default both bots fly a scout and a fighter — but that is only a fallback, not a limit. A bot
that declares its own `SQUADRON` (see [Squadron composition](writing-a-bot.md#squadron-composition))
flies exactly that instead, bomber included, with no extra flag needed:

```console
$ sky-battle duel bots/alice.py bots/bob.py --seed 7 --rounds 11
squadron 0 (alice.py):   2170.4 points  accepted 6749/6749  strikes 0  forfeits 0
squadron 1 (bob.py):   3722.4 points  accepted 6749/6749  strikes 0  forfeits 0
winner: squadron 1
```

Here `alice.py` has no `SQUADRON` at all, so she gets the default scout and fighter; `bob.py`
declares `SQUADRON = ["bomber", "bomber"]` and flies two bombers instead. Nothing on the command
line says so — the composition lives entirely in the bot files.

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

## Running a game file

A host sets the rules; a player sets their loadout. Rounds, ticks, how many players and how many
planes each belongs to the host's file; which *kinds* those planes are belongs to each player's
own bot, via the `SQUADRON` declaration — see [Squadron
composition](writing-a-bot.md#squadron-composition). Neither side reads the other's.

```toml
[game]
rounds            = 11          # default 11
ticks_per_round   = 3000        # default 3000
planes_per_player = 2           # default 2
arena             = [2000, 2000]
seed              = 7
deadline          = 0.05

[[players]]
name = "jakub"
bot  = "bots/jakub.py"

[[players]]
name = "anna"
bot  = "bots/anna.py"

[[players]]
name = "petr"
bot  = "bots/petr.py"
```

Every `[game]` field has a default; only the players are required — a file needs at least one
`[[players]]` block. `bot` paths resolve relative to the game file's own directory, not the
process's working directory, so a game file and its bots move together if you relocate them. See
[Reference](reference.md#game-files) for the exhaustive field list.

`ticks_per_round` is one thing a game file can do that `duel` still cannot: `duel` has no flag
for it at all, so a `duel` round is always capped at 3000 ticks; only a game file can shorten or
lengthen one.

Run it with `play`:

```console
$ sky-battle play game.toml
squadron 0 (jakub):   1964.0 points  accepted 8268/8268  strikes 0  forfeits 0
squadron 1 (anna):   1294.8 points  accepted 8268/8268  strikes 0  forfeits 0
squadron 2 (petr):   3938.0 points  accepted 8268/8268  strikes 0  forfeits 0
winner: petr
```

That is the same result-line format `duel` prints (see [Reading the result
line](#reading-the-result-line)) — just one line per player instead of exactly two, and each one
labelled by the player's name from the game file rather than a squadron index or bot filename.
`play` also accepts `--replay-dir`, written the same way as `duel`'s.

The whole file is validated before a single tick runs, and every failure names the offending
file: the TOML has to parse; the arena has to be large enough for every class's cone and bubble
range (the same check `duel --arena` gets); every player needs a name and a readable bot path;
every bot has to declare `SQUADRON`; every declared kind has to exist in the class table; and
every declared squadron's length has to equal `planes_per_player`. Unlike `duel`, there is no
fallback squadron here — a bot that omits `SQUADRON` is a hard rejection, not a default.

This is also a genuine free-for-all, not a round-robin in disguise: all three players above flew
in the *same* arena at the *same* time, against both opponents at once — jakub's, anna's and
petr's squadrons each saw the other two as ordinary contacts. It is one match with three
squadrons, not three matches with two.

## Running a small tournament

There is still no dedicated tournament subcommand — a full double round-robin ranking is still a
shell loop over `duel`, once per ordered pair of bots. What a game file changes is that "more
than two bots in the same picture" no longer *requires* a round robin: [a game
file](#running-a-game-file) puts any number of players into one shared match, all at once, with
a single standings line. Reach for a game file when what you want is one melee among a fixed
group; reach for the loop below when what you want is a fair pairwise *ranking* across many
bots.

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
