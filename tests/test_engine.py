# tests/test_engine.py
import threading
from config import Config
from src.models import GameState, Target
from src.engine import BotEngine

class FakeActions:
    def __init__(self):
        self.calls = []
        self._flasks = 300
    def flasks_left(self):
        return self._flasks
    def refill_energy(self):
        self._flasks -= 1
        self.calls.append(('refill',))
        return self._flasks
    def attack_mob(self, t):
        self.calls.append(('attack', t)); return True
    def assault_boss(self, t):
        self.calls.append(('assault', t)); return True
    def close_popups(self):
        self.calls.append(('close',))

class FakeStateSource:
    """Подменяет read_state сценарием состояний."""
    def __init__(self, states):
        self.states = states
        self.i = 0
    def next(self):
        s = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        return s

def _mk_engine(states, actions):
    cfg = Config(screen_w=900, screen_h=1600)
    eng = BotEngine(driver=None, vision=None, actions=actions, cfg=cfg,
                    log=lambda m: None, sleep=lambda s: None)
    src = FakeStateSource(states)
    eng.read_state = src.next          # инъекция состояний
    eng.flasks = 300
    return eng

def test_iteration_attacks_mob():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine([GameState(300, 130, 0, [mob], 900, 1600)], act)
    a = eng.one_iteration()
    assert a.type == 'attack_mob'
    assert ('attack', mob) in act.calls

def test_iteration_boss_priority():
    act = FakeActions()
    boss = Target('boss', 70, 450, 800)
    eng = _mk_engine([GameState(300, 130, 0, [boss], 900, 1600)], act)
    a = eng.one_iteration()
    assert a.type == 'assault_boss'
    assert ('assault', boss) in act.calls

def test_refill_updates_flask_memory():
    act = FakeActions()
    eng = _mk_engine([GameState(300, 10, 0, [], 900, 1600)], act)
    a = eng.one_iteration()
    assert a.type == 'refill'
    assert eng.flasks == 299            # обновили из возврата refill_energy

def test_run_stops_on_stop_action():
    act = FakeActions()
    eng = _mk_engine([GameState(179, 130, 0, [], 900, 1600)], act)  # склянки<180
    reason = eng.run(threading.Event())
    assert reason == 'stop'

def test_run_stops_on_event():
    act = FakeActions()
    ev = threading.Event(); ev.set()
    eng = _mk_engine([GameState(300, 130, 0, [], 900, 1600)], act)
    reason = eng.run(ev)
    assert reason == 'stopped_by_user'


class FakeDriver:
    def screenshot(self):
        return "IMG"


class FakeVision:
    """Возвращает заранее заданные значения, не читает реальные изображения."""
    def __init__(self, energy=42, deployed=1, targets=None):
        self._energy = energy
        self._deployed = deployed
        self._targets = targets if targets is not None else []
    def read_energy(self, img):
        return self._energy
    def read_deployed(self, img):
        return self._deployed
    def find_targets(self, img):
        return self._targets


def test_read_state_builds_gamestate_from_vision():
    cfg = Config(screen_w=900, screen_h=1600)
    mob = Target('mob', 5, 460, 810)
    driver = FakeDriver()
    vision = FakeVision(energy=42, deployed=1, targets=[mob])
    eng = BotEngine(driver=driver, vision=vision, actions=FakeActions(), cfg=cfg,
                    log=lambda m: None, sleep=lambda s: None)
    eng.flasks = 250

    state = eng.read_state()

    assert state.flasks == 250
    assert state.energy == 42
    assert state.deployed == 1
    assert state.targets == [mob]
    assert state.screen_w == 900
    assert state.screen_h == 1600


def test_read_state_handles_none():
    cfg = Config(screen_w=900, screen_h=1600)
    driver = FakeDriver()
    vision = FakeVision(energy=None, deployed=None, targets=[])
    eng = BotEngine(driver=driver, vision=vision, actions=FakeActions(), cfg=cfg,
                    log=lambda m: None, sleep=lambda s: None)
    eng.flasks = None

    state = eng.read_state()

    assert state.energy == 0
    assert state.deployed == 0
    assert state.flasks == 10**9


def test_start_reads_flask_count():
    cfg = Config(screen_w=900, screen_h=1600)
    act = FakeActions()
    act._flasks = 200
    eng = BotEngine(driver=None, vision=None, actions=act, cfg=cfg,
                    log=lambda m: None, sleep=lambda s: None)

    eng.start()

    assert eng.flasks == 200


def test_run_returns_error_on_iteration_exception():
    act = FakeActions()
    logs = []
    cfg = Config(screen_w=900, screen_h=1600)
    eng = BotEngine(driver=None, vision=None, actions=act, cfg=cfg,
                    log=logs.append, sleep=lambda s: None)
    eng.flasks = 300
    def boom():
        raise RuntimeError("kaboom")
    eng.read_state = boom
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('kaboom' in m for m in logs)


def test_run_returns_error_on_start_exception():
    class BoomActions(FakeActions):
        def flasks_left(self):
            raise NotImplementedError("no OCR")
    logs = []
    cfg = Config(screen_w=900, screen_h=1600)
    eng = BotEngine(driver=None, vision=None, actions=BoomActions(), cfg=cfg,
                    log=logs.append, sleep=lambda s: None)
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('no OCR' in m for m in logs)
