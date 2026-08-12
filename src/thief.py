# src/thief.py
import time
from src.cancel import Cancel
from src.human import Human
from src.watchdog import safe_back

class ThiefActions:
    """Режим «Поиск вора» (проверено вживую 2026-08-12, reference/40..46):
    «Особое событие» -> вкладка «Поиск вора» -> «Поиск» -> камера уезжает к
    ближайшему вору -> отзум -> тап по черепу ур.5 -> «Атака» -> отряд 2 ->
    «Отправиться» (энергия −10).

    Две операции, потому что у них разная цена и разные условия: search()
    лезет в меню и стоит зум-ина, attack() бьёт цель на отзуме."""

    def __init__(self, driver, vision, actions, cfg, zoom, log=print,
                 sleep=time.sleep, human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.actions = actions        # close_preview и энергоокно переиспользуем
        self.cfg = cfg
        self.zoom = zoom
        self.log = log
        self.sleep = sleep
        # если human не передан — свой, но спящий через тот же sleep (тесты
        # подсовывают фейковый sleep и должны видеть паузы именно там)
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        # cancel всегда объект, а не None: точки проверки читаются
        # как `if self.cancel.stopped()`, без проверок на None в каждой
        self.cancel = cancel if cancel is not None else Cancel()
        self.last_wave_seconds = None

    def _safe_back(self):
        # логика одна на весь проект (нужна и сторожу) -> живёт в watchdog
        safe_back(self.driver, self.vision, self.cfg, log=self.log,
                  sleep=self.sleep, human=self.human)

    def _wait_tab(self):
        """Окно события выезжает анимацией — одиночной проверки мало."""
        for _ in range(max(1, int(self.cfg.panel_verify_timeout_s / 0.3))):
            if self.cancel.stopped():
                return False
            if self.vision.thief_tab_open(self.driver.screenshot()):
                return True
            self.sleep(self.human.poll_s(0.3))
        return False

    def search(self):
        """Заход «Поиск»: перевезти камеру к ближайшему вору.

        'searched'  — окно закрылось, камера уехала, цели ищем на карте;
        'no_event'  — вкладки «Поиск вора» нет (событие кончилось/уехало);
        'no_wave'   — окно осталось открытым: «Поиску» некого искать;
        'failed'    — шаг не подтвердился;
        'stopped'   — нажат Стоп."""
        if self.cancel.stopped():
            return "stopped"
        # Кнопка «Особое событие» видна ТОЛЬКО на зум-ине (замер §0.1):
        # на отзуме вместо правого столбца событий стоит легенда карты.
        if not self.zoom.ensure("close"):
            # ZoomKeeper сам проверяет отмену внутри лестницы щипков (паузы
            # между ними ~1.3 с — окно для Стопа реальное) и при Стопе тоже
            # отдаёт False, не тапнув. Если списать это в 'failed' наравне с
            # настоящим провалом зума, Стоп попадёт в счётчик поломок
            # вызывающего кода и лог соврёт про причину.
            if self.cancel.stopped():
                return "stopped"
            self.log("  «Поиск»: не смог привести зум к зум-ину")
            return "failed"

        if self.cancel.stopped():
            return "stopped"
        pos = self.vision.find_button(self.driver.screenshot(), "event_button")
        self.driver.tap(pos if pos is not None
                        else self.cfg.tap_box("thief_event_button", self.cfg.thief_event_button_xy))
        self.human.after_tap(1.2)

        if not self._wait_tab():
            if self.cancel.stopped():
                return "stopped"
            # Окно события открывается на ПОСЛЕДНЕЙ смотренной вкладке, и это
            # не обязательно наша. Ищем свою шаблоном в полосе вкладок: набор
            # вкладок меняется вместе с активными событиями, фиксированная
            # координата промахнётся при первой же смене.
            tab = self.vision.find_button(self.driver.screenshot(), "thief_tab")
            if tab is None:
                self.log("  вкладки «Поиск вора» нет — событие кончилось или уехало за край")
                self._safe_back()
                return "no_event"
            self.driver.tap(tab)
            self.human.after_tap(0.8)
            if not self._wait_tab():
                return "stopped" if self.cancel.stopped() else self._abort("вкладка не открылась")

        if self.cancel.stopped():
            return "stopped"
        img = self.driver.screenshot()
        self.last_wave_seconds = self.vision.wave_seconds(img)
        send = self.vision.find_button(img, "thief_search")
        if send is None:
            return self._abort("кнопка «Поиск» не найдена")
        # Тапаем по НАЙДЕННОЙ кнопке, а не по координате: рядом стоит «Поиск
        # босса», и слепой тап по координате при смене вёрстки уйдёт в неё.
        self.driver.tap(send)
        self.human.after_tap(2.0)

        if self.vision.thief_tab_open(self.driver.screenshot()):
            # Окно осталось открытым: искать некого, волна выбита.
            self.log(f"  «Поиск» никого не нашёл — волна выбита "
                     f"(до следующей {self.last_wave_seconds} с)")
            self._safe_back()
            return "no_wave"
        return "searched"

    def _abort(self, why):
        """Шаг не подтвердился: закрываем то, что открылось, чтобы следующая
        итерация не тапала вслепую по чужому меню."""
        self.log(f"  {why} -> BACK")
        self._safe_back()
        return "failed"
