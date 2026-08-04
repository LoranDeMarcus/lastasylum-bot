import random
from config import Config
from src.driver import jitter, AdbDriver
from src.models import Box
from src.human import Human

def test_back_sends_keyevent_back():
    """BACK закрывает случайно открытый диалог -> вид снова чистый."""
    drv = AdbDriver(Config())
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)
    drv.back()
    assert calls == [("shell", "input", "keyevent", "4")]

def test_jitter_within_bounds():
    rng = random.Random(42)
    for _ in range(100):
        x, y = jitter(500, 800, px=4, rng=rng)
        assert 496 <= x <= 504
        assert 796 <= y <= 804

def test_jitter_zero_px_is_identity():
    rng = random.Random(0)
    assert jitter(10, 20, px=0, rng=rng) == (10, 20)

def test_tap_accepts_box_and_tuple():
    """tap принимает и Box, и голый кортеж — вторые остаются у tools/*."""
    drv = AdbDriver(Config(jitter_px=0))
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)

    drv.tap(Box(500, 800, 200, 60))
    drv.tap((10, 20))

    assert calls == [("shell", "input", "tap", "500", "800"),
                     ("shell", "input", "tap", "10", "20")]

def test_tap_box_uses_named_size_and_falls_back_to_default():
    cfg = Config()
    known = cfg.tap_box("corruption_search", (548, 1785))
    unknown = cfg.tap_box("такой_кнопки_нет", (100, 200))

    assert known.center == (548, 1785)
    assert (known.w, known.h) == cfg.tap_sizes["corruption_search"]
    assert (unknown.w, unknown.h) == cfg.tap_size_default

def _drv_with_human(cfg, seed=5):
    drv = AdbDriver(cfg, human=Human(cfg, rng=random.Random(seed)))
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)
    return drv, calls

def test_taps_spread_inside_button_when_human_attached():
    cfg = Config()
    drv, calls = _drv_with_human(cfg)
    box = Box(548, 1785, 300, 88)
    for _ in range(50):
        drv.tap(box)
    xs = {int(c[3]) for c in calls}
    assert len(xs) > 5                                  # не одна выверенная точка
    assert all(473 <= int(c[3]) <= 623 for c in calls)  # внутри центральных 50%
    assert all(1763 <= int(c[4]) <= 1807 for c in calls)

def test_human_disabled_falls_back_to_center():
    cfg = Config(human_enabled=False, jitter_px=0)
    drv, calls = _drv_with_human(cfg)
    drv.tap(Box(100, 200, 300, 88))
    assert calls == [("shell", "input", "tap", "100", "200")]

def test_variable_hold_uses_swipe_with_equal_coords():
    """input tap даёт нулевую длительность нажатия — машинный признак.
    Переменное нажатие делается swipe'ом в ту же точку."""
    cfg = Config(human_tap_hold=True, tap_inset=0.0)
    drv, calls = _drv_with_human(cfg)
    drv.tap(Box(500, 800, 200, 60))
    cmd = calls[0]
    assert cmd[:2] == ("shell", "input") and cmd[2] == "swipe"
    assert cmd[3:5] == ("500", "800") and cmd[5:7] == ("500", "800")
    assert cfg.tap_hold_ms[0] <= int(cmd[7]) <= cfg.tap_hold_ms[1]
