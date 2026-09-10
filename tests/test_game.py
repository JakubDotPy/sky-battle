from pathlib import Path

import pytest

from skybattle.cli import main
from skybattle.game import load_game
from skybattle.match import run_match

BOTS = Path(__file__).parent / "bots"


def _write(path, content):
    path.write_text(content)
    return path


# ------------------------------------------------------------------ defaults / path resolution

def test_defaults_are_applied_when_fields_are_omitted(tmp_path):
    (tmp_path / "bot_a.py").write_text('SQUADRON = ["scout", "fighter"]\n')
    (tmp_path / "bot_b.py").write_text('SQUADRON = ["scout", "fighter"]\n')
    game_file = _write(tmp_path / "game.toml", """
[[players]]
name = "a"
bot  = "bot_a.py"

[[players]]
name = "b"
bot  = "bot_b.py"
""")
    game = load_game(game_file)
    assert game.rounds == 11
    assert game.ticks_per_round == 3000
    assert game.planes_per_player == 2
    assert game.arena == (2000.0, 2000.0)
    assert game.seed == 1
    assert game.deadline == 0.05
    assert [p.name for p in game.players] == ["a", "b"]


def test_bot_paths_resolve_relative_to_the_game_file_not_cwd(tmp_path):
    """The game file lives in a subdirectory the test process never chdirs into -- if bot
    paths were resolved against the process cwd instead of the game file's own directory,
    the bot would not be found here."""
    game_dir = tmp_path / "somewhere" / "else"
    game_dir.mkdir(parents=True)
    bot_dir = game_dir / "bots"
    bot_dir.mkdir()
    (bot_dir / "mybot.py").write_text('SQUADRON = ["scout", "fighter"]\n')
    game_file = _write(game_dir / "game.toml", """
[[players]]
name = "a"
bot  = "bots/mybot.py"

[[players]]
name = "b"
bot  = "bots/mybot.py"
""")
    game = load_game(game_file)
    assert game.players[0].bot == (bot_dir / "mybot.py").resolve()


# ------------------------------------------------------------------ validation failures

def test_a_malformed_toml_file_is_rejected_naming_the_file(tmp_path):
    """tomllib.TOMLDecodeError IS a ValueError, so a bare `pytest.raises(ValueError)` would
    pass even if the wrapping that names the file were deleted -- assert the message."""
    game_file = _write(tmp_path / "game.toml", "this is not [ valid toml")
    with pytest.raises(ValueError, match="not valid TOML"):
        load_game(game_file)
    with pytest.raises(ValueError, match="game.toml"):
        load_game(game_file)


def test_a_game_file_with_no_players_is_rejected(tmp_path):
    game_file = _write(tmp_path / "game.toml", "[game]\nrounds = 3\n")
    with pytest.raises(ValueError, match="at least one"):
        load_game(game_file)


def test_a_player_missing_a_name_is_rejected(tmp_path):
    (tmp_path / "bot.py").write_text('SQUADRON = ["scout", "fighter"]\n')
    game_file = _write(tmp_path / "game.toml", '[[players]]\nbot = "bot.py"\n')
    with pytest.raises(ValueError, match="name"):
        load_game(game_file)


def test_an_arena_too_small_for_the_widest_cone_is_rejected(tmp_path):
    """The scout's 900-unit cone exceeds half of 1400, same as load_classes(arena=...) already
    enforces for `duel` -- a game file must get that check too, up front."""
    (tmp_path / "bot.py").write_text('SQUADRON = ["scout", "fighter"]\n')
    game_file = _write(tmp_path / "game.toml", """
[game]
arena = [2000, 1400]

[[players]]
name = "a"
bot  = "bot.py"

[[players]]
name = "b"
bot  = "bot.py"
""")
    with pytest.raises(ValueError, match="cone_range"):
        load_game(game_file)


def test_a_player_with_a_missing_bot_path_is_rejected(tmp_path):
    game_file = _write(tmp_path / "game.toml",
                       '[[players]]\nname = "a"\nbot = "does_not_exist.py"\n')
    with pytest.raises(ValueError, match="bot not found"):
        load_game(game_file)


def test_a_bot_without_squadron_is_rejected_naming_the_bot_file(tmp_path):
    bot = tmp_path / "no_squadron.py"
    bot.write_text("class Bot:\n    def act(self, state):\n        return {}\n")
    game_file = _write(tmp_path / "game.toml", f'[[players]]\nname = "a"\nbot = "{bot.name}"\n')
    with pytest.raises(ValueError, match="no module-level SQUADRON declaration"):
        load_game(game_file)


def test_a_squadron_with_a_non_string_literal_is_rejected(tmp_path):
    game_file = _write(tmp_path / "game.toml",
                       f'[[players]]\nname = "a"\nbot = "{BOTS / "bad_squadron_type.py"}"\n')
    with pytest.raises(ValueError, match="string literals"):
        load_game(game_file)


def test_a_squadron_kind_not_in_the_class_table_is_rejected_listing_valid_kinds(tmp_path):
    """bad_kind.py's SQUADRON is ["scout", "zeppelin"] -- length 2, matching the default
    planes_per_player, so only the kind check can fire, not the length check."""
    game_file = _write(tmp_path / "game.toml",
                       f'[[players]]\nname = "a"\nbot = "{BOTS / "bad_kind.py"}"\n')
    with pytest.raises(ValueError, match="zeppelin") as excinfo:
        load_game(game_file)
    assert "bomber" in str(excinfo.value) and "fighter" in str(excinfo.value) and (
        "scout" in str(excinfo.value)
    )


def test_a_squadron_length_mismatched_with_planes_per_player_is_rejected(tmp_path):
    """good_scout_fighter.py declares two VALID kinds, so with planes_per_player=3 only the
    length check can fire, not the kind check."""
    game_file = _write(tmp_path / "game.toml", f"""
[game]
planes_per_player = 3

[[players]]
name = "a"
bot  = "{BOTS / "good_scout_fighter.py"}"
""")
    with pytest.raises(ValueError, match=r"has 2 planes, expected planes_per_player=3"):
        load_game(game_file)


# ------------------------------------------------------------------ end to end

def _three_player_game_file(tmp_path, ticks_per_round=5, rounds=1):
    return _write(tmp_path / "game.toml", f"""
[game]
rounds            = {rounds}
ticks_per_round   = {ticks_per_round}
planes_per_player = 2
arena             = [2000, 2000]
seed              = 7

[[players]]
name = "jakub"
bot  = "{BOTS / "good_scout_fighter.py"}"

[[players]]
name = "anna"
bot  = "{BOTS / "good_fighter_bomber.py"}"

[[players]]
name = "petr"
bot  = "{BOTS / "good_bomber_scout.py"}"
""")


def test_a_three_player_game_file_loads_and_runs_a_short_match(tmp_path):
    game_file = _three_player_game_file(tmp_path, ticks_per_round=5, rounds=1)
    game = load_game(game_file)
    assert [p.name for p in game.players] == ["jakub", "anna", "petr"]
    assert [p.squadron for p in game.players] == [
        ["scout", "fighter"], ["fighter", "bomber"], ["bomber", "scout"],
    ]

    from skybattle.classes import load_classes
    squadrons = [p.squadron for p in game.players]
    result = run_match([p.bot for p in game.players], squadrons, seed=game.seed,
                       rounds=game.rounds, arena=game.arena,
                       classes=load_classes(arena=game.arena), deadline=game.deadline,
                       round_tick_limit=game.ticks_per_round)
    assert sorted(result.totals) == [0, 1, 2]
    # good_*.py bots never fire, so with only 5 ticks the round can only end by hitting the
    # tick limit -- this is the "ticks_per_round actually shortens a round" check.
    assert result.rounds[0].ticks == 5
    assert result.rounds[0].outcome == "timeout"


def test_the_cli_play_command_runs_and_prints_a_result_line_per_player(tmp_path, capsys):
    game_file = _three_player_game_file(tmp_path, ticks_per_round=5, rounds=1)
    code = main(["play", str(game_file)])
    assert code == 0
    out = capsys.readouterr().out
    for name in ("jakub", "anna", "petr"):
        assert name in out
    assert "accepted" in out
    assert "winner" in out


def test_a_bot_declaring_an_unknown_api_version_is_refused(tmp_path):
    """bot-api.md specifies this check; until now nothing compared a bot's declaration
    against the engine's own version."""
    bot = tmp_path / "future.py"
    bot.write_text('SQUADRON = ["scout", "fighter"]\nAPI_VERSION = 99\n')
    game = tmp_path / "game.toml"
    game.write_text('[game]\n[[players]]\nname = "a"\nbot = "future.py"\n')
    with pytest.raises(ValueError, match=r"declares API_VERSION = 99"):
        load_game(game)


def test_a_bot_declaring_the_current_api_version_is_accepted(tmp_path):
    from skybattle.state import API_VERSION
    bot = tmp_path / "ok.py"
    bot.write_text(f'SQUADRON = ["scout", "fighter"]\nAPI_VERSION = {API_VERSION}\n')
    game = tmp_path / "game.toml"
    game.write_text('[game]\n[[players]]\nname = "a"\nbot = "ok.py"\n')
    assert load_game(game).players[0].squadron == ["scout", "fighter"]


def test_a_bot_with_no_api_version_is_treated_as_current(tmp_path):
    """Requiring the constant would break every bot written before it was checked."""
    bot = tmp_path / "quiet.py"
    bot.write_text('SQUADRON = ["scout", "fighter"]\n')
    game = tmp_path / "game.toml"
    game.write_text('[game]\n[[players]]\nname = "a"\nbot = "quiet.py"\n')
    assert load_game(game).players[0].squadron == ["scout", "fighter"]


def test_a_non_integer_api_version_is_a_clear_error(tmp_path):
    bot = tmp_path / "bad.py"
    bot.write_text('SQUADRON = ["scout", "fighter"]\nAPI_VERSION = "one"\n')
    game = tmp_path / "game.toml"
    game.write_text('[game]\n[[players]]\nname = "a"\nbot = "bad.py"\n')
    with pytest.raises(ValueError, match="API_VERSION must be an integer literal"):
        load_game(game)
