import random
import statistics
from config import Config
from src.models import Box
from src.human import Human

def _h(cfg=None, seed=7):
    return Human(cfg or Config(), rng=random.Random(seed), sleep=lambda s: None)

def test_same_seed_gives_same_sequence():
    """Детерминизм по сиду: иначе тест разброса нечем воспроизвести."""
    box = Box(500, 800, 200, 60)
    ha, hb = _h(seed=1), _h(seed=1)
    a = [(ha.point_in(box), round(ha.delay('react'), 6)) for _ in range(20)]
    b = [(hb.point_in(box), round(hb.delay('react'), 6)) for _ in range(20)]
    assert a == b
    assert len({p for p, _ in a}) > 1     # последовательность не вырождена

def test_point_in_never_leaves_inner_area():
    """clamp жёсткий: промах по мелкой кнопке дороже недобора случайности."""
    cfg = Config()
    h = _h(cfg)
    box = Box(500, 800, 200, 60)
    ax = box.w / 2 * cfg.tap_inset
    ay = box.h / 2 * cfg.tap_inset
    for _ in range(500):
        x, y = h.point_in(box)
        assert box.x - ax - 1 <= x <= box.x + ax + 1
        assert box.y - ay - 1 <= y <= box.y + ay + 1

def test_point_in_actually_spreads_and_centers_on_button():
    h = _h()
    box = Box(500, 800, 200, 60)
    pts = [h.point_in(box) for _ in range(500)]
    xs = [p[0] for p in pts]
    assert len(set(xs)) > 20                      # разброс есть, а не одна точка
    assert abs(statistics.mean(xs) - box.x) < 5   # облако центрировано на кнопке

def test_tiny_target_box_stays_within_few_pixels():
    """Цель на карте: бокс (16,16) -> разброс не шире нынешнего jitter ±4px."""
    h = _h()
    box = Box(545, 1164, 16, 16)
    for _ in range(200):
        x, y = h.point_in(box)
        assert 541 <= x <= 549 and 1160 <= y <= 1168

def test_react_delay_within_range_and_not_constant():
    cfg = Config()
    h = _h(cfg)
    xs = [h.delay('react') for _ in range(400)]
    assert all(cfg.delay_react[0] <= v <= cfg.delay_react[1] for v in xs)
    assert statistics.pstdev(xs) > 0.05

def test_react_delay_has_right_tail():
    """Логнормаль, а не равномерное: много быстрых реакций, редкий долгий
    хвост. У равномерного среднее совпадает с медианой — это машинный признак."""
    h = _h()
    xs = [h.delay('react') for _ in range(2000)]
    assert statistics.mean(xs) > statistics.median(xs)

def test_after_tap_never_shorter_than_calibrated_base():
    """Главный инвариант плана: защита ходит ТОЛЬКО вверх. Пауза короче
    калибровки сорвала бы верификации шагов."""
    slept = []
    h = Human(Config(), rng=random.Random(3), sleep=slept.append)
    for _ in range(300):
        h.after_tap(0.8)
    assert min(slept) >= 0.8

def test_poll_and_idle_never_shorter_than_base():
    h = _h()
    assert all(h.poll_s(0.3) >= 0.3 for _ in range(200))
    assert all(h.idle_s(10.0) >= 10.0 for _ in range(200))
