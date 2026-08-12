from config import Config
from src.cancel import Cancel
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

class StoppingZoom:
    """Имитирует ZoomKeeper.ensure, прерванный Стопом ПОСЕРЕДИНЕ лестницы
    щипков (щипки идут с паузами ~1.3 с — окно для нажатия Стопа реальное).
    ZoomKeeper сам проверяет отмену и возвращает False, НЕ ПОТОМУ что зум не
    удался, а потому что дальше тапать незачем — этот исход нельзя путать
    с настоящим провалом приведения зума."""
    def __init__(self, cancel):
        self.cancel = cancel
    def ensure(self, want):
        self.cancel.set()
        return False

def test_search_stopped_during_zoom_is_not_a_failure():
    """Стоп во время приведения зума -> 'stopped', а не 'failed'.

    Иначе вызывающий код считает провалы подряд и после N решит, что
    сломалась игра, хотя на самом деле человек нажал кнопку — лог при
    этом ещё и соврёт про причину («не смог привести зум»)."""
    cancel = Cancel()
    v = FakeVision()
    driver = FakeDriver(["map"])
    t = ThiefActions(driver, v, FakeActions(), _cfg(), StoppingZoom(cancel),
                     log=lambda m: None, sleep=lambda s: None, cancel=cancel)
    assert t.search() == "stopped"
    assert driver.taps == []            # вслепую не тапаем

def test_search_makes_no_taps_when_already_stopped():
    """Стоп нажат до захода — ни одного тапа."""
    v = FakeVision()
    cancel = Cancel()
    cancel.set()
    driver = FakeDriver(["map"])
    t = ThiefActions(driver, v, FakeActions(), _cfg(), FakeZoom(),
                     log=lambda m: None, sleep=lambda s: None, cancel=cancel)
    assert t.search() == "stopped"
    assert driver.taps == []

def test_search_aborts_mid_flow_without_further_taps():
    """Стоп посреди захода: экран оставляем как есть, но больше не тапаем.

    Между двумя паузами бот успевает тапнуть, а после Стопа тапать уже
    незачем — отмена проверяется ПЕРЕД каждым тапом, не только между
    паузами (см. _wait_tab)."""
    v = FakeVision(tab_by_frame={"tab": True, "map": False},
                   buttons_by_frame={("tab", "thief_search"): Box(305, 1795, 400, 88)})
    cancel = Cancel()
    driver = FakeDriver(["map", "tab", "tab", "map"])
    t = ThiefActions(driver, v, FakeActions(), _cfg(), FakeZoom(),
                     log=lambda m: None, sleep=lambda s: None, cancel=cancel)
    orig_tap = driver.tap
    def tap_then_stop(target):
        orig_tap(target)
        cancel.set()                    # Стоп сразу после первого тапа
    driver.tap = tap_then_stop

    assert t.search() == "stopped"
    assert len(driver.taps) == 1        # второго тапа не было
    assert driver.backs == 0            # и «прибираться» тоже не просили

def test_wait_loops_give_up_on_stop():
    """Цикл ожидания вкладки не должен докручивать таймаут после Стопа."""
    driver = FakeDriver(["map"])
    v = FakeVision()
    cancel = Cancel()
    cancel.set()
    t = ThiefActions(driver, v, FakeActions(), _cfg(), FakeZoom(),
                     log=lambda m: None, sleep=lambda s: None, cancel=cancel)
    assert t._wait_tab() is False
    assert driver.i <= 1                # максимум один кадр, а не весь таймаут

def test_search_finds_tab_but_no_search_button_is_failure():
    """Вкладка «Поиск вора» открылась, но кнопки «Поиск» на ней нет —
    отдельный провал от «вкладки нет вообще» (no_event): вкладку-то нашли,
    просто на ней не оказалось ожидаемой кнопки (вёрстка поехала)."""
    v = FakeVision(tab_by_frame={"tab": True, "map": False})
    t, d = _thief(["map", "tab", "tab", "map"], v)
    assert t.search() == "failed"
    assert d.backs == 1                 # прибрались через _abort -> safe_back

def test_search_tab_found_by_template_but_never_opens_is_failure():
    """Вкладка «Поиск вора» находится шаблоном в строке вкладок и тапается,
    но подтверждения открытия так и не пришло — третий отдельный провал:
    не «вкладки нет» (её нашли) и не «кнопки Поиск нет» (до неё флоу
    не доходит, потому что вкладка так и не подтвердилась)."""
    v = FakeVision(buttons_by_frame={("map", "thief_tab"): Box(450, 205, 240, 90)})
    t, d = _thief(["map", "map", "map"], v)
    assert t.search() == "failed"
    assert d.backs == 1
