import math
from config import Config
from src.models import Target, GameState, Action, Box, distance, nearest

def test_squad_limit_reserves_fourth_squad_by_default():
    """По умолчанию один отряд остаётся человеку."""
    assert Config().squad_limit() == 3
    assert Config(use_fourth_squad=True).squad_limit() == 4

def test_distance_euclidean():
    assert distance(0, 0, 3, 4) == 5.0

def test_nearest_picks_closest_to_center():
    a = Target('mob', 5, 100, 100)
    b = Target('mob', 5, 500, 500)
    assert nearest([a, b], 90, 90) is a

def test_nearest_empty_returns_none():
    assert nearest([], 0, 0) is None

def test_action_defaults_target_none():
    assert Action('stop').target is None

def test_gamestate_holds_targets():
    t = Target('boss', 70, 10, 20)
    gs = GameState(flasks=200, energy=130, deployed=0, targets=[t],
                   screen_w=900, screen_h=1600)
    assert gs.targets[0].kind == 'boss'

def test_box_center_and_at():
    b = Box(500, 800, 200, 60)
    assert b.center == (500, 800)
    assert Box.at((10, 20), (40, 24)) == Box(10, 20, 40, 24)
