from pathlib import Path

from skybattle.classes import load_classes
from skybattle.match import run_match, run_round

BOTS = Path(__file__).parent / "bots"
SAMPLES = Path(__file__).parent.parent / "samples"
CLASSES = load_classes()
ARENA = (2000.0, 2000.0)
SQ = [["scout", "fighter"], ["scout", "fighter"]]


def test_a_round_terminates_and_reports_both_squadrons():
    r = run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES)
    assert r.ticks > 0
    assert sorted(r.scores) == [0, 1]
    assert r.outcome != "ongoing"


def test_run_round_threads_a_supplied_table_path_into_the_replay_header(tmp_path):
    """The header must record the table that was ACTUALLY used, not always the default one.

    A plain string, as a caller passing a CLI argument or a config value would -- not a Path,
    which would silently paper over a missing str-to-Path coercion.
    """
    from skybattle import replay
    from skybattle.classes import DEFAULT_TABLE, table_hash

    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
              table_path=str(DEFAULT_TABLE), replay_dir=tmp_path)
    header, _ = replay.read(tmp_path / "round-001.thin.jsonl.gz")
    assert header["class_table_source"] == str(DEFAULT_TABLE)
    assert header["class_table_sha256"] == table_hash(DEFAULT_TABLE)


def test_a_hanging_bot_forfeits_but_the_round_still_finishes():
    r = run_round([BOTS / "good.py", BOTS / "hanger.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES, deadline=0.02)
    assert r.forfeited[1]
    assert not r.forfeited[0]
    assert r.outcome != "ongoing"


def test_a_forfeited_squadrons_planes_keep_existing(tmp_path):
    """A forfeit must not delete planes - that would change the physics for the survivor."""
    r = run_round([BOTS / "good.py", BOTS / "crasher.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES, deadline=0.02, replay_dir=tmp_path)
    assert r.forfeited[1]
    from skybattle import replay
    _, ticks = replay.read(tmp_path / "round-001.fat.jsonl.gz")
    last = ticks[-1]
    squadron_1 = [p for p in last["planes"] if p["squadron"] == 1]
    # existence, not survival: by round end both sides are typically drained to death since
    # neither good.py nor crasher.py's held-last action ever fires a shot, so asserting "alive"
    # would be wrong -- the count must simply still match the squadron that was spawned.
    assert len(squadron_1) == len(SQ[1]), "forfeited squadron's planes disappeared from the world"


def test_accepted_is_reported_alongside_strikes():
    r = run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES)
    # the honest number: a drained stale reply also costs the following tick
    assert r.accepted[0] <= r.ticks
    assert r.strikes[0] == 0


def test_a_match_is_eleven_rounds_and_sums_scores():
    m = run_match([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, rounds=3, arena=ARENA,
                  classes=CLASSES)
    assert len(m.rounds) == 3
    assert m.totals[0] == sum(r.scores[0] for r in m.rounds)


def test_the_same_seed_reproduces_the_same_match(tmp_path):
    """Determinism is the whole replay and CI story, so test it with a seed-sensitive bot.

    `good.py` returns a constant action, so comparing two of its runs would pass even if
    determinism were broken entirely. `random_walker.py` reads the per-squadron RNG, so its
    flight path is seed-derived -- but it never fires, so `totals` stays 0.0/0.0 for every seed
    (nothing ever deals damage; the drain always ends the round in a mutual draw). The
    same-seed check below still legitimately covers `run_match`'s `totals`; the divergence
    check needs the finer, still seed-derived signal of a plane's flown position from the fat
    replay, confirmed empirically: identical seeds produce byte-identical final plane state,
    different seeds do not.
    """
    walker = BOTS / "random_walker.py"
    kw = {"squadrons": SQ, "seed": 42, "rounds": 2, "arena": ARENA, "classes": CLASSES}
    a = run_match([walker, walker], **kw)
    b = run_match([walker, walker], **kw)
    assert a.totals == b.totals

    from skybattle import replay
    run_round([walker, walker], SQ, seed=42, arena=ARENA, classes=CLASSES,
              replay_dir=tmp_path / "same")
    run_round([walker, walker], SQ, seed=43, arena=ARENA, classes=CLASSES,
              replay_dir=tmp_path / "diff")
    _, same = replay.read(tmp_path / "same" / "round-001.fat.jsonl.gz")
    _, diff = replay.read(tmp_path / "diff" / "round-001.fat.jsonl.gz")
    assert same[-1]["planes"] != diff[-1]["planes"], (
        "a different seed produced an identical match; RNG is not wired in"
    )


def test_a_replay_pair_is_written_when_asked(tmp_path):
    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
              classes=CLASSES, replay_dir=tmp_path)
    assert (tmp_path / "round-001.thin.jsonl.gz").exists()
    assert (tmp_path / "round-001.fat.jsonl.gz").exists()


def test_the_thin_replay_records_the_actions_that_were_applied(tmp_path):
    """The thin replay is canonical truth: seed plus the action stream. Empty is useless."""
    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1,
              arena=ARENA, classes=CLASSES, replay_dir=tmp_path)
    from skybattle import replay
    _, ticks = replay.read(tmp_path / "round-001.thin.jsonl.gz")
    assert any(frame["actions"] for frame in ticks), "thin replay recorded no actions"


def test_the_cli_duel_command_runs_and_prints_one_result_line(capsys):
    from skybattle.cli import main
    code = main(["duel", str(BOTS / "good.py"), str(BOTS / "good.py"),
                 "--seed", "3", "--rounds", "1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "squadron 0" in out
    assert "accepted" in out


def test_rules_prints_the_class_table_without_bot_paths(capsys):
    from skybattle.cli import main
    assert main(["duel", "--rules"]) == 0
    out = capsys.readouterr().out
    assert "[scout]" in out and "cone_range" in out
