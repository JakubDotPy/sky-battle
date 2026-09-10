"""The command line. `play` runs a host's declared game file; `duel` is the two-bot shortcut;
`serve` hands a finished match to a browser.

`serve` is a stdlib `http.server` only: no framework, no build step. Replays are already gzipped
on disk, so the replay route forwards those bytes unchanged with `Content-Encoding: gzip` -- the
browser's own `fetch` gunzips them, and nothing here ever holds a whole replay decompressed.
"""

import argparse
import functools
import http.server
import json
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import replay
from .classes import DEFAULT_TABLE, load_classes
from .game import Game, check_squadron, load_game, read_squadron
from .match import MatchResult, run_match

DEFAULT_SQUADRON = ["scout", "fighter"]

VIEWER_DIR = Path(__file__).parent / "viewer"


def _rounds_index(replay_dir: Path) -> list[dict]:
    """List `*.fat.jsonl.gz` rounds, newest first, with header facts plus a frame count.

    Reading each file in full to count frames costs real time at scale -- a round is ~41 KB /
    831 frames, so this is cheap here -- but it is a whole-file read per round, not a header peek.
    """
    rounds = []
    paths = sorted(replay_dir.glob("*.fat.jsonl.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        header, ticks = replay.read(path)
        rounds.append({
            "name": path.name,
            "seed": header["seed"],
            "bots": header["bots"],
            "frames": len(ticks),
        })
    return rounds


class _ViewerHandler(http.server.BaseHTTPRequestHandler):
    """Four routes: the viewer page, its script, the round index, and replay bytes."""

    def __init__(self, *args: object, replay_dir: Path, **kwargs: object) -> None:
        self.replay_dir = replay_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._serve_file(VIEWER_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/viewer.js":
            self._serve_file(VIEWER_DIR / "viewer.js", "text/javascript; charset=utf-8")
        elif path == "/rounds.json":
            body = json.dumps(_rounds_index(self.replay_dir)).encode()
            self._respond(200, body, "application/json")
        elif path.startswith("/replay/"):
            self._serve_replay(path.removeprefix("/replay/"))
        else:
            self._respond(404, b"not found", "text/plain")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._respond(404, b"not found", "text/plain")
            return
        self._respond(200, path.read_bytes(), content_type)

    def _serve_replay(self, name: str) -> None:
        # Resolve and check containment -- a textual ".." reject is not enough (encoded dots,
        # an absolute-looking name that pathlib would otherwise splice in as-is).
        target = (self.replay_dir / name).resolve()
        try:
            target.relative_to(self.replay_dir.resolve())
        except ValueError:
            self._respond(403, b"forbidden", "text/plain")
            return
        if not target.is_file():
            self._respond(404, b"not found", "text/plain")
            return

        # The one trick that matters: these bytes are already gzip on disk. Ship them as-is and
        # say so, so the browser's own fetch gunzips them -- never decompress here.
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # quiet by default; nothing here is worth a request log line


def make_server(replay_dir: Path, port: int = 8765) -> http.server.ThreadingHTTPServer:
    """Bind a viewer server to `replay_dir`. `port=0` lets the OS pick a free one.

    Loopback only -- this serves local files from whatever directory the caller names, and has
    no business being reachable from the network.
    """
    handler = functools.partial(_ViewerHandler, replay_dir=Path(replay_dir))
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


def _print_result_lines(result: MatchResult, labels: dict[int, str]) -> None:
    """One line per squadron: name, points, accepted N/total, strikes, forfeits.

    Shared by `duel` and `play` so the two commands report in one format; each caller prints
    its own winner line afterward, since `play` names the host's player, not a squadron index.
    """
    for sq in sorted(result.totals):
        acc = sum(r.accepted[sq] for r in result.rounds)
        ticks = sum(r.ticks for r in result.rounds)
        strikes = sum(r.strikes[sq] for r in result.rounds)
        forfeits = sum(1 for r in result.rounds if r.forfeited[sq])
        print(f"squadron {sq} ({labels[sq]}): {result.totals[sq]:8.1f} points  "
              f"accepted {acc}/{ticks}  strikes {strikes}  forfeits {forfeits}")


def _squadron_for(bot_path: Path, classes: dict) -> list[str]:
    """duel's composition: the bot's own SQUADRON if it declares one, else the historic default.

    Unlike `play`, duel has no `planes_per_player` to enforce -- two bots may field different
    squadron sizes; the engine already handles squadrons of any length.
    """
    squadron = read_squadron(bot_path)
    if squadron is None:
        return list(DEFAULT_SQUADRON)
    check_squadron(bot_path, squadron, classes, planes_per_player=len(squadron))
    return squadron


def _play(game_file: Path, replay_dir: Path | None) -> int:
    try:
        game: Game = load_game(game_file)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    squadrons = [p.squadron for p in game.players]
    classes = load_classes(arena=game.arena)
    result = run_match([p.bot for p in game.players], squadrons, seed=game.seed,
                       rounds=game.rounds, arena=game.arena, classes=classes,
                       deadline=game.deadline, replay_dir=replay_dir,
                       round_tick_limit=game.ticks_per_round)

    # Just the player's name -- `_print_result_lines` already wraps it in one pair of
    # parens, so adding the bot filename here too would nest it redundantly, e.g.
    # "squadron 0 (jakub (jakub.py))"; the host already has the name-to-bot mapping in
    # their own game file.
    labels = {i: p.name for i, p in enumerate(game.players)}
    _print_result_lines(result, labels)
    winner = "draw" if result.winner is None else game.players[result.winner].name
    print(f"winner: {winner}")
    return 0


def _serve(replay_dir: Path, port: int, open_browser: bool) -> int:
    if not replay_dir.is_dir():
        print(f"error: not a directory: {replay_dir}")
        return 1

    server = make_server(replay_dir, port=port)
    host, bound_port = server.server_address[:2]
    url = f"http://{host}:{bound_port}/"
    print(f"serving {replay_dir} at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sky-battle")
    subs = parser.add_subparsers(dest="command", required=True)

    duel = subs.add_parser("duel", help="run a match between two bots")
    duel.add_argument("bot_a", type=Path, nargs="?")
    duel.add_argument("bot_b", type=Path, nargs="?")
    duel.add_argument("--seed", type=int, default=1)
    duel.add_argument("--rounds", type=int, default=11)
    duel.add_argument("--arena", type=float, nargs=2, default=[2000.0, 2000.0])
    duel.add_argument("--deadline", type=float, default=0.05)
    duel.add_argument("--replay-dir", type=Path, default=None)
    duel.add_argument("--rules", action="store_true", help="print the class table and exit")

    play = subs.add_parser("play", help="run a match from a host's game file")
    play.add_argument("game_file", type=Path)
    play.add_argument("--replay-dir", type=Path, default=None)

    serve = subs.add_parser("serve", help="serve a replay directory to a browser")
    serve.add_argument("replay_dir", type=Path)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true", help="do not launch a browser")

    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve(args.replay_dir, port=args.port, open_browser=not args.no_open)

    if args.command == "play":
        return _play(args.game_file, replay_dir=args.replay_dir)

    if args.rules:
        # The numbers ARE the game; nobody should have to read source for them.
        print(DEFAULT_TABLE.read_text())
        return 0

    if args.bot_a is None or args.bot_b is None:
        duel.error("two bot paths are required unless --rules is given")

    arena = (args.arena[0], args.arena[1])
    classes = load_classes(arena=arena)     # validates cone ranges against this arena
    try:
        squadrons = [_squadron_for(args.bot_a, classes), _squadron_for(args.bot_b, classes)]
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    result = run_match([args.bot_a, args.bot_b], squadrons, seed=args.seed,
                       rounds=args.rounds, arena=arena, classes=classes,
                       deadline=args.deadline, replay_dir=args.replay_dir)

    labels = {0: args.bot_a.name, 1: args.bot_b.name}
    _print_result_lines(result, labels)
    print(f"winner: {'draw' if result.winner is None else f'squadron {result.winner}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
