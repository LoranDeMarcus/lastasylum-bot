# src/corruption.py
import time
from src.cancel import Cancel
from src.human import Human
from src.watchdog import safe_back
from src.energy import EnergyRefill

class CorruptionActions:
    """Режим «Элитная скверна» (проверено вживую, reference/13..18):
    лупа -> вкладка «Элитная скверна» -> «Поиск» -> панель босса открывается
    САМА -> «Штурм» -> превью -> «Начать Штурм» (энергия −20).

    Тапа по иконке на карте нет, поэтому промахов и случайного зума не бывает —
    не нужны ни детекция черепов, ни guard вида, ни отзум щипком. Каждый шаг
    подтверждается шаблоном; не подтвердился -> BACK и заход провален
    (вызывающий считает провалы и после N подряд зовёт человека)."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep,
                 human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.actions = actions        # энергоокно/склянки переиспользуем
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        # если human не передан — свой, но спящий через тот же sleep (тесты
        # подсовывают фейковый sleep и должны видеть паузы именно там)
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        # cancel всегда объект, а не None: точки проверки во флоу читаются
        # как `if self.cancel.stopped()`, без проверок на None в каждой
        self.cancel = cancel if cancel is not None else Cancel()
        self.energy = EnergyRefill(driver, vision, cfg, log=log, sleep=sleep,
                                   human=self.human, cancel=self.cancel)

    def _wait_any(self, wanted, timeout_s=None):
        """Ждём любой из перечисленных экранов; возвращаем какой дождались."""
        t = self.cfg.panel_verify_timeout_s if timeout_s is None else timeout_s
        for _ in range(max(1, int(t / 0.3))):
            if self.cancel.stopped():
                return None          # докручивать таймаут после Стопа незачем
            screen = self.vision.corruption_screen(self.driver.screenshot())
            if screen in wanted:
                return screen
            self.sleep(self.human.poll_s(0.3))
        return None

    def _wait_screen(self, want, timeout_s=None):
        return self._wait_any({want}, timeout_s) == want

    def _wait_dialog(self):
        """Диалог поиска выезжает анимацией — одиночной проверки мало."""
        t = self.cfg.panel_verify_timeout_s
        for _ in range(max(1, int(t / 0.3))):
            if self.cancel.stopped():
                return False
            if self.vision.search_dialog_open(self.driver.screenshot()):
                return True
            self.sleep(self.human.poll_s(0.3))
        return False

    def _safe_back(self):
        # логика одна на весь проект (нужна и сторожу) -> живёт в watchdog
        safe_back(self.driver, self.vision, self.cfg, log=self.log,
                  sleep=self.sleep, human=self.human)

    def _abort(self, why):
        """Шаг не подтвердился: закрываем то, что открылось, чтобы следующая
        итерация не тапала вслепую по чужому меню."""
        self.log(f"  {why} -> BACK")
        self._safe_back()
        return "failed"

    @property
    def flasks_used(self):
        return self.energy.flasks_used

    @property
    def last_flask_stock(self):
        return self.energy.last_flask_stock

    def _use_flask(self):
        return self.energy.use_flask()

    def _close_energy_window(self):
        self.energy.close_window()

    def run_once(self, refill=False):
        """Один заход поиск->штурм.

        refill — разрешено ли потратить фиолетовую склянку +50, если игра
        сказала, что энергии не хватает (решение о разрешении принимает
        движок по порогу остатка).

        'dispatched' | 'failed' | 'low_energy' | 'skip_unwinnable' | 'stopped'."""
        # Проверка перед КАЖДЫМ тапом: прерываемого сна мало, между двумя
        # паузами бот успевает тапнуть, а после Стопа тапать уже незачем.
        # Экран оставляем как есть — прибираться некому и незачем, человек
        # за клавиатурой.
        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(self.cfg.tap_box("corruption_search_icon", self.cfg.corruption_search_icon_xy))
        self.human.after_tap(0.8)
        if not self._wait_dialog():
            return "stopped" if self.cancel.stopped() else self._abort("диалог поиска не открылся")

        # вкладка может быть не выбрана -> тапаем ВСЕГДА, без проверки активности
        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(self.cfg.tap_box("corruption_tab", self.cfg.corruption_tab_xy))
        self.human.after_tap(0.8)
        if not self._wait_screen('dialog'):
            return "stopped" if self.cancel.stopped() else self._abort("вкладка «Элитная скверна» не открылась")

        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(self.cfg.tap_box("corruption_search", self.cfg.corruption_search_xy))
        self.human.after_tap(1.6)
        if not self._wait_screen('boss_panel'):
            return "stopped" if self.cancel.stopped() else self._abort("«Поиск» не дал панель босса")

        if self.cancel.stopped():
            return "stopped"
        pos = self.vision.find_button(self.driver.screenshot(), "assault")
        self.driver.tap(pos if pos is not None else self.cfg.tap_box("corruption_assault", self.cfg.corruption_assault_xy))
        screen = self._wait_any({'preview', 'preview_low_energy'})
        if screen is None:
            return "stopped" if self.cancel.stopped() else self._abort("превью штурма не открылось")
        if screen == 'preview_low_energy':
            # Энергии меньше стоимости штурма: игра подменяет «Начать Штурм»
            # на «Увеличить энергию». Она же — вход в окно энергии.
            if not refill:
                self.log("  энергии не хватает на штурм (кнопка «Увеличить энергию»)")
                self.actions.close_preview()
                self.human.after_tap(0.6)
                return "low_energy"
            if not self._use_flask():
                if self.cancel.stopped():
                    return "stopped"
                self.actions.close_preview()
                self.human.after_tap(0.6)
                return "low_energy"
            if not self._wait_screen('preview'):
                return "stopped" if self.cancel.stopped() else self._abort("после склянки превью не вернулось")

        # Гейт победы по умолчанию выключен: уровень скверны фиксирует человек,
        # значит босс заведомо проходим (см. спеку).
        if self.cfg.corruption_verdict_gate:
            pred = self.vision.win_prediction(self.driver.screenshot())
            if pred != 'win':
                self.log(f"  прогноз боя '{pred}' != win -> пропускаем босса")
                self.actions.close_preview()
                self.human.after_tap(0.6)
                return "skip_unwinnable"

        if self.cancel.stopped():
            return "stopped"
        send = self.vision.find_button(self.driver.screenshot(), "start_assault")
        if send is None:
            return self._abort("кнопка «Начать Штурм» пропала")
        self.driver.tap(send)
        self.human.after_tap(1.5)
        return "dispatched"
