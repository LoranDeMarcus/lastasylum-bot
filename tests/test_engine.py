# tests/test_engine.py
import threading
import time
from config import Config
from src.cancel import Cancel
from src.models import GameState, Target
from src.engine import BotEngine

class FakeActions:
    def __init__(self, attack_result="dispatched"):
        self.calls = []
        self._flasks = 300
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
    def __init__(self, energy=130, targets=None, squad='idle', on_map=True, active=0,
                 active_after=None):
        self._energy = energy
        self._targets = targets if targets is not None else []
        self._squad = squad
        self._on_map = on_map
        self._active = active          # «Отряд N/4» для режима скверны
        # что покажет счётчик со ВТОРОГО чтения: движок сверяет число отрядов
        # до и после отправки. None -> счётчик не меняется
        self._active_after = active_after
        self.active_reads = 0
    def active_squads(self, img):
        self.active_reads += 1
        if self.active_reads > 1 and self._active_after is not None:
            return self._active_after
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
    # старые тесты проверяют map-based путь -> strategy="map" отключает скверну/join/вора
    cfg = Config(screen_w=900, screen_h=1600, dry_run=dry_run, strategy="map")
    eng = BotEngine(driver=driver or FakeDriver(),
                    vision=FakeVision(energy, targets, squad, on_map),
                    actions=actions, cfg=cfg, log=lambda m: None, sleep=lambda s: None)
    eng.flasks = flasks
    return eng

# --- Режим «Элитная скверна» ---

class FakeCorruption:
    def __init__(self, results=(), spend=0, stock=None):
        self.results = list(results)
        self.calls = []
        self.flasks_used = 0
        self.last_flask_stock = None
        self._spend = spend          # сколько склянок «тратит» каждый заход
        self._stock = stock          # что «прочитано» в «В наличии: N»
    def run_once(self, refill=False):
        self.calls.append(refill)
        if refill:
            self.flasks_used += self._spend
            if self._stock is not None:
                self.last_flask_stock = self._stock
                self._stock -= self._spend
        return self.results.pop(0) if self.results else "dispatched"

def _mk_corruption_engine(corruption, active=0, energy=80, flasks=251, fourth=True):
    # существующие тесты писались, когда бот занимал все четыре отряда ->
    # по умолчанию в хелпере включаем 4-й, а резерв проверяем отдельными тестами
    cfg = Config(screen_w=900, screen_h=1600, strategy="corruption",
                 use_fourth_squad=fourth)
    eng = BotEngine(driver=FakeDriver(), vision=FakeVision(energy=energy, active=active),
                    actions=FakeActions(), cfg=cfg, log=lambda m: None,
                    sleep=lambda s: None, corruption=corruption)
    eng.flasks = flasks
    return eng

class FakeWatchdog:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0
    def check(self):
        self.calls += 1
        return self.verdicts.pop(0) if self.verdicts else 'ok'

class _NoopCorruption:
    """Штурма быть не должно: сторож обязан развернуть итерацию раньше."""
    flasks_used = 0
    last_flask_stock = None
    def run_once(self, refill=False):
        raise AssertionError("движок не должен доходить до штурма")

def test_corruption_iteration_stops_on_watchdog_verdict():
    eng = _mk_corruption_engine(_NoopCorruption())
    eng.watchdog = FakeWatchdog(['stop'])
    action = eng.one_iteration()
    assert action is not None and action.type == 'stop'

def test_corruption_iteration_skips_turn_after_recovery():
    """recovered -> итерация начинается заново со свежего кадра, не тапая."""
    eng = _mk_corruption_engine(_NoopCorruption())
    eng.watchdog = FakeWatchdog(['recovered'])
    assert eng.one_iteration() is None

def test_idle_wait_wakes_up_on_stop():
    """Ожидание «все отряды заняты» — самая длинная пауза бота (10-14 с).
    Стоп должен будить из неё, а не только между итерациями.

    Отмена взводится ИЗ ТАЙМЕРА, а не заранее: заранее взведённая отмена
    развернула бы итерацию ещё на входе, и тест перестал бы проверять
    пробуждение из паузы."""
    cancel = Cancel()
    cfg = Config(screen_w=900, screen_h=1600, strategy="corruption")
    eng = BotEngine(driver=FakeDriver(), vision=FakeVision(active=4),
                    actions=FakeActions(), cfg=cfg, log=lambda m: None,
                    sleep=cancel.sleep, corruption=FakeCorruption(), cancel=cancel)
    eng.flasks = 251
    threading.Timer(0.1, cancel.set).start()
    t0 = time.perf_counter()
    assert eng.one_iteration() is None
    assert time.perf_counter() - t0 < 2.0      # а не corruption_poll_interval_s = 10 с

def test_corruption_dispatches_when_squad_free():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, active=1)
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == [True]              # склянок 251 > порога -> рефилл разрешён

def test_corruption_waits_when_all_squads_busy():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr, active=4)
    assert eng.one_iteration() is None
    assert corr.calls == []                  # ни одного захода

def test_corruption_waits_when_fourth_squad_is_reserved():
    """Три отряда заняты, четвёртый зарезервирован -> ждём, а не шлём."""
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr, active=3, fourth=False)
    assert eng.one_iteration() is None
    assert corr.calls == []

def test_corruption_uses_fourth_squad_when_enabled():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, active=3, fourth=True)
    assert eng.one_iteration().type == "assault_boss"

def test_corruption_dispatches_on_last_free_slot():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, active=3)
    assert eng.one_iteration().type == "assault_boss"

def test_corruption_forbids_refill_at_or_below_threshold():
    """Порог из GUI: на нём и ниже склянки не тратим, но фармить продолжаем,
    пока хватает энергии."""
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, flasks=180)     # ровно порог
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == [False]

def test_corruption_allows_refill_above_threshold():
    corr = FakeCorruption(["dispatched"])
    eng = _mk_corruption_engine(corr, flasks=181)
    eng.one_iteration()
    assert corr.calls == [True]

def test_corruption_allows_probe_refill_when_stock_unknown():
    """«В наличии: N» читается только ПОСЛЕ применения, поэтому первый рефилл
    разрешён вслепую — он же и выясняет реальный остаток."""
    corr = FakeCorruption(["dispatched"], spend=2, stock=273)
    eng = _mk_corruption_engine(corr)
    eng.flasks = None
    eng.one_iteration()
    assert corr.calls == [True]
    assert eng.flasks == 273           # остаток стал известен

def test_corruption_prefers_read_stock_over_local_count():
    corr = FakeCorruption(["dispatched"], spend=2, stock=273)
    eng = _mk_corruption_engine(corr, flasks=500)   # учёт был неверным
    eng.one_iteration()
    assert eng.flasks == 273                        # верим прочитанному

def test_corruption_subtracts_spent_when_stock_unreadable():
    corr = FakeCorruption(["dispatched"], spend=2)
    eng = _mk_corruption_engine(corr, flasks=200)
    eng.one_iteration()
    assert eng.flasks == 198

def test_corruption_stops_spending_once_threshold_reached():
    corr = FakeCorruption(["dispatched", "dispatched"], spend=2)
    eng = _mk_corruption_engine(corr, flasks=182)
    eng.one_iteration()                      # 182 -> 180
    assert eng.flasks == 180
    eng.one_iteration()                      # на пороге -> больше не тратим
    assert corr.calls == [True, False]

def test_corruption_stops_immediately_on_low_energy_verdict():
    """Превью сказало «энергии мало» — это источник истины, стопимся сразу,
    не дожидаясь трёх провалов."""
    corr = FakeCorruption(["low_energy"])
    eng = _mk_corruption_engine(corr, energy=80)   # HUD мог прочитаться неверно
    assert eng.one_iteration().type == "stop"

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

def test_corruption_stopped_result_stops_engine_without_counting_failure():
    """'stopped' — не провал: человек сам нажал кнопку."""
    corr = FakeCorruption(["stopped"])
    eng = _mk_corruption_engine(corr, active=1)
    action = eng.one_iteration()
    assert action is not None and action.type == "stop"
    assert eng._no_progress == 0

def test_iteration_returns_stop_when_cancelled_before_start():
    corr = FakeCorruption()
    cancel = Cancel()
    cancel.set()
    eng = _mk_corruption_engine(corr, active=0)
    eng.cancel = cancel
    action = eng.one_iteration()
    assert action is not None and action.type == "stop"
    assert corr.calls == []            # до штурма не дошло

def test_corruption_dry_run_does_not_act():
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr)
    eng.cfg.dry_run = True
    assert eng.one_iteration().type == "assault_boss"
    assert corr.calls == []

def test_corruption_start_leaves_stock_unknown_until_read_from_game():
    """Ручного поля больше нет: остаток берётся из «В наличии: N» после
    первого рефилла, до этого он неизвестен и порог не ограничивает."""
    corr = FakeCorruption()
    eng = _mk_corruption_engine(corr)
    eng.flasks = None
    eng.start()
    assert eng.flasks is None

def test_unreadable_stock_is_logged_not_silently_ignored():
    """Раньше эту дыру закрывало ручное поле: если «В наличии: N» не
    прочиталось, порог молча перестаёт действовать."""
    lines = []
    corr = FakeCorruption(["dispatched"], spend=2, stock=None)
    eng = _mk_corruption_engine(corr)
    eng.log = lines.append
    eng.flasks = None
    eng.one_iteration()
    assert any("прочитать не удалось" in s for s in lines)

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
                    cfg=Config(strategy="map"),
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
                    cfg=Config(strategy="map"),
                    log=logs.append, sleep=lambda s: None)
    reason = eng.run(threading.Event())
    assert reason == 'error'
    assert any('no OCR' in m for m in logs)

# --- Режим «присоединяться к чужим штурмам» ---

class FakeJoin:
    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []
    def run_once(self):
        self.calls.append(None)
        return self.results.pop(0) if self.results else "dispatched"

def _mk_join_engine(join, active=0, energy=80, fourth=True, active_after=None):
    cfg = Config(screen_w=900, screen_h=1600, strategy="join",
                 use_fourth_squad=fourth)
    eng = BotEngine(driver=FakeDriver(),
                    vision=FakeVision(energy=energy, active=active,
                                      active_after=active_after),
                    actions=FakeActions(), cfg=cfg, log=lambda m: None,
                    sleep=lambda s: None, join=join)
    return eng

def test_join_waits_when_all_squads_busy():
    join = FakeJoin(["dispatched"])
    eng = _mk_join_engine(join, active=4)
    assert eng.one_iteration() is None
    assert join.calls == []                 # в окно даже не заходили

def test_join_dispatches_when_slot_free():
    join = FakeJoin(["dispatched"])
    eng = _mk_join_engine(join, active=1, active_after=2)   # отряд реально вышел
    assert eng.one_iteration().type == 'join_assault'
    assert len(join.calls) == 1
    assert eng._no_progress == 0

def test_join_dispatch_without_squad_growth_is_not_progress():
    """Живой прогон 2026-08-10: JoinActions отдал 'dispatched', а счётчик
    отрядов в игре так и остался 0/4 — сбор истёк между обновлением списка и
    тапом по «Отправиться». Отправку надо ПРОВЕРЯТЬ, а не объявлять:
    неподтверждённая не успех, счётчик провалов обязан расти, иначе бот
    молчаливо крутится вхолостую (I-1)."""
    join = FakeJoin(["dispatched"])
    eng = _mk_join_engine(join, active=0)      # счётчик отрядов не вырос
    eng.one_iteration()
    assert eng._no_progress == 1

def test_join_unconfirmed_dispatch_eventually_stops():
    """Три неподтверждённые отправки подряд — стоп и зов человека, а не
    бесконечный холостой цикл."""
    join = FakeJoin(["dispatched"] * Config().max_search_failures)
    eng = _mk_join_engine(join, active=0)
    for _ in range(Config().max_search_failures - 1):
        assert eng.one_iteration().type == 'join_assault'
    assert eng.one_iteration().type == 'stop'

def test_join_counts_only_confirmed_joins():
    """Счётчик вступлений — тот, по которому раннер решает, что дело сделано.
    Живой прогон 2026-08-10 отрапортовал «ИТОГО вступлений: 1», хотя из игры
    не вышел ни один отряд: считалось по 'dispatched' из JoinActions. Считать
    можно только подтверждённые счётчиком «Отряд N/4» вступления."""
    eng = _mk_join_engine(FakeJoin(["dispatched"]), active=0)
    eng.one_iteration()
    assert eng.joins == 0                  # отрядов не прибавилось — не вступили

    ok = _mk_join_engine(FakeJoin(["dispatched"]), active=0, active_after=1)
    ok.one_iteration()
    assert ok.joins == 1

def test_join_confirmed_dispatch_resets_failure_counter():
    join = FakeJoin(["dispatched"])
    eng = _mk_join_engine(join, active=1, active_after=2)
    eng._no_progress = 2
    eng.one_iteration()
    assert eng._no_progress == 0

def test_join_no_calls_is_not_a_failure():
    join = FakeJoin(["no_calls"])
    eng = _mk_join_engine(join)
    assert eng.one_iteration() is None
    assert eng._no_progress == 0            # сборов нет — это не провал бота

def test_join_stops_after_repeated_failures():
    cfg_failures = Config().max_search_failures
    join = FakeJoin(["failed"] * cfg_failures)
    eng = _mk_join_engine(join)
    for _ in range(cfg_failures - 1):
        assert eng.one_iteration().type == 'join_assault'
    assert eng.one_iteration().type == 'stop'

def test_join_low_energy_stops():
    join = FakeJoin(["low_energy"])
    eng = _mk_join_engine(join)
    assert eng.one_iteration().type == 'stop'

def test_join_start_leaves_stock_unknown_until_read_from_game():
    """Ветка start() для join нужна ровно затем, чтобы режим не проваливался
    в «Поиск вора»: flasks остаётся None (склянки в этом режиме не при чём,
    читать их неоткуда и незачем). Лог обязан называть режим присоединения и
    НЕ обещать рефилл — рефилла тут нет, а первая строка живого лога врала
    человеку именно про него."""
    lines = []
    join = FakeJoin()
    eng = _mk_join_engine(join)
    eng.log = lines.append
    eng.start()
    assert eng.flasks is None
    assert any("присоединение" in m.lower() for m in lines)
    assert not any("рефилл" in m.lower() for m in lines)

# --- Режим «Поиск вора» ---

class ThiefFakeDriver:
    def __init__(self):
        self.taps = []
    def screenshot(self):
        return "frame"
    def tap(self, target):
        self.taps.append(tuple(target.center) if hasattr(target, "center") else tuple(target))
    def back(self):
        pass

class ThiefFakeVision:
    """Кадр один, ответы фиксированы: движок тут проверяется на решения,
    а не на распознавание — оно своё в tests/test_vision.py."""
    def __init__(self, squad="idle", leveled=(), energy=120):
        self.squad = squad
        self.leveled = list(leveled)
        self.energy = energy
    def squad_state(self, img):
        return self.squad
    def leveled_targets(self, img):
        return self.leveled
    def read_energy(self, img):
        return self.energy
    def classify_screen(self, img):
        return "world_map"          # по умолчанию помех поверх карты нет

class ThiefFakeActions:
    def close_preview(self):
        pass

class FakeThief:
    def __init__(self, search_result="searched", attack_result="dispatched",
                 wave_seconds=None, spend=0, stock=None):
        self.search_result = search_result
        self.attack_result = attack_result
        self.last_wave_seconds = wave_seconds
        self.flasks_used = 0
        self.last_flask_stock = None
        self._spend = spend          # сколько склянок «тратит» удар (см. FakeCorruption)
        self._stock = stock          # что «прочитано» в «В наличии: N»; None -> нечитаемо
        self.calls = []
    def search(self):
        self.calls.append("search")
        return self.search_result
    def attack(self, target, refill=False):
        self.calls.append(("attack", target.x, target.y, refill))
        if refill:
            self.flasks_used += self._spend
            if self._stock is not None:
                self.last_flask_stock = self._stock
                self._stock -= self._spend
        return self.attack_result

class FakeZoom:
    def __init__(self, ok=True, last_failure='stuck'):
        self.ok = ok
        self.last_failure = None if ok else last_failure
        self.calls = []
    def ensure(self, want):
        self.calls.append(want)
        return self.ok

def _thief_cfg(**over):
    cfg = Config()
    cfg.strategy = "thief"
    cfg.human_enabled = False        # без случайных пауз тест детерминирован
    cfg.thief_min_targets = 1        # по умолчанию БЬЁМ; ветку поиска тесты
    for k, v in over.items():        # включают явно, подняв порог
        setattr(cfg, k, v)
    return cfg

def _thief_engine(vision, thief=None, zoom=None, cfg=None, sleeps=None, cancel=None):
    eng = BotEngine(ThiefFakeDriver(), vision, ThiefFakeActions(),
                    cfg or _thief_cfg(), log=lambda m: None,
                    sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
                    thief=thief or FakeThief(), zoom=zoom or FakeZoom(),
                    cancel=cancel)
    eng.flasks = 500                 # выше порога: рефилл разрешён, стопа нет
    return eng

def test_thief_waits_while_squad_marching():
    """Гейт читается на ЗУМ-ИНЕ: виджета «Отряд» на отзуме нет."""
    v = ThiefFakeVision(squad="marching", leveled=[Target("mob", 5, 400, 900)])
    z = FakeZoom()
    eng = _thief_engine(v, zoom=z)
    assert eng.one_iteration() is None
    assert z.calls == ["close"]           # до отзума дело не дошло

def test_thief_attacks_nearest_level_five():
    """Уровень берётся из бейджа: цель ур.30 рядом с центром не трогаем."""
    v = ThiefFakeVision(leveled=[
        Target("mob", 5, 100, 100),       # далеко от центра
        Target("mob", 5, 540, 900),       # ближе к центру
        Target("mob", 30, 545, 905),      # ещё ближе, но не тот уровень
    ])
    t = FakeThief()
    eng = _thief_engine(v, thief=t)
    eng.one_iteration()
    assert ("attack", 540, 900, True) in t.calls

def test_thief_searches_when_too_few_targets():
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief()
    eng = _thief_engine(v, thief=t, cfg=_thief_cfg(thief_min_targets=3))
    eng.one_iteration()
    assert t.calls == ["search"]

def test_production_config_attacks_a_single_visible_thief():
    """Порог берётся из ПРОИЗВОДСТВЕННОГО конфига, а не из хелпера.

    Живьём (прогон 2, итерация 24) бот видел двух воров, одного ровно в
    центре, и всё равно уходил в меню за «Поиском» — заход стоит 21-24 с.
    Хелпер _thief_cfg ставит порог 1 сам, поэтому дефолт 3 не проверялся."""
    cfg = Config()
    cfg.strategy = "thief"
    cfg.human_enabled = False
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief()
    eng = _thief_engine(v, thief=t, cfg=cfg)
    eng.one_iteration()
    assert "search" not in t.calls
    assert ("attack", 540, 900, True) in t.calls

def test_thief_attacks_anyway_after_search_budget_spent():
    """Редкая волна не должна давать вечный цикл «ищу — мало — ищу» при
    живой цели перед носом."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief()
    eng = _thief_engine(v, thief=t,
                        cfg=_thief_cfg(thief_min_targets=3, thief_searches_per_wave=2))
    for _ in range(3):
        eng.one_iteration()
    assert t.calls.count("search") == 2
    assert ("attack", 540, 900, True) in t.calls

def test_thief_not_a_thief_is_not_a_failure():
    """Обычный моб ур.5 — ожидаемый исход неразличимых иконок, а не провал:
    иначе три подряд таких моба выключили бы бота на ровном месте."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief(attack_result="not_thief")
    eng = _thief_engine(v, thief=t)
    for _ in range(5):
        eng.one_iteration()
    assert eng._no_progress == 0
    assert len(eng.skip_targets) == 1     # цель помечена, второй раз не берём

def test_thief_stops_when_zoom_unfixable():
    """Первая осечка — ждём, лимит подряд — стоп. Молча работать на чужом
    зуме нельзя: детекция площадей врёт."""
    v = ThiefFakeVision()
    eng = _thief_engine(v, zoom=FakeZoom(ok=False))
    actions = [eng.one_iteration() for _ in range(eng.cfg.zoom_fail_limit)]
    assert actions[0] is None
    assert actions[-1].type == "stop"

class BannerVision(ThiefFakeVision):
    """Баннер закрыл якорь HUD: экран не опознан, зума не определить."""
    def __init__(self):
        super().__init__(squad="idle", leveled=[])
    def map_zoom(self, img):
        return "unknown"
    def classify_screen(self, img):
        return "unknown"

class ModalVision(ThiefFakeVision):
    """Поверх карты осталось СВОЁ превью: ожиданием не лечится, надо закрыть."""
    def __init__(self):
        super().__init__(squad="idle", leveled=[])
        self.closed = False
    def map_zoom(self, img):
        return "close" if self.closed else "unknown"
    def classify_screen(self, img):
        return "game_view" if self.closed else "thief_preview"

class ClosingActions:
    def __init__(self, vision):
        self.vision = vision
        self.closed = 0
    def close_preview(self):
        self.closed += 1
        self.vision.closed = True

def _zoom_engine(vision, zoom, actions=None, cfg=None, sleeps=None):
    eng = BotEngine(ThiefFakeDriver(), vision, actions or ThiefFakeActions(),
                    cfg or _thief_cfg(), log=lambda m: None,
                    sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
                    thief=FakeThief(), zoom=zoom)
    eng.flasks = 500
    return eng

def test_unrecognized_screen_is_waited_out_not_counted_as_broken_zoom():
    """Живьём бот встал за 6 с из-за баннера, закрывшего якорь HUD (замер:
    скор 0.364 при пороге 0.7). Баннер уходит сам — его надо пережидать, а
    не звать человека."""
    sleeps = []
    eng = _zoom_engine(BannerVision(),
                       FakeZoom(ok=False, last_failure='unknown_screen'),
                       sleeps=sleeps)
    for _ in range(Config().zoom_fail_limit):
        assert eng.one_iteration() is None          # ни одного стопа
    assert eng._zoom_fails == 0                     # это НЕ провал зума
    assert max(sleeps) >= Config().zoom_unknown_wait_s

def test_unrecognized_screen_eventually_gives_up():
    """Но и ждать вечно нельзя: терпение конечно, просто оно длиннее."""
    cfg = _thief_cfg(zoom_unknown_limit=2)
    eng = _zoom_engine(BannerVision(),
                       FakeZoom(ok=False, last_failure='unknown_screen'), cfg=cfg)
    assert eng.one_iteration() is None
    assert eng.one_iteration().type == 'stop'

def test_stuck_pinch_still_stops_after_the_old_limit():
    """Сломанный щипок — прежнее поведение, терпение тут ни при чём."""
    eng = _zoom_engine(ThiefFakeVision(squad="idle", leveled=[]),
                       FakeZoom(ok=False, last_failure='stuck'))
    for _ in range(Config().zoom_fail_limit - 1):
        assert eng.one_iteration() is None
    assert eng.one_iteration().type == 'stop'

def test_own_modal_is_closed_instead_of_waited_out():
    """Своё превью ожиданием не уйдёт — его закрывают. И это не провал зума:
    иначе три всплывших окна подряд выключали бы бота."""
    v = ModalVision()
    acts = ClosingActions(v)
    eng = _zoom_engine(v, FakeZoom(ok=False, last_failure='unknown_screen'),
                       actions=acts)
    assert eng.one_iteration() is None
    assert acts.closed == 1
    assert eng._zoom_fails == 0
    assert eng._zoom_unknowns == 0

class StuckModalVision(ThiefFakeVision):
    """Модалка НЕ закрывается: тап close_preview либо промахивается, либо
    игра зависла — classify_screen раз за разом называет ту же СВОЮ
    модалку. Ревью раунда 1 (Critical): без предела попыток бот молча
    крутится вечно, а сторож это не ловит — экран РАСПОЗНАН, просто не тот."""
    def __init__(self):
        super().__init__(squad="idle", leveled=[])
    def map_zoom(self, img):
        return "unknown"
    def classify_screen(self, img):
        return "thief_preview"

class CountingActions:
    """close_preview тапает раз за разом, но экран не откликается."""
    def __init__(self):
        self.closed = 0
    def close_preview(self):
        self.closed += 1

def test_unclosable_modal_eventually_stops():
    """У попыток закрыть СВОЮ модалку тоже есть предел: закрытие либо
    срабатывает сразу, либо не сработает вовсе (не помеха, которую
    пережидают) — вечно тапать по тому же месту нельзя."""
    v = StuckModalVision()
    acts = CountingActions()
    eng = _zoom_engine(v, FakeZoom(ok=False, last_failure='unknown_screen'),
                       actions=acts, cfg=_thief_cfg(modal_close_limit=3))
    actions = [eng.one_iteration() for _ in range(10)]
    assert any(a is not None and a.type == 'stop' for a in actions)

def test_thief_sleeps_until_next_wave():
    """Таймер волны 666 с -> спим столько, а не жмём «Поиск» вхолостую."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="no_wave", wave_seconds=666)
    sleeps = []
    eng = _thief_engine(v, thief=t, sleeps=sleeps)
    assert eng.one_iteration() is None
    assert max(sleeps) >= 600

def test_thief_sleeps_when_search_budget_spent_and_still_no_targets():
    """Critical (финальное ревью): бюджет «Поисков» исчерпан, целей всё ещё
    нет, а «Поиск» продолжает отвечать 'searched' — живьём 'no_wave' от
    игры ни разу не приходил, и полагаться на него как на единственный
    выход из цикла нельзя. Бот обязан заснуть сам, а не долбить «Поиск»
    вхолостую бесконечно (каждый заход — «Особое событие» + вкладка + два
    щипка, риск бана за одинаковый макро-цикл)."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="searched", wave_seconds=None)
    sleeps = []
    eng = _thief_engine(v, thief=t, sleeps=sleeps,
                        cfg=_thief_cfg(thief_min_targets=3, thief_searches_per_wave=2))
    for _ in range(2):
        eng.one_iteration()                  # исчерпываем бюджет «Поисков»
    assert t.calls.count("search") == 2
    action = eng.one_iteration()             # бюджет исчерпан, целей всё ещё нет
    assert action is None                    # не 'attack_mob' — итерация просто ждёт
    assert t.calls.count("search") == 2      # «Поиск» НЕ вызывали заново
    assert sleeps                            # бот заснул до следующей волны

# --- Регрессия: Стоп не должен считаться провалом (класс бага, который
# ревью в этом плане уже ловило дважды в src/thief.py — коммиты 33cb819 и
# 1a54392). Единственный тест на отказ моделирует «шаг сам не удался»
# (FakeThief(...="failed") / FakeZoom(ok=False)) — это ДРУГОЕ, чем «шаг
# прервали Стопом», и первое не доказывает отсутствие второго. ---

class StoppingZoom:
    """Как FakeZoom(ok=False), но имитирует то, что видит ZoomKeeper внутри
    лестницы щипков: Стоп ловится ПОСЕРЕДИНЕ приведения зума, и он же вернул
    False, не тапнув (см. tests/test_thief.py::StoppingZoom, тот же приём)."""
    def __init__(self, cancel):
        self.cancel = cancel
        self.calls = []
    def ensure(self, want):
        self.calls.append(want)
        self.cancel.set()
        return False

def test_thief_zoom_stop_is_not_a_zoom_failure():
    """zoom.ensure() сам проверяет отмену внутри лестницы щипков и при
    Стопе тоже отдаёт False, не тапнув — снаружи это неотличимо от
    настоящей невозможности привестись. Движок обязан отличить их сам:
    иначе Стоп попадёт в счётчик поломок зума, а лог соврёт про причину.

    Заодно Minor 2 ревью раунда 1: молчаливая остановка по Стопу читалась
    бы человеком как «бот сам умер» — лог обязан назвать причину."""
    cancel = Cancel()
    eng = _thief_engine(ThiefFakeVision(), zoom=StoppingZoom(cancel), cancel=cancel)
    lines = []
    eng.log = lines.append
    action = eng.one_iteration()
    assert action is not None and action.type == "stop"
    assert eng._zoom_fails == 0            # не «зум не приводится», а Стоп
    assert any("стоп" in m.lower() for m in lines)   # причина не осталась в тишине

class FlakySkullZoom:
    """Зум-ин («close») приводится штатно каждый раз, зум для выбора цели
    («skull») — никогда. Регрессия на Important A ревью раунда 1: счётчик
    _zoom_fails раньше обнулялся ПЕРВЫМ гейтом («close» всегда успешен) и
    никогда не доходил до zoom_fail_limit, хотя второй гейт стабильно рвётся —
    бот вечно щипал бы туда-сюда и молчал вместо честной остановки."""
    def __init__(self):
        self.calls = []
    def ensure(self, want):
        self.calls.append(want)
        return want == "close"

def test_thief_zoom_counter_survives_a_working_first_gate():
    """close приводится штатно на КАЖДОЙ итерации, skull — никогда. Лимит
    zoom_fail_limit обязан быть достигнут, а не растворяться в успехе
    первого гейта (см. FlakySkullZoom)."""
    v = ThiefFakeVision()
    z = FlakySkullZoom()
    eng = _thief_engine(v, zoom=z)
    actions = [eng.one_iteration() for _ in range(eng.cfg.zoom_fail_limit)]
    assert actions[-1] is not None and actions[-1].type == "stop"

def test_thief_attack_stopped_is_not_a_failure():
    """thief.attack() вернул 'stopped' (кнопка нажата ПОСЕРЕДИНЕ захода,
    не сам заход не удался) -> движок обязан остановиться, не наращивая
    счётчик провалов отправки."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief(attack_result="stopped")
    eng = _thief_engine(v, thief=t)
    action = eng.one_iteration()
    assert action is not None and action.type == "stop"
    assert eng._no_progress == 0

def test_thief_search_stopped_is_not_a_failure():
    """thief.search() вернул 'stopped' -> тоже стоп без наращивания
    счётчика провалов («Поиск» прерван Стопом, а не сам не получился)."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="stopped")
    eng = _thief_engine(v, thief=t)
    action = eng.one_iteration()
    assert action is not None and action.type == "stop"
    assert eng._no_progress == 0

# --- Minor 1 ревью раунда 1: сброс _searches и skip_targets.clear() не был
# покрыт НИ ОДНИМ тестом — мутационная проверка ревьюера убрала обе строки
# без единого красного теста. По одному тесту на каждую из четырёх точек
# сброса (их две пары: перед отправкой и в ветке «волна кончилась»). ---

def test_thief_search_budget_resets_after_a_dispatch():
    """Счётчик «Поисков подряд» обязан сброситься не только когда волна
    кончилась (no_wave/no_event), но и после обычной отправки — иначе
    следующая волна с тем же малым числом целей начинается уже с
    подорванным бюджетом «Поиска», доставшимся от предыдущей."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief()
    eng = _thief_engine(v, thief=t,
                        cfg=_thief_cfg(thief_min_targets=3, thief_searches_per_wave=2))
    for _ in range(3):     # 2 «Поиска» исчерпывают бюджет, 3-й бьёт цель
        eng.one_iteration()
    assert eng._searches == 0

def test_thief_search_budget_resets_when_wave_ends():
    """То же самое, но для ветки «волна кончилась»: бюджет «Поисков» не
    должен переползать в следующую волну частично исчерпанным."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="searched")
    eng = _thief_engine(v, thief=t, cfg=_thief_cfg(thief_min_targets=3))
    eng.one_iteration()                    # один «Поиск» -> searches=1
    assert eng._searches == 1
    t.search_result = "no_wave"
    t.last_wave_seconds = 100
    eng.one_iteration()                    # волна кончилась -> сон
    assert eng._searches == 0

def test_thief_skip_targets_reset_after_a_successful_search():
    """«Поиск» переносит камеру — старые пропуски по экранным координатам
    больше ничего не значат. Без сброса бот пропустил бы нового вора,
    попавшего в старую ячейку сетки."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="searched")
    eng = _thief_engine(v, thief=t, cfg=_thief_cfg(thief_min_targets=3))
    eng.skip_targets.add(("mob", 27, 45))   # старая метка, до «Поиска»
    eng.one_iteration()
    assert eng.skip_targets == set()

def test_thief_skip_targets_reset_when_wave_ends():
    """То же самое для ветки «волна кончилась»: старые пропуски не должны
    пережить переход к следующей волне."""
    v = ThiefFakeVision(leveled=[])
    t = FakeThief(search_result="no_wave", wave_seconds=100)
    eng = _thief_engine(v, thief=t, cfg=_thief_cfg(thief_min_targets=3))
    eng.skip_targets.add(("mob", 3, 4))
    eng.one_iteration()
    assert eng.skip_targets == set()

# --- Important (финальное ревью): порог склянок молча переставал действовать,
# если «В наличии: N» после удара не прочлось — ThiefActions.flasks_used было
# объявлено и не читалось никем. Тот же приём, что уже есть у скверны
# (test_unreadable_stock_is_logged_not_silently_ignored). ---

def test_thief_unreadable_stock_is_logged_not_silently_ignored():
    """Склянки потрачены (flasks_used вырос), но «В наличии: N» не
    прочиталось (last_flask_stock остался None) -> порог перестаёт
    действовать, и молчать об этом нельзя: refill = self.flasks is None
    иначе разрешил бы рефилл навсегда."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief(spend=2, stock=None)
    eng = _thief_engine(v, thief=t)
    eng.flasks = None            # остаток пока неизвестен (как после старта)
    lines = []
    eng.log = lines.append
    eng.one_iteration()
    assert any("прочитать не удалось" in s for s in lines)

def test_thief_subtracts_spent_when_stock_unreadable_but_known():
    """Остаток был известен (500), стока «В наличии» не прочлось -> считаем
    локально (500 - потрачено), а не остаёмся слепы к порогу."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief(spend=2, stock=None)
    eng = _thief_engine(v, thief=t)          # eng.flasks == 500 (см. _thief_engine)
    eng.one_iteration()
    assert eng.flasks == 498

def test_thief_prefers_read_stock_over_local_count():
    """Прочитанное «В наличии: N» точнее локального счёта — как у скверны."""
    v = ThiefFakeVision(leveled=[Target("mob", 5, 540, 900)])
    t = FakeThief(spend=2, stock=273)
    eng = _thief_engine(v, thief=t)          # локальный учёт (500) был бы неверен
    eng.one_iteration()
    assert eng.flasks == 273
