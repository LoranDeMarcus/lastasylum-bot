# src/zoom.py
import time
from src.cancel import Cancel
from src.human import Human

class ZoomKeeper:
    """Приведение карты к нужной ступени зума.

    Отдельный модуль, а не пара методов в режиме: это единственная механика
    бота с обратной связью «сделал -> проверил -> поправил», и именно она
    исторически разваливалась. Здесь её можно проверить изолированно.

    Лестница close -> skull -> far, один мягкий щипок на ступень (замер
    2026-08-12). Перелёт штатен: скулл и пин — соседи, и лишний щипок
    наружу убивает детекцию целей полностью (6 -> 0). Поэтому откат
    обязателен, и лестница для него обратима."""

    LADDER = ('close', 'skull', 'far')

    def __init__(self, driver, vision, cfg, log=print, sleep=time.sleep,
                 human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        # если human не передан — свой, но спящий через тот же sleep (тесты
        # подсовывают фейковый sleep и должны видеть паузы именно там)
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        # cancel всегда объект, а не None: точки проверки читаются
        # как `if self.cancel.stopped()`, без проверок на None в каждой
        self.cancel = cancel if cancel is not None else Cancel()

    def ensure(self, want):
        """Привести карту к ступени want. True — получилось.

        False отдаём в двух случаях, и оба означают «дальше вслепую нельзя»:
        экран не опознан (под нами может быть меню, а не карта) или щипок
        перестал двигать карту."""
        for _ in range(max(1, self.cfg.zoom_fail_limit)):
            if self.cancel.stopped():
                return False
            have = self.vision.map_zoom(self.driver.screenshot())
            if have == want:
                return True
            if have == 'unknown':
                self.log(f"  зум: экран не опознан — щипать вслепую не буду")
                return False
            self.log(f"  зум: {have} -> {want}, щипок")
            if self.LADDER.index(have) < self.LADDER.index(want):
                self.driver.zoom_out()
            else:
                self.driver.zoom_in()
            self.human.after_tap(1.3)      # карте нужно доехать анимацией
        self.log(f"  зум: не удалось привести к '{want}' за "
                 f"{self.cfg.zoom_fail_limit} щипков")
        return False
