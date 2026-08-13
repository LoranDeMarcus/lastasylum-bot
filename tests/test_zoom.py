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

class UnknownVision:
    def map_zoom(self, img):
        return "unknown"

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

class FakeHuman:
    """Спай вместо настоящего Human: реальный after_tap растягивает базовую
    паузу случайным множителем (delay_settle_mult) и добавляет реакцию
    (delay_react >= 0.25 с) — точное значение cfg.pinch_settle_s в
    засечённой паузе никогда не увидеть, минимум для 2.0 с уже 2.25 с.
    Поэтому проверяем, ЧТО ZoomKeeper передаёт в after_tap, а не как
    Human это потом растянет — это уже забота теста самого Human."""
    def __init__(self):
        self.after_tap_calls = []

    def after_tap(self, base_s):
        self.after_tap_calls.append(base_s)

def test_settle_pause_comes_from_config():
    """Пауза после жеста — настройка: с 8 шагами жест короче, и карта
    доезжает анимацией уже ПОСЛЕ возврата управления."""
    cfg = _cfg()
    cfg.pinch_settle_s = 2.0
    human = FakeHuman()
    d = FakeDriver("close")
    k = ZoomKeeper(d, FakeVision(), cfg, log=lambda m: None, sleep=lambda s: None,
                   human=human)
    assert k.ensure("skull") is True
    assert 2.0 in human.after_tap_calls

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

def test_ensure_reports_unknown_screen():
    """«Экран не опознан» и «щипок не работает» — разные беды: первую надо
    переждать (баннер уходит сам), вторая требует человека. Снаружи их не
    различить, если ensure молча отдаёт False."""
    d = FakeDriver("close")
    k = ZoomKeeper(d, UnknownVision(), _cfg(), log=lambda m: None, sleep=lambda s: None)
    assert k.ensure("skull") is False
    assert k.last_failure == "unknown_screen"
    assert d.pinches == []          # вслепую не щипали

def test_ensure_reports_stuck_pinch():
    """Экран опознан, но щипок не двигает карту — это поломка."""
    class StuckDriver(FakeDriver):
        def zoom_out(self):
            self.pinches.append("out")      # карта не двигается
    d = StuckDriver("close")
    k = ZoomKeeper(d, FakeVision(), _cfg(), log=lambda m: None, sleep=lambda s: None)
    assert k.ensure("skull") is False
    assert k.last_failure == "stuck"

def test_ensure_clears_failure_on_success():
    d = FakeDriver("close")
    k = ZoomKeeper(d, FakeVision(), _cfg(), log=lambda m: None, sleep=lambda s: None)
    assert k.ensure("skull") is True
    assert k.last_failure is None
