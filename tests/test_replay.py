import gzip
import json
from pathlib import Path

from skybattle import replay
from skybattle.classes import load_classes
from skybattle.match import run_round
from skybattle.state import Action
from skybattle.world import World

BOTS = Path(__file__).parent / "bots"
CLASSES = load_classes()
ARENA = (2000.0, 2000.0)
SQ = [["scout", "fighter"], ["scout", "fighter"]]


def _world():
    return World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=7)


def test_the_header_records_everything_needed_to_reproduce():
    h = replay.make_header(seed=7, arena=ARENA, squadrons=[["fighter"], ["fighter"]])
    for key in ("seed", "arena", "squadrons", "class_table_sha256", "class_table_source",
                "bots", "api_version", "engine_version", "python_version"):
        assert key in h


def test_class_table_source_says_default_or_names_the_path():
    """A caller supplying `classes` without `table_path` still gets DEFAULT_TABLE's hash -- this
    field at least says so instead of silently claiming it is the table actually used."""
    from skybattle.classes import DEFAULT_TABLE

    h = replay.make_header(seed=1, arena=ARENA, squadrons=[["fighter"], ["fighter"]])
    assert h["class_table_source"] == "default"
    h2 = replay.make_header(seed=1, arena=ARENA, squadrons=[["fighter"], ["fighter"]],
                            table_path=DEFAULT_TABLE)
    assert h2["class_table_source"] == str(DEFAULT_TABLE)


def test_the_header_identifies_the_bots_that_produced_the_replay(tmp_path):
    """(seed, class-table hash, bot files) must be recoverable from the artifact alone."""
    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
              classes=CLASSES, replay_dir=tmp_path)
    header, _ = replay.read(tmp_path / "round-001.thin.jsonl.gz")
    assert len(header["bots"]) == 2
    assert all("sha256" in b and "path" in b for b in header["bots"])


def test_thin_replay_records_actions_and_statuses_per_tick(tmp_path):
    p = tmp_path / "thin.jsonl.gz"
    with replay.ThinWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(1, {0: Action(throttle=1.0)}, {0: "ok", 1: "timeout"})
    header, ticks = replay.read(p)
    assert header["seed"] == 7
    assert ticks[0]["tick"] == 1
    assert ticks[0]["statuses"]["1"] == "timeout"


def test_fat_replay_carries_derived_fields_so_a_viewer_needs_no_engine(tmp_path):
    """The fat stream's derived fields are its whole product.

    A viewer reads `visible` and the cone geometry so it never has to embed the simulation.
    So assert they are POPULATED, not merely present.
    """
    w = _world()
    # Face the two squadrons at each other, close enough to see and to hit. Fighter cone_range
    # is 600.0 and cone_deg is 70.0 (classes.toml), so 200 units apart, dead ahead, is well
    # inside both.
    a, b = min(w.planes), max(w.planes)
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y, w.planes[b].heading_deg = 700.0, 500.0, 180.0
    sq_a, sq_b = w.planes[a].squadron, w.planes[b].squadron
    w.tick({sq_a: {a: Action(throttle=0.5, fire=frozenset({0}))},
            sq_b: {b: Action(throttle=0.5)}})

    p = tmp_path / "fat.jsonl.gz"
    with replay.FatWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(w)
    _, ticks = replay.read(p)
    frame = ticks[0]

    plane = frame["planes"][0]
    for key in ("id", "squadron", "kind", "x", "y", "heading_deg", "speed", "hp", "alive",
                "cone_deg", "cone_range", "rear_cone_deg", "rear_cone_range"):
        assert key in plane, key
    assert plane["cone_range"] > 0.0                      # real geometry, not a placeholder

    # Each squadron can see the other, and a round is in the air.
    assert frame["visible"][str(sq_a)] == [b]
    assert frame["visible"][str(sq_b)] == [a]
    assert len(frame["bullets"]) == 1
    assert frame["bullets"][0][2] == sq_a                 # owned by the shooter's squadron
    assert "scores" in frame


def test_fat_replay_records_a_degraded_tick_badge(tmp_path):
    w = _world()
    w.tick({p.squadron: {p.id: Action()} for p in w.planes.values()})
    p = tmp_path / "fat.jsonl.gz"
    with replay.FatWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(w, statuses={0: "ok", 1: "timeout"})
    _, ticks = replay.read(p)
    assert ticks[0]["degraded"] == ["1"]


def test_replays_are_gzipped_jsonl(tmp_path):
    p = tmp_path / "thin.jsonl.gz"
    with replay.ThinWriter(p, replay.make_header(7, ARENA, [["fighter"]])) as wr:
        wr.record(1, {}, {})
    with gzip.open(p, "rt") as fh:
        lines = [json.loads(x) for x in fh]
    assert len(lines) == 2               # header line, then one tick
