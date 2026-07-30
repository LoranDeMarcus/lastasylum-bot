import random
from config import Config
from src.driver import jitter, AdbDriver

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
