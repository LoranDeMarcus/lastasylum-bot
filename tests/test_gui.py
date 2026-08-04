# tests/test_gui.py
import time
import threading
from config import Config
from src.gui import BotController, apply_flask_threshold

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
    ctrl = BotController(lambda: eng)
    ctrl.start()
    assert eng.ran.wait(timeout=1.0)
    assert ctrl.is_running()
    ctrl.stop()
    time.sleep(0.1)
    assert not ctrl.is_running()

def test_controller_double_start_is_noop():
    eng = DummyEngine()
    ctrl = BotController(lambda: eng)
    ctrl.start()
    ctrl.start()   # не должен падать/плодить потоки
    assert ctrl.is_running()
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
