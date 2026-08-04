# tests/test_engine.py
import threading
from config import Config
from src.models import GameState, Target
from src.engine import BotEngine

class FakeActions:
    def __init__(self, search_result="dispatched", attack_result="dispatched"):
        self.calls = []
        self._flasks = 300
        self._search_result = search_result
        self._attack_result = attack_result
        self.last_flasks = None
        self.attack_kwargs = None
    def flasks_left(self):
        self.calls.append(('flasks_left',))
        return self._flasks
    def refill_energy(self):
        self._flasks -= 1
        self.calls.append(('refill',))
        return self._flasks
    def attack_mob(self, t, refill=False, want_flasks=False):
        self.calls.append(('attack', t))
        self.attack_kwargs = (refill, want_flasks)
        if want_flasks or refill:
            self.last_flasks = self._flasks
        return self._attack_result
    def assault_boss(self, t):
        self.calls.append(('assault', t)); return "dispatched"
    def search_and_attack_mob(self, refill=False, want_flasks=False):
        self.calls.append(('search', refill, want_flasks))
        if want_flasks or refill:
            self.last_flasks = self._flasks
        return self._search_result

class FakeDriver:
    def __init__(self, boom=False):
        self._boom = boom
        self.zoom_outs = 0
    def screenshot(self):
        if self._boom:
            raise RuntimeError("kaboom")
        return "IMG"
    def swipe(self, *a, **k):
        pass
    def zoom_out(self):
        self.zoom_outs += 1

class FakeVision:
    def __init__(self, energy=130, targets=None, squad='idle', on_map=True, active=0):
        self._energy = energy
        self._targets = targets if targets is not None else []
        self._squad = squad
        self._on_map = on_map
        self._active = active          # «Отряд N/4» для режима скверны
    def active_squads(self, img):
        return self._active
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
    # старые тесты проверяют map-based путь -> отключаем и search, и скверну
    cfg = Config(screen_w=900, screen_h=1600, dry_run=dry_run,
                 use_search_strategy=False, strategy="map")
    eng = BotEngine(driver=driver or FakeDriver(),
                    vision=FakeVision(energy, targets, squad, on_map),
                    actions=actions, cfg=cfg, log=lambda m: None, sleep=lambda s: None)
    eng.flasks = flasks
    return eng

def _mk_search_engine(actions, squad='idle', energy=130, flasks=300, targets=None):
    cfg = Config(screen_w=900, screen_h=1600, use_search_strategy=True, strategy="thief")
    eng = BotEngine(driver=FakeDriver(),
                    vision=FakeVision(energy=energy, targets=targets, squad=squad),
                    actions=actions, cfg=cfg, log=lambda m: None, sleep=lambda s: None)
    eng.flasks = flasks
    return eng

# --- Режим «Элитная скверна» ---

class FakeCorruption:
    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []
        self.last_flasks = None
    def run_once(self, refill=False, want_flasks=False):
        self.calls.append((refill, want_flasks))
        return self.results.pop(0) if self.results else "dispatched"

def _mk_corruption_engine(corruption, active=0, energy=80, flasks=251):
    cfg = Config(screen_w=900, screen_h=1600, strategy="corruption")
    eng = BotEngine(driver=FakeDriver(), vision=FakeVision(energy=energy, active=active),
                    actions=FakeActions(), cfg=cfg, log=lambda m: None,
                    sleep=lambda s: None, corruption=corruption)
    eng.flasks = flasks
    return eng

def test_corruption_dispatches_when_squad_free():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, active=1)
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == [(False, False)]

def test_corruption_waits_when_all_squads_busy():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr, active=4)
    assert eng.one_iteration() is None
    assert corr.calls == []                  # ни одного захода

def test_corruption_dispatches_on_last_free_slot():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, active=3)
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == [(False, False)]

def test_corruption_requests_refill_when_energy_low():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, energy=15, flasks=251)   # < corruption_energy_cost
    eng.one_iteration()
    assert corr.calls == [(True, False)]

def test_corruption_stops_when_energy_low_and_flasks_below_threshold():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr, energy=15, flasks=100)
    assert eng.one_iteration().type == "stop"
    assert corr.calls == []

def test_corruption_keeps_farming_on_low_flasks_while_energy_lasts():
    """Склянок мало, но энергии хватает -> продолжаем, стоп только когда
    энергия кончится (решение юзера: ждём отряды, стоп по энергии)."""
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, energy=80, flasks=100)
    assert eng.one_iteration().type == "assault_boss"

def test_corruption_reads_flasks_first_time_instead_of_spending():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, energy=15)
    eng.flasks = None                        # ещё не читали
    eng.one_iteration()
    assert corr.calls == [(False, True)]     # читаем, но склянку не тратим

def test_corruption_updates_flask_memory_from_side_trip():
    corr = FakeCorruption(["dispatched"])
    corr.last_flasks = 240
    eng = _mk_corruption_engine(corr)
    eng.one_iteration()
    assert eng.flasks == 240

def test_corruption_stops_after_max_failures():
    corr = FakeCorruption(["failed"] * 5)
    eng = _mk_corruption_engine(corr)
    last = None
    for _ in range(eng.cfg.max_search_failures):
        last = eng.one_iteration()
    assert last.type == "stop"

def test_corruption_failure_counter_resets_on_success():
    corr = FakeCorruption(["failed", "dispatched", "failed", "failed"])
    eng = _mk_corruption_engine(corr)
    for _ in range(4):
        action = eng.one_iteration()
    assert action.type == "assault_boss"     # 3 подряд не набралось -> не стоп

def test_corruption_dry_run_does_not_act():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr)
    eng.cfg.dry_run = True
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == []

def test_corruption_start_defers_flask_read_to_preview():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr)
    eng.flasks = None
    eng.start()
    assert eng.flasks is None                # окно энергии только с превью

def test_search_strategy_searches_when_idle():
    act = FakeActions()
    eng = _mk_search_engine(act, squad='idle')
    eng.one_iteration()
    assert act.calls[0][0] == 'search'       # ищем вора и отправляем

def test_search_start_does_not_open_energy_window_from_map():
    """С карты «+» тапнет кнопку дома -> в режиме поиска склянки на старте НЕ
    читаем (прочитаем пиггибеком на первом превью отправки)."""
    act = FakeActions()
    eng = _mk_search_engine(act, flasks=None)
    eng.start()
    assert ('flasks_left',) not in act.calls
    assert eng.flasks is None

def test_search_reads_flasks_on_first_dispatch():
    act = FakeActions(); act._flasks = 240
    eng = _mk_search_engine(act, flasks=None)
    eng.one_iteration()
    assert act.calls == [('search', False, True)]   # refill=False, want_flasks=True
    assert eng.flasks == 240

def test_search_requests_refill_when_energy_low():
    act = FakeActions()
    eng = _mk_search_engine(act, energy=12)         # < energy_refill_threshold
    eng.one_iteration()
    assert act.calls == [('search', True, False)]

def test_search_stops_when_flasks_below_threshold():
    act = FakeActions()
    eng = _mk_search_engine(act, flasks=100)        # < flask_stop_threshold
    a = eng.one_iteration()
    assert a.type == 'stop'
    assert act.calls == []                          # без тапов

def test_search_stops_after_repeated_failures():
    """«Поиск» перестал давать панель (событие кончилось/вёрстка иная) —
    не долбимся вслепую, а останавливаемся и зовём человека."""
    act = FakeActions(search_result="no_thief")
    eng = _mk_search_engine(act)
    for _ in range(eng.cfg.max_search_failures - 1):
        assert eng.one_iteration().type != 'stop'
    assert eng.one_iteration().type == 'stop'

def test_search_failure_counter_resets_after_success():
    act = FakeActions(search_result="no_thief")
    eng = _mk_search_engine(act)
    for _ in range(eng.cfg.max_search_failures - 1):
        eng.one_iteration()                         # провалы, но ещё не стоп
    act._search_result = "dispatched"
    eng.one_iteration()                             # успех -> счётчик сброшен
    act._search_result = "no_thief"
    assert eng.one_iteration().type != 'stop'       # снова 1 провал подряд

def test_search_strategy_waits_when_marching():
    act = FakeActions()
    eng = _mk_search_engine(act, squad='marching')
    a = eng.one_iteration()
    assert a is None
    assert act.calls == []                   # отряд занят -> не ищем

# --- Гибрид: фарм видимых соседей до нового «Поиска вора» ---

def test_search_attacks_visible_neighbor_instead_of_searching():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)         # виден на текущем виде
    eng = _mk_search_engine(act, targets=[mob])
    eng.one_iteration()
    assert ('attack', mob) in act.calls               # фармим соседа
    assert not any(c[0] == 'search' for c in act.calls)   # без нового «Поиска»

def test_search_falls_back_to_thief_when_no_neighbor_mobs():
    act = FakeActions()
    eng = _mk_search_engine(act, targets=[])          # соседей не видно
    eng.one_iteration()
    assert any(c[0] == 'search' for c in act.calls)
    assert not any(c[0] == 'attack' for c in act.calls)

def test_search_picks_neighbor_nearest_to_center():
    act = FakeActions()
    far = Target('mob', 5, 100, 200)
    near = Target('mob', 5, 470, 780)        # центр экрана (450, 800)
    eng = _mk_search_engine(act, targets=[far, near])
    eng.one_iteration()
    attacked = [c[1] for c in act.calls if c[0] == 'attack']
    assert attacked == [near]                # ближайший к центру = короткий марш

def test_search_ignores_boss_neighbor_and_searches():
    act = FakeActions()
    boss = Target('boss', 0, 460, 810)       # рогатый / ложный UI -> не моб
    eng = _mk_search_engine(act, targets=[boss])
    eng.one_iteration()
    assert not any(c[0] == 'attack' for c in act.calls)   # босса соседом не фармим
    assert any(c[0] == 'search' for c in act.calls)       # мобов нет -> поиск

def test_search_reads_flasks_on_neighbor_dispatch():
    act = FakeActions(); act._flasks = 240
    mob = Target('mob', 5, 460, 810)
    eng = _mk_search_engine(act, flasks=None, targets=[mob])
    eng.one_iteration()
    assert act.attack_kwargs == (False, True)   # refill=False, want_flasks=True
    assert eng.flasks == 240

def test_search_requests_refill_on_neighbor_when_energy_low():
    act = FakeActions()
    mob = Target('mob', 5, 460, 810)
    eng = _mk_search_engine(act, energy=12, targets=[mob])   # < energy_refill_threshold
    eng.one_iteration()
    assert act.attack_kwargs == (True, False)

def test_search_skips_phantom_neighbor_after_failed_attack():
    act = FakeActions(attack_result="wrong_panel")
    phantom = Target('mob', 5, 460, 810)
    eng = _mk_search_engine(act, targets=[phantom])
    eng.one_iteration()
    assert eng._target_key(phantom) in eng.skip_targets   # не выбираем снова

def test_search_stops_after_no_progress_across_neighbor_and_search():
    """Промах по соседу (-> skip) и провал «Поиска» одинаково копят
    «нет прогресса»; после порога — стоп и зов человека."""
    act = FakeActions(search_result="no_thief", attack_result="missed")
    mob = Target('mob', 5, 460, 810)
    eng = _mk_search_engine(act, targets=[mob])
    results = [eng.one_iteration() for _ in range(eng.cfg.max_search_failures)]
    assert results[-1].type == 'stop'
    assert all(r is None or r.type != 'stop' for r in results[:-1])

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

def test_guard_pinches_and_blocks_when_not_on_world_map():
    act = FakeActions()
    boss = Target('boss', 0, 450, 800)          # был бы assault, но мы не на карте
    drv = FakeDriver()
    eng = _mk_engine(act, targets=[boss], on_map=False, driver=drv)
    a = eng.one_iteration()
    assert a is None                            # guard -> действия нет
    assert act.calls == []                      # ни одного тапа-действия
    assert drv.zoom_outs == 1                   # но пробуем авто-отзум щипком

def test_guard_stops_pinching_after_limit():
    act = FakeActions()
    drv = FakeDriver()
    eng = _mk_engine(act, targets=[], on_map=False, driver=drv)
    for _ in range(10):
        eng.one_iteration()
    assert drv.zoom_outs == eng.cfg.max_pinch_recover   # не долбим щипком бесконечно

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
    eng = BotEngine(driver=None, vision=None, actions=act,
                    cfg=Config(use_search_strategy=False, strategy="map"),
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
    eng = BotEngine(driver=None, vision=None, actions=BoomActions(),
                    cfg=Config(use_search_strategy=False, strategy="map"),
                    log=logs.append, sleep=lambda s: None)
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('no OCR' in m for m in logs)
