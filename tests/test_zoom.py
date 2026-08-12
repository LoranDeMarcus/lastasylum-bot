from config import Config
from src.cancel import Cancel
from src.zoom import ZoomKeeper

class FakeDriver:
    """Щипок двигает уровень по лестнице close -> skull -> far."""
    LADDER = ["close", "skull", "far"]

    def __init__(self, level="close"):
        self.level = level
        self.pinches = []

    def screenshot(self):
        return self.level          # «кадр» — просто метка уровня

    def zoom_out(self):
        self.pinches.append("out")
        i = min(len(self.LADDER) - 1, self.LADDER.index(self.level) + 1)
        self.level = self.LADDER[i]

    def zoom_in(self):
        self.pinches.append("in")
        i = max(0, self.LADDER.index(self.level) - 1)
        self.level = self.LADDER[i]

class FakeVision:
    def map_zoom(self, img):
        return img                 # кадр и есть уровень

def _cfg():
    cfg = Config()
    cfg.human_enabled = False      # без случайных пауз тест детерминирован
    return cfg

def _keeper(driver, cfg=None):
    cfg = cfg or _cfg()
    return ZoomKeeper(driver, FakeVision(), cfg, log=lambda m: None, sleep=lambda s: None)

def test_already_at_wanted_level_does_not_pinch():
    d = FakeDriver("skull")
    assert _keeper(d).ensure("skull") is True
    assert d.pinches == []

def test_one_pinch_out_from_close_to_skull():
    d = FakeDriver("close")
    assert _keeper(d).ensure("skull") is True
    assert d.pinches == ["out"]

def test_overshoot_is_rolled_back():
    """Скулл и пин — соседние ступени, перелёт штатен и должен откатываться."""
    d = FakeDriver("far")
    assert _keeper(d).ensure("skull") is True
    assert d.pinches == ["in"]

def test_two_steps_from_far_to_close():
    d = FakeDriver("far")
    assert _keeper(d).ensure("close") is True
    assert d.pinches == ["in", "in"]

def test_two_steps_from_close_to_far():
    """Лестница обратима: два щипка НАРУЖУ, не только внутрь — симметрия
    с test_two_steps_from_far_to_close (та проверяла только направление in)."""
    d = FakeDriver("close")
    assert _keeper(d).ensure("far") is True
    assert d.pinches == ["out", "out"]

def test_unknown_screen_fails_without_pinching():
    """Не на карте — щипать вслепую нельзя: под нами может быть меню."""
    d = FakeDriver("unknown")
    assert _keeper(d).ensure("skull") is False
    assert d.pinches == []

def test_stop_before_pinch_blocks_action():
    """Отмена проверяется ПЕРЕД щипком, а не только между паузами: между
    двумя паузами бот успевает щипнуть, а после Стопа щипать уже незачем
    (та же историческая проблема, что решает src/cancel.py)."""
    d = FakeDriver("close")
    cancel = Cancel()
    cancel.set()          # Стоп нажат ДО первого вызова ensure
    keeper = ZoomKeeper(d, FakeVision(), _cfg(), log=lambda m: None,
                         sleep=lambda s: None, cancel=cancel)
    assert keeper.ensure("skull") is False
    assert d.pinches == []

def test_gives_up_after_fail_limit():
    """Щипок не двигает карту -> не долбимся вечно.

    Лимит здесь НАМЕРЕННО отличается от дефолта cfg.zoom_fail_limit (3,
    см. config.py): при совпадении тест не отличил бы модуль, читающий
    предел из конфига, от кода с захардкоженной тройкой — обе версии
    остались бы зелёными. Значение 2 ловит именно эту подмену."""
    class Stuck(FakeDriver):
        def zoom_out(self):
            self.pinches.append("out")      # уровень не меняется
    cfg = _cfg()
    cfg.zoom_fail_limit = 2
    d = Stuck("close")
    assert _keeper(d, cfg).ensure("skull") is False
    assert len(d.pinches) == 2
