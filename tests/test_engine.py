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
        self.calls.append(('attack', t)); return "dispatched"
    def assault_boss(self, t):
        self.calls.append(('assault', t)); return "dispatched"

class FakeDriver:
    def __init__(self, boom=False):
        self._boom = boom
    def screenshot(self):
        if self._boom:
            raise RuntimeError("kaboom")
        return "IMG"
    def swipe(self, *a, **k):
        pass

class FakeVision:
    def __init__(self, energy=130, targets=None, squad='idle', on_map=True):
        self._energy = energy
        self._targets = targets if targets is not None else []
        self._squad = squad
        self._on_map = on_map
    def on_world_map(self, img):
        return self._on_map
    def read_energy(self, img):
        return self._energy
    def find_targets(self, img):
        return self._targets
    def squad_state(self, img):
        return self._squad

def _mk_engine(actions, energy=130, targets=None, squad='idle', flasks=300,
               dry_run=False, driver=None, on_map=True):
    cfg = Config(screen_w=900, screen_h=1600, dry_run=dry_run)
    eng = BotEngine(driver=driver or FakeDriver(),
                    vision=FakeVision(energy, targets, squad, on_map),
                    actions=actions, cfg=cfg, log=lambda m: None, sleep=lambda s: None)
    eng.flasks = flasks
    return eng

def test_iteration_attacks_mob():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine(act, targets=[mob])
    a = eng.one_iteration()
    assert a.type == 'attack_mob'
    assert ('attack', mob) in act.calls

def test_iteration_boss_priority():
    act = FakeActions()
    boss = Target('boss', 0, 450, 800)
    eng = _mk_engine(act, targets=[boss])
    a = eng.one_iteration()
    assert a.type == 'assault_boss'
    assert ('assault', boss) in act.calls

def test_guard_blocks_action_when_not_on_world_map():
    act = FakeActions()
    boss = Target('boss', 0, 450, 800)          # был бы assault, но мы не на карте
    eng = _mk_engine(act, targets=[boss], on_map=False)
    a = eng.one_iteration()
    assert a is None                            # guard -> ничего не делаем
    assert act.calls == []                      # ни одного тапа/действия

def test_squad_busy_marching_waits():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine(act, targets=[mob], squad='marching')
    a = eng.one_iteration()
    assert a is None                 # занят -> ждём
    assert act.calls == []           # ничего не отправляли

def test_squad_returning_sends_next():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine(act, targets=[mob], squad='returning')   # send_next_on_return=True
    a = eng.one_iteration()
    assert a.type == 'attack_mob'
    assert ('attack', mob) in act.calls

def test_boss_skip_unwinnable_marks_and_excludes():
    class SkipActions(FakeActions):
        def assault_boss(self, t):
            self.calls.append(('assault', t)); return 'skip_unwinnable'
    act = SkipActions()
    boss = Target('boss', 0, 450, 800)
    eng = _mk_engine(act, targets=[boss])
    a1 = eng.one_iteration()
    assert a1.type == 'assault_boss'
    assert eng.skip_targets                      # босс помечен непроходимым
    a2 = eng.one_iteration()                     # тот же босс исключён
    assert a2.type == 'explore'                  # мобов нет -> explore

def test_dry_run_decides_without_acting():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine(act, targets=[mob], dry_run=True)
    a = eng.one_iteration()
    assert a.type == 'attack_mob'
    assert act.calls == []           # dry-run: ни одного действия

def test_refill_updates_flask_memory():
    act = FakeActions()
    eng = _mk_engine(act, energy=10, targets=[])
    a = eng.one_iteration()
    assert a.type == 'refill'
    assert eng.flasks == 299

def test_run_stops_on_stop_action():
    act = FakeActions()
    eng = _mk_engine(act, flasks=179)         # склянки<180 -> stop
    reason = eng.run(threading.Event())
    assert reason == 'stop'

def test_run_stops_on_event():
    act = FakeActions()
    ev = threading.Event(); ev.set()
    eng = _mk_engine(act)
    reason = eng.run(ev)
    assert reason == 'stopped_by_user'

def test_read_state_builds_gamestate_from_vision():
    mob = Target('mob', 5, 460, 810)
    eng = _mk_engine(FakeActions(), energy=42, targets=[mob], flasks=250)
    state = eng.read_state("IMG")
    assert state.flasks == 250
    assert state.energy == 42
    assert state.deployed == 0
    assert state.targets == [mob]
    assert state.screen_w == 900
    assert state.screen_h == 1600

def test_read_state_handles_none_energy():
    eng = _mk_engine(FakeActions(), energy=None, targets=[], flasks=None)
    state = eng.read_state("IMG")
    assert state.energy == 999        # не прочли -> высокий сентинел (без ложного рефилла)
    assert state.deployed == 0
    assert state.flasks == 10**9

def test_start_reads_flask_count():
    act = FakeActions(); act._flasks = 200
    eng = BotEngine(driver=None, vision=None, actions=act, cfg=Config(),
                    log=lambda m: None, sleep=lambda s: None)
    eng.start()
    assert eng.flasks == 200

def test_run_returns_error_on_iteration_exception():
    logs = []
    cfg = Config()
    eng = BotEngine(driver=FakeDriver(boom=True), vision=FakeVision(),
                    actions=FakeActions(), cfg=cfg, log=logs.append, sleep=lambda s: None)
    eng.flasks = 300
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('kaboom' in m for m in logs)

def test_run_returns_error_on_start_exception():
    class BoomActions(FakeActions):
        def flasks_left(self):
            raise NotImplementedError("no OCR")
    logs = []
    eng = BotEngine(driver=None, vision=None, actions=BoomActions(), cfg=Config(),
                    log=logs.append, sleep=lambda s: None)
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('no OCR' in m for m in logs)
