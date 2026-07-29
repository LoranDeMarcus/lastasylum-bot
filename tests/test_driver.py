import random
from src.driver import jitter

def test_jitter_within_bounds():
    rng = random.Random(42)
    for _ in range(100):
        x, y = jitter(500, 800, px=4, rng=rng)
        assert 496 <= x <= 504
        assert 796 <= y <= 804

def test_jitter_zero_px_is_identity():
    rng = random.Random(0)
    assert jitter(10, 20, px=0, rng=rng) == (10, 20)
