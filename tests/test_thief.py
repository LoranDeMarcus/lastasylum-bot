from config import Config
from src.models import Box
from src.thief import ThiefActions

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
        self.taps.append(tuple(target.center) if hasattr(target, "center") else tuple(target))
    def back(self):
        self.backs += 1

class FakeVision:
    def __init__(self, tab_by_frame=None, buttons_by_frame=None,
                 wave_by_frame=None, zoom_by_frame=None):
        self.tab_by_frame = tab_by_frame or {}
        self.buttons_by_frame = buttons_by_frame or {}
        self.wave_by_frame = wave_by_frame or {}
        self.zoom_by_frame = zoom_by_frame or {}
    def thief_tab_open(self, img):
        return self.tab_by_frame.get(img, False)
    def find_button(self, img, name):
        return self.buttons_by_frame.get((img, name))
    def wave_seconds(self, img):
        return self.wave_by_frame.get(img)
    def map_zoom(self, img):
        return self.zoom_by_frame.get(img, "close")
    def exit_dialog_open(self, img):
        return False
    def thief_panel(self, img):
        return True
    def squad_slot(self, n):
        return Config().squad_slots[n]

class FakeZoom:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []
    def ensure(self, want):
        self.calls.append(want)
        return self.ok

class FakeActions:
    def __init__(self):
        self.closed = 0
    def close_preview(self):
        self.closed += 1

def _cfg():
    cfg = Config()
    cfg.human_enabled = False        # без случайных пауз тест детерминирован
    return cfg

def _thief(frames, vision, zoom=None, cfg=None):
    cfg = cfg or _cfg()
    driver = FakeDriver(frames)
    return ThiefActions(driver, vision, FakeActions(), cfg, zoom or FakeZoom(),
                        log=lambda m: None, sleep=lambda s: None), driver

def test_search_opens_tab_and_taps_search():
    """Окно закрылось после «Поиска» -> камера уехала к вору."""
    v = FakeVision(tab_by_frame={"tab": True, "map": False},
                   buttons_by_frame={("tab", "thief_search"): Box(305, 1795, 400, 88)})
    t, d = _thief(["map", "tab", "tab", "map"], v)
    assert t.search() == "searched"
    assert (305, 1795) in d.taps

def test_search_without_tab_is_no_event():
    """Вкладки нет — событие кончилось или уехало за край. Не провал."""
    v = FakeVision(tab_by_frame={"map": False})
    t, d = _thief(["map", "map", "map", "map"], v)
    assert t.search() == "no_event"
    assert d.backs == 1                 # прибрались, а не бросили окно открытым

def test_search_that_leaves_window_open_means_wave_done():
    """Окно не закрылось -> «Поиску» некого искать, волна выбита."""
    v = FakeVision(tab_by_frame={"tab": True},
                   buttons_by_frame={("tab", "thief_search"): Box(305, 1795, 400, 88)},
                   wave_by_frame={"tab": 666})
    t, d = _thief(["map", "tab", "tab", "tab"], v)
    assert t.search() == "no_wave"
    assert t.last_wave_seconds == 666

def test_search_needs_close_zoom_first():
    """Кнопка «Особое событие» видна только на зум-ине."""
    v = FakeVision(tab_by_frame={"tab": True},
                   buttons_by_frame={("tab", "thief_search"): Box(305, 1795, 400, 88)})
    z = FakeZoom()
    t, d = _thief(["map", "tab", "tab", "map"], v, zoom=z)
    t.search()
    assert z.calls[0] == "close"

def test_search_fails_when_zoom_fails():
    v = FakeVision()
    t, d = _thief(["map"], v, zoom=FakeZoom(ok=False))
    assert t.search() == "failed"
    assert d.taps == []                 # вслепую не тапаем
