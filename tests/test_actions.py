from config import Config
from src.models import Target
from src.actions import Actions

class FakeDriver:
    def __init__(self, frames):
        self._frames = frames
        self.i = 0
        self.taps = []
    def screenshot(self):
        f = self._frames[min(self.i, len(self._frames) - 1)]
        self.i += 1
        return f
    def tap(self, x, y):
        self.taps.append((x, y))
    def swipe(self, *a, **k):
        pass

class FakeVision:
    """Возвращает координаты кнопок по сценарию {frame_id: {name:(x,y)}}."""
    def __init__(self, buttons_by_frame, flasks=251):
        self.buttons_by_frame = buttons_by_frame
        self._flasks = flasks
        self.squad_taps = []
    def find_button(self, img, name):
        return self.buttons_by_frame.get(img, {}).get(name)
    def read_flasks(self, img):
        return self._flasks
    def squad_slot(self, n):
        return (100 + n, 200)   # детерминированные координаты слота

def test_attack_mob_sequence_selects_squad_2():
    cfg = Config()
    # кадры-идентификаторы (строки как «изображения»)
    frames = ["map", "panel", "preview", "map2"]
    drv = FakeDriver(frames)
    vis = FakeVision({
        "panel": {"attack": (400, 900)},
        "preview": {"dispatch": (450, 1400)},
    })
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    ok = act.attack_mob(Target('mob', 5, 300, 300))
    assert ok is True
    # тапнули моба, кнопку атаки, слот отряда 2, кнопку отправки
    assert (300, 300) in drv.taps
    assert (400, 900) in drv.taps
    assert vis.squad_slot(cfg.mob_squad) in drv.taps
    assert (450, 1400) in drv.taps

def test_refill_returns_remaining_flasks():
    cfg = Config()
    frames = ["map", "energy", "map2"]
    drv = FakeDriver(frames)
    vis = FakeVision({
        "map": {"energy_cross": (50, 950)},
        "energy": {"flask_use": (480, 900), "energy_close": (560, 240)},
    }, flasks=200)
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    left = act.refill_energy()
    assert left == 200
    assert (480, 900) in drv.taps    # нажали «Использовать»
