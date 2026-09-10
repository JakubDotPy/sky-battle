"""Loading and validating a host's game file.

A host declares a match -- rounds, ticks, arena, players -- in a TOML file; each player
declares their own squadron composition in their own bot file, as a module-level `SQUADRON`
list. The engine never imports player code to read it: bots run as subprocesses behind the
runner shim, and that isolation is what makes a per-tick deadline enforceable at all. So
`SQUADRON` is read statically with `ast` -- which also means a host can inspect every
submission's choice without running anything.
"""

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .classes import PlaneClass, load_classes
from .state import API_VERSION

DEFAULT_ARENA = (2000.0, 2000.0)


@dataclass(frozen=True)
class Player:
    name: str
    bot: Path
    squadron: list[str]


@dataclass(frozen=True)
class Game:
    rounds: int
    ticks_per_round: int
    planes_per_player: int
    arena: tuple[float, float]
    seed: int
    deadline: float
    players: list[Player]


def read_squadron(bot_path: Path) -> list[str] | None:
    """Read a bot's `SQUADRON = [...]` declaration without importing it.

    Returns None if the file declares no module-level `SQUADRON` at all -- absence is a
    legitimate outcome for a caller that wants to fall back to a default (`duel`); a
    declaration that IS present but malformed is always an error, never silently ignored.
    """
    try:
        source = bot_path.read_text()
    except OSError as exc:
        raise ValueError(f"{bot_path}: cannot read bot file: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(bot_path))
    except SyntaxError as exc:
        raise ValueError(f"{bot_path}: cannot parse: {exc}") from exc

    for node in tree.body:  # module level only -- a nested SQUADRON must not count
        if not (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SQUADRON" for t in node.targets)):
            continue
        value = node.value
        if (isinstance(value, ast.List)
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in value.elts)):
            return [e.value for e in value.elts]
        raise ValueError(f"{bot_path}: SQUADRON must be a list of string literals, "
                         f"e.g. SQUADRON = [\"scout\", \"fighter\"]")
    return None


def read_api_version(bot_path: Path) -> int | None:
    """Read a bot's `API_VERSION = N` declaration without importing it.

    Returns None when the file declares none, which is treated as "the current version" rather
    than as an error: requiring the constant would break every bot written before it was
    checked, and Battlesnake's precedent is that a bot declares its version and old ones keep
    working until a published cut-off.
    """
    try:
        tree = ast.parse(bot_path.read_text(), filename=str(bot_path))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"{bot_path}: cannot read bot file - {exc}") from exc

    for node in tree.body:  # module level only, same discipline as read_squadron
        if not (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "API_VERSION" for t in node.targets)):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int) \
                and not isinstance(value.value, bool):
            return value.value
        raise ValueError(f"{bot_path}: API_VERSION must be an integer literal, "
                         f"e.g. API_VERSION = {API_VERSION}")
    return None


def check_api_version(bot_path: Path) -> None:
    """Refuse a bot written against an API version this engine does not speak.

    `bot-api.md` specifies this check; until now the constant existed and was stamped into
    replay headers but was never compared against anything a bot declared.
    """
    declared = read_api_version(bot_path)
    if declared is not None and declared != API_VERSION:
        raise ValueError(
            f"{bot_path}: declares API_VERSION = {declared}, but this engine speaks "
            f"version {API_VERSION}. Within a major version the state and action types are "
            f"additive only, so a bot written for a different major needs updating."
        )


def load_game(path: str | Path) -> Game:
    """Parse and validate a game file. Every failure names the offending file."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except OSError as exc:
        raise ValueError(f"{path}: cannot read game file: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: not valid TOML: {exc}") from exc

    game = raw.get("game", {})
    rounds = game.get("rounds", 11)
    ticks_per_round = game.get("ticks_per_round", 3000)
    planes_per_player = game.get("planes_per_player", 2)
    arena_raw = game.get("arena", list(DEFAULT_ARENA))
    if len(arena_raw) != 2:
        raise ValueError(f"{path}: [game] arena must be [width, height], got {arena_raw!r}")
    arena = (float(arena_raw[0]), float(arena_raw[1]))
    seed = game.get("seed", 1)
    deadline = game.get("deadline", 0.05)

    player_specs = raw.get("players", [])
    if not player_specs:
        raise ValueError(f"{path}: needs at least one [[players]] block")

    # Validates cone/bubble ranges against this arena, so an arena too small for the widest
    # cone is refused up front -- same check `duel` already gets via load_classes(arena=...).
    classes = load_classes(arena=arena)

    players = []
    for i, spec in enumerate(player_specs):
        name = spec.get("name")
        if not name:
            raise ValueError(f"{path}: [[players]] block {i} needs a name")
        bot_field = spec.get("bot")
        if not bot_field:
            raise ValueError(f"{path}: player {name!r} needs a bot path")
        # Relative to the GAME FILE's directory, not the process cwd, so a game file and its
        # bots move together.
        bot_path = (path.parent / bot_field).resolve()
        if not bot_path.is_file():
            raise ValueError(f"{path}: player {name!r} bot not found: {bot_path}")

        squadron = read_squadron(bot_path)
        if squadron is None:
            raise ValueError(f"{bot_path}: no module-level SQUADRON declaration found, e.g. "
                             f"SQUADRON = [\"scout\", \"fighter\"]")
        check_api_version(bot_path)
        check_squadron(bot_path, squadron, classes, planes_per_player)
        players.append(Player(name=name, bot=bot_path, squadron=squadron))

    return Game(rounds=rounds, ticks_per_round=ticks_per_round,
               planes_per_player=planes_per_player, arena=arena, seed=seed,
               deadline=deadline, players=players)


def check_squadron(bot_path: Path, squadron: list[str], classes: dict[str, PlaneClass],
                   planes_per_player: int) -> None:
    """Shared by `load_game` (hard requirement) and `duel` (only when SQUADRON is present)."""
    for kind in squadron:
        if kind not in classes:
            raise ValueError(f"{bot_path}: unknown plane kind {kind!r} in SQUADRON; "
                             f"valid kinds are {sorted(classes)}")
    if len(squadron) != planes_per_player:
        raise ValueError(f"{bot_path}: SQUADRON has {len(squadron)} planes, expected "
                         f"planes_per_player={planes_per_player}")
