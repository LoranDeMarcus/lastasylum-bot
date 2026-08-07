from config import Config
from src.cancel import Cancel
from src.watchdog import Watchdog, safe_back

class FakeDriver:
    """Кадры выдаются по очереди; последний повторяется."""
    def __init__(self, frames):
        self._frames = frames
        self.i = 0
        self.taps = []
        self.backs = 0
    def screenshot(self):
        f = self._frames[min(self.i, len(self._frames) - 1)]
        self.i += 1
        return f
    def tap(self, target):
        self.taps.append(target)
    def back(self):
        self.backs += 1

class FakeVision:
    def __init__(self, by_frame, exit_frames=()):
        self.by_frame = by_frame
        self.exit_frames = set(exit_frames)
    def classify_screen(self, img):
        return self.by_frame.get(img, 'unknown')
    def exit_dialog_open(self, img):
        return img in self.exit_frames
    def find_button(self, img, name):
        return None

def _wd(driver, vision, cfg=None, saved=None, cancel=None):
    cfg = cfg or Config()
    def save(path, img):
        if saved is not None:
            saved.append((path, img))
    return Watchdog(driver, vision, cfg, log=lambda m: None, sleep=lambda s: None,
                    now=lambda: 1754300000.0, save=save, beep=lambda: None,
                    cancel=cancel)

def test_known_screen_passes_without_waiting_or_tapping():
    drv = FakeDriver(["map"])
    wd = _wd(drv, FakeVision({"map": "game_view"}))
    assert wd.check() == 'ok'
    assert drv.taps == [] and drv.backs == 0

def test_transient_unknown_recovers_without_back():
    """Реклама/подарок/анимация уходят сами — BACK для этого не нужен."""
    drv = FakeDriver(["ad", "ad", "map"])
    wd = _wd(drv, FakeVision({"map": "game_view"}))
    assert wd.check() == 'recovered'
    assert drv.backs == 0 and drv.taps == []

def test_persistent_unknown_tries_back_once_then_stops():
    drv = FakeDriver(["чужое"])
    saved = []
    cfg = Config(watchdog_action="stop")
    wd = _wd(drv, FakeVision({}), cfg=cfg, saved=saved)
    assert wd.check() == 'stop'
    assert drv.backs == 1          # ровно один спасательный BACK
    assert len(saved) == 1         # кадр аномалии сохранён
    assert saved[0][0].startswith(cfg.watchdog_dir)

def test_log_mode_saves_frame_but_does_not_stop():
    drv = FakeDriver(["чужое"])
    saved = []
    wd = _wd(drv, FakeVision({}), cfg=Config(watchdog_action="log"), saved=saved)
    assert wd.check() == 'ok'
    assert len(saved) == 1

def test_disabled_watchdog_is_a_noop():
    drv = FakeDriver(["чужое"])
    wd = _wd(drv, FakeVision({}), cfg=Config(watchdog_enabled=False))
    assert wd.check() == 'ok'
    assert drv.backs == 0

def test_safe_back_cancels_exit_dialog():
    """BACK на чистой карте открывает «Выйти из игры?» — если это проглядеть,
    следующий слепой тап подтвердит выход."""
    drv = FakeDriver(["exit"])
    vis = FakeVision({}, exit_frames=["exit"])
    cfg = Config()
    safe_back(drv, vis, cfg, log=lambda m: None, sleep=lambda s: None)
    assert drv.backs == 1
    assert drv.taps == [cfg.tap_box("exit_cancel", cfg.exit_cancel_xy)]

# --- Возврат из базы на карту ---

def test_base_view_taps_world_button_and_continues():
    """База — не аномалия: жмём «Мир» и работаем дальше, без скрина и звука."""
    drv = FakeDriver(["база", "карта"])
    saved = []
    cfg = Config(watchdog_action="stop")
    wd = _wd(drv, FakeVision({"база": "base_view", "карта": "game_view"}),
             cfg=cfg, saved=saved)
    assert wd.check() == 'recovered'
    assert len(drv.taps) == 1
    assert drv.taps[0].center == cfg.world_button_xy
    assert saved == []            # кадр не сохраняли: это не аномалия

def test_base_view_that_never_leaves_becomes_an_alarm():
    drv = FakeDriver(["база"])
    saved = []
    cfg = Config(watchdog_action="stop")
    wd = _wd(drv, FakeVision({"база": "base_view"}), cfg=cfg, saved=saved)
    assert wd.check() == 'stop'
    assert len(drv.taps) == cfg.world_button_attempts
    assert len(saved) == 1

# --- Взаимодействие со Стопом ---

def test_stopped_watchdog_never_taps():
    """Сторож ждёт 12 с и жмёт BACK. После Стопа ни того, ни другого."""
    drv = FakeDriver(["чужое"])
    cancel = Cancel()
    cancel.set()
    wd = _wd(drv, FakeVision({}), cfg=Config(watchdog_action="stop"), cancel=cancel)
    assert wd.check() == 'ok'
    assert drv.backs == 0 and drv.taps == []

def test_stopped_watchdog_does_not_leave_base():
    drv = FakeDriver(["база"])
    cancel = Cancel()
    cancel.set()
    wd = _wd(drv, FakeVision({"база": "base_view"}), cancel=cancel)
    assert wd.check() == 'ok'
    assert drv.taps == []
