# tests/test_decide.py
from config import Config
from src.models import GameState, Target
from src.decide import decide

CFG = Config(screen_w=900, screen_h=1600)

def _state(**kw):
    base = dict(flasks=300, energy=130, deployed=0, targets=[],
                screen_w=900, screen_h=1600)
    base.update(kw)
    return GameState(**base)

def test_stop_when_flasks_below_threshold():
    assert decide(_state(flasks=179), CFG).type == 'stop'

def test_refill_when_energy_low():
    assert decide(_state(energy=19), CFG).type == 'refill'

def test_stop_beats_refill():
    # склянки кончились и энергия низкая -> всё равно stop
    assert decide(_state(flasks=100, energy=5), CFG).type == 'stop'

def test_wait_when_squad_deployed():
    assert decide(_state(deployed=1), CFG).type == 'wait'

def test_boss_priority_over_mob():
    boss = Target('boss', 70, 800, 800)
    mob = Target('mob', 5, 450, 800)   # ближе к центру
    a = decide(_state(targets=[mob, boss]), CFG)
    assert a.type == 'assault_boss' and a.target is boss

def test_attack_nearest_mob():
    m_far = Target('mob', 5, 100, 100)
    m_near = Target('mob', 5, 460, 810)   # рядом с центром (450,800)
    a = decide(_state(targets=[m_far, m_near]), CFG)
    assert a.type == 'attack_mob' and a.target is m_near

def test_mob_level_filtered_out():
    off = Target('mob', 27, 450, 800)     # не в farm_levels -> explore
    assert decide(_state(targets=[off]), CFG).type == 'explore'

def test_explore_when_no_targets():
    assert decide(_state(targets=[]), CFG).type == 'explore'

def test_boss_ignores_level_filter():
    boss = Target('boss', 70, 450, 800)
    assert decide(_state(targets=[boss]), CFG).type == 'assault_boss'
