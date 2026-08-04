import random
from config import Config
from src.driver import jitter, AdbDriver
from src.models import Box

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
