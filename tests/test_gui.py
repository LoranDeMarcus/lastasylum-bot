# tests/test_gui.py
import time
import threading
from config import Config
from src.gui import BotController, apply_flask_threshold, apply_strategy

class DummyEngine:
    def __init__(self):
        self.ran = threading.Event()
    def run(self, stop_event):
        self.ran.set()
        while not stop_event.is_set():
            time.sleep(0.01)
        return 'stopped_by_user'

def test_controller_start_and_stop():
    eng = DummyEngine()
    ctrl = BotController(lambda cancel: eng)
    ctrl.start()
    assert eng.ran.wait(timeout=1.0)
    assert ctrl.is_running()
    ctrl.stop()
    time.sleep(0.1)
    assert not ctrl.is_running()

def test_controller_double_start_is_noop():
    eng = DummyEngine()
    ctrl = BotController(lambda cancel: eng)
    ctrl.start()
    ctrl.start()   # не должен падать/плодить потоки
    assert ctrl.is_running()
    ctrl.stop()

def test_controller_gives_factory_the_same_cancel_it_stops():
    """Фабрика собирает компоненты вокруг того же объекта, который взводит
    кнопка Стоп, — иначе паузы просыпаться не будут."""
    seen = []
    eng = DummyEngine()
    def factory(cancel):
        seen.append(cancel)
        return eng
    ctrl = BotController(factory)
    ctrl.start()
    assert eng.ran.wait(timeout=1.0)
    ctrl.stop()
    assert len(seen) == 1 and seen[0].is_set()

def test_controller_clears_cancel_on_restart():
    """Второй Start не должен стартовать с уже взведённым Стопом."""
    eng = DummyEngine()
    seen = []
    ctrl = BotController(lambda cancel: seen.append(cancel) or eng)
    ctrl.start()
    ctrl.stop()
    time.sleep(0.1)
    eng.ran.clear()
    ctrl.start()
    assert seen[-1].is_set() is False
    ctrl.stop()

# --- Поле «Мин. остаток склянок» ---

def test_apply_flask_threshold_sets_value():
    cfg = Config()
    assert apply_flask_threshold(cfg, "120") == 120
    assert cfg.flask_stop_threshold == 120

def test_apply_flask_threshold_ignores_garbage():
    cfg = Config()
    before = cfg.flask_stop_threshold
    assert apply_flask_threshold(cfg, "абв") == before
    assert cfg.flask_stop_threshold == before

def test_apply_flask_threshold_ignores_negative():
    cfg = Config()
    before = cfg.flask_stop_threshold
    assert apply_flask_threshold(cfg, "-5") == before
    assert cfg.flask_stop_threshold == before

def test_apply_flask_threshold_ignores_empty():
    cfg = Config()
    before = cfg.flask_stop_threshold
    assert apply_flask_threshold(cfg, "") == before
    assert cfg.flask_stop_threshold == before

def test_apply_flask_threshold_accepts_zero_and_spaces():
    cfg = Config()
    assert apply_flask_threshold(cfg, "  0 ") == 0
    assert cfg.flask_stop_threshold == 0

# --- Переключатель режима (corruption / join) ---

def test_apply_strategy_switches_mode():
    cfg = Config()
    assert apply_strategy(cfg, "join") == "join"
    assert cfg.strategy == "join"

def test_apply_strategy_ignores_unknown():
    cfg = Config()
    cfg.strategy = "corruption"
    assert apply_strategy(cfg, "чепуха") == "corruption"
    assert cfg.strategy == "corruption"

def test_apply_strategy_accepts_thief():
    cfg = Config()
    assert apply_strategy(cfg, "thief") == "thief"
    assert cfg.strategy == "thief"

def test_apply_strategy_ignores_unknown_mode():
    """Лучше остаться в прежнем режиме, чем уронить движок чужой веткой."""
    cfg = Config()
    cfg.strategy = "thief"
    assert apply_strategy(cfg, "нет такого") == "thief"
