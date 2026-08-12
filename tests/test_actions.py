from config import Config
from src.models import Target
from src.actions import Actions

class FakeDriver:
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
        self.taps.append(tuple(target.center) if hasattr(target, "center") else tuple(target))
    def swipe(self, *a, **k):
        pass
    def back(self):
        self.backs += 1

class FakeVision:
    """Кнопки {frame:{name:(x,y)}}; панель {frame:'attack'|'assault'};
    прогноз боя {frame:'win'|'lose'}."""
    def __init__(self, buttons_by_frame, panel_by_frame=None, win_by_frame=None, flasks=251):
        self.buttons_by_frame = buttons_by_frame
        self.panel_by_frame = panel_by_frame or {}
        self.win_by_frame = win_by_frame or {}
        self._flasks = flasks
    def find_button(self, img, name):
        return self.buttons_by_frame.get(img, {}).get(name)
    def panel_action(self, img):
        return self.panel_by_frame.get(img)
    def win_prediction(self, img):
        return self.win_by_frame.get(img)
    def read_flasks(self, img):
        return self._flasks
    def squad_slot(self, n):
        return (100 + n, 200)   # детерминированные координаты слота

def test_attack_mob_sequence_selects_squad_2():
    cfg = Config()
    frames = ["panel", "panel2", "preview", "preview2"]
    drv = FakeDriver(frames)
    vis = FakeVision(
        buttons_by_frame={
            "panel2": {"attack": (400, 900)},
            "preview": {"dispatch": (450, 1400)},
            "preview2": {"dispatch": (450, 1400)},
        },
        panel_by_frame={"panel": "attack"},
    )
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    res = act.attack_mob(Target('mob', 5, 300, 300))
    assert res == "dispatched"
    assert (300, 300) in drv.taps                     # тап по мобу
    assert (400, 900) in drv.taps                     # кнопка «Атака»
    assert vis.squad_slot(cfg.mob_squad) in drv.taps  # карточка отряда 2
    assert (450, 1400) in drv.taps                    # «Отправиться»

def test_attack_mob_missed_returns_missed():
    cfg = Config()
    drv = FakeDriver(["map"])          # панель не откроется -> промах
    vis = FakeVision(buttons_by_frame={}, panel_by_frame={})
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    res = act.attack_mob(Target('mob', 5, 300, 300))
    assert res == "missed"
    assert (300, 300) in drv.taps      # тап был, но панели нет

def test_attack_mob_wrong_panel_when_boss():
    cfg = Config()
    drv = FakeDriver(["boss_panel"])
    vis = FakeVision(buttons_by_frame={}, panel_by_frame={"boss_panel": "assault"})
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    res = act.attack_mob(Target('mob', 5, 300, 300))
    assert res == "wrong_panel"

def test_assault_boss_dispatches_on_win():
    cfg = Config()
    frames = ["panel", "after", "preview", "pred", "preview2"]
    drv = FakeDriver(frames)
    vis = FakeVision(
        buttons_by_frame={
            "after": {"assault": (500, 1290)},
            "preview": {"start_assault": (535, 1340)},
            "preview2": {"start_assault": (535, 1340)},
        },
        panel_by_frame={"panel": "assault"},
        win_by_frame={"pred": "win"},
    )
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    res = act.assault_boss(Target('boss', 0, 400, 400))
    assert res == "dispatched"
    assert vis.squad_slot(cfg.boss_squad) in drv.taps   # выбран отряд 1
    assert (535, 1340) in drv.taps                       # «Начать Штурм»

def test_assault_boss_skips_when_unwinnable():
    cfg = Config()
    frames = ["panel", "after", "preview", "pred"]
    drv = FakeDriver(frames)
    vis = FakeVision(
        buttons_by_frame={
            "after": {"assault": (500, 1290)},
            "preview": {"start_assault": (535, 1340)},
        },
        panel_by_frame={"panel": "assault"},
        win_by_frame={"pred": "lose"},
    )
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    res = act.assault_boss(Target('boss', 0, 400, 400))
    assert res == "skip_unwinnable"
    assert cfg.preview_close_xy in drv.taps               # закрыли превью
    assert vis.squad_slot(cfg.boss_squad) not in drv.taps # отряд НЕ выбирали
    assert (535, 1340) not in drv.taps                    # штурм НЕ начинали

def test_refill_returns_remaining_flasks():
    cfg = Config()
    frames = ["energy", "energy2", "energy3"]
    drv = FakeDriver(frames)
    vis = FakeVision(
        buttons_by_frame={
            "energy": {"flask_use": (480, 900)},
            "energy3": {"energy_close": (560, 240)},
        },
        flasks=200,
    )
    act = Actions(drv, vis, cfg, sleep=lambda *_: None)
    left = act.refill_energy()
    assert left == 200
    assert cfg.energy_open_xy in drv.taps    # тап по «+»
    assert cfg.flask_use_xy in drv.taps      # фиксированная координата фиолетовой +50
