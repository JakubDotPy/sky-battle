"""Two replay artifacts, one derived from the other.

THIN is canonical truth: seed plus the validated, post-substitution action stream. It replays
bit-exactly and needs no bots.

FAT is what anything that DISPLAYS reads: full per-tick state plus the DERIVED fields -- cone
geometry and per-squadron visibility. Recording those is the whole point: a viewer that has to
work out visibility itself is a viewer that has to embed the physics, which in a browser means
porting the simulation to JavaScript. About a kilobyte more per tick buys the architecture.

The engine regenerates fat from thin on demand, so there is one source of truth.
"""

import gzip
import hashlib
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import protocol, vision
from .classes import table_hash
from .state import API_VERSION, Action

try:
    ENGINE_VERSION = version("skybattle")
except PackageNotFoundError:      # a source checkout on PYTHONPATH, never installed
    ENGINE_VERSION = "unknown"
"""Read from package metadata rather than retyped here, so `uv version --bump` stays the single
source and a replay header can never claim a version the package does not have. The fallback is
deliberately not a version number: an uninstalled checkout cannot know one, and saying so beats
stamping a stale guess into a header whose whole job is saying what produced the replay."""


def make_header(seed: int, arena: tuple[float, float], squadrons: list[list[str]],
                table_path: Path | None = None,
                bot_paths: list[str | Path] | None = None) -> dict:
    """Everything needed to know whether two results are comparable.

    The reproducibility triple is (seed, class-table hash, bot files): `bot_paths` records each
    bot's file path and content hash, so a replay says exactly which bot files produced it.
    """
    return {
        "seed": seed,
        "arena": list(arena),
        "squadrons": squadrons,
        "class_table_sha256": table_hash(table_path),
        # A caller that supplies `classes` without `table_path` still gets DEFAULT_TABLE's
        # hash above -- this field at least says so, rather than silently claiming it is the
        # table actually used.
        "class_table_source": str(table_path) if table_path is not None else "default",
        "bots": [
            {"path": str(p), "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
            for p in (bot_paths or [])
        ],
        "api_version": API_VERSION,
        "engine_version": ENGINE_VERSION,
        # `random`'s stream stability across interpreter versions is not guaranteed, so a
        # replay that will not reproduce should at least say why.
        "python_version": platform.python_version(),
    }


class _Writer:
    def __init__(self, path: str | Path, header: dict) -> None:
        self._fh = gzip.open(Path(path), "wt", encoding="utf-8")  # noqa: SIM115 -- closed in close()
        self._fh.write(json.dumps(header) + "\n")

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ThinWriter(_Writer):
    def record(self, tick: int, actions: dict[int, Action],
               statuses: dict[int, str]) -> None:
        self._fh.write(json.dumps({
            "tick": tick,
            # The engine/bot wire format, not a second hand-written copy of it: the thin
            # stream is canonical, so a format change must not be able to miss it.
            "actions": protocol.encode_actions(dict(sorted(actions.items()))),
            "statuses": {str(sq): s for sq, s in sorted(statuses.items())},
        }) + "\n")


class FatWriter(_Writer):
    def record(self, world, statuses: dict[int, str] | None = None) -> None:
        statuses = statuses or {}
        living = [p for _, p in sorted(world.planes.items()) if p.alive]

        # Per-squadron visibility, computed once here and RECORDED, never left to the viewer.
        visible: dict[str, list[int]] = {}
        for sq in sorted(world.damage_dealt):
            mine = [p for p in living if p.squadron == sq]
            seen = sorted({
                e.id for e in living if e.squadron != sq
                for o in mine if vision.sees(o, e, world.arena)
            })
            visible[str(sq)] = seen

        self._fh.write(json.dumps({
            "tick": world.tick_no,
            "planes": [
                {
                    "id": p.id, "squadron": p.squadron, "kind": p.kind,
                    "x": round(p.x, 3), "y": round(p.y, 3),
                    "heading_deg": round(p.heading_deg, 3), "speed": round(p.speed, 3),
                    "hp": p.hp, "hp_max": p.cls.hp, "alive": p.alive,
                    "ammo": list(p.ammo), "cooldown": list(p.cooldown),
                    "cone_deg": p.cls.cone_deg, "cone_range": p.cls.cone_range,
                    "rear_cone_deg": p.cls.rear_cone_deg,
                    "rear_cone_range": p.cls.rear_cone_range,
                    "bubble_range": p.cls.bubble_range,
                }
                for _, p in sorted(world.planes.items())
            ],
            "bullets": [[round(b.x, 2), round(b.y, 2), b.squadron] for b in world.bullets],
            "visible": visible,
            "scores": {str(sq): s for sq, s in sorted(world.scores().items())},
            "degraded": sorted(str(sq) for sq, s in statuses.items() if s != "ok"),
        }) + "\n")


def read(path: str | Path) -> tuple[dict, list[dict]]:
    with gzip.open(Path(path), "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    return lines[0], lines[1:]
