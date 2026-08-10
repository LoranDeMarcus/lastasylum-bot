# src/join.py
import time
from src.cancel import Cancel
from src.human import Human
from src.watchdog import safe_back

class JoinActions:
    """Присоединение к чужому штурму «Элитной скверны» (кадры reference/30..32):
    иконка-череп -> окно «Война альянсов» -> вкладка «Событие» -> самый правый
    зелёный «+» первой подходящей карточки -> превью -> «Отправиться».

    Тапа по карте нет, поэтому промахов и случайного зума не бывает. Каждый шаг
    подтверждается шаблоном; не подтвердился -> BACK и заход провален.

    Мест может не остаться, пока мы тапаем: это гонка за слот, а не поломка —
    пробуем следующую карточку и провалом не считаем, иначе бот выключался бы
    в самом живом альянсе."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep,
                 human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.actions = actions        # Actions: нужен close_preview()
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        self.cancel = cancel if cancel is not None else Cancel()

    def _wait_any(self, wanted, timeout_s=None):
        t = self.cfg.panel_verify_timeout_s if timeout_s is None else timeout_s
        for _ in range(max(1, int(t / 0.3))):
            if self.cancel.stopped():
                return None
            screen = self.vision.join_screen(self.driver.screenshot())
            if screen in wanted:
                return screen
            self.sleep(self.human.poll_s(0.3))
        return None

    def _abort(self, why):
        self.log(f"  {why} -> BACK")
        safe_back(self.driver, self.vision, self.cfg, log=self.log,
                  sleep=self.sleep, human=self.human)
        return "failed"

    def run_once(self):
        """Один заход. 'dispatched' | 'no_calls' | 'lost_window' |
        'low_energy' | 'failed' | 'stopped'."""
        if self.cancel.stopped():
            return "stopped"
        icon = self.vision.assault_call_icon(self.driver.screenshot())
        if icon is None:
            return "no_calls"

        self.driver.tap(icon)
        self.human.after_tap(1.0)
        if self._wait_any({'list'}) is None:
            return "stopped" if self.cancel.stopped() else self._abort("окно сборов не открылось")

        # вкладка может быть не выбрана -> тапаем ВСЕГДА, без проверки активности
        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(self.cfg.tap_box("join_tab", self.cfg.join_tab_xy))
        self.human.after_tap(0.8)
        if self._wait_any({'list'}) is None:
            return "stopped" if self.cancel.stopped() else self._abort("вкладка «Событие» не открылась")

        return self._wait_in_window()

    def _wait_in_window(self):
        """Сидим в окне, пока не вступим: подходящих сборов может не быть
        сейчас, но «Обновить» внизу — это ровно сигнал «кто-то запустил штурм».
        Выходим только по вступлению, Стопу или потере окна."""
        while True:
            if self.cancel.stopped():
                return "stopped"
            img = self.driver.screenshot()
            if not self.vision.alliance_war_open(img):
                self.log("  окно сборов пропало")
                return "lost_window"

            card = self._pick(self.vision.join_cards(img))
            if card is None:
                btn = self.vision.refresh_button(img)
                if btn is not None:
                    self.log("  появилась «Обновить» -> перечитываю список")
                    self.driver.tap(btn)
                    self.human.after_tap(0.8)
                else:
                    self.sleep(self.human.poll_s(self.cfg.join_poll_interval_s))
                continue

            res = self._join(card)
            if res == "taken":
                self.log("  места разобрали — пробую следующую карточку")
                continue
            return res

    def _pick(self, cards):
        """Первая сверху карточка со свободным слотом и запасом времени.
        Таймер не прочитался -> считаем, что времени хватает: цена ошибки —
        секунды ожидания, а отказ стоил бы отряда."""
        for c in cards:
            if not c.slots:
                continue
            if c.seconds is not None and c.seconds < self.cfg.join_min_seconds_left:
                continue
            return c
        return None

    def _join(self, card):
        """Тап по самому правому свободному слоту и отправка отряда."""
        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(card.slots[-1])
        self.human.after_tap(1.0)
        screen = self._wait_any({'preview', 'preview_low_energy', 'list'})
        if screen is None:
            return "stopped" if self.cancel.stopped() else self._abort("превью не открылось")
        if screen == 'list':
            return "taken"          # остались в списке — слот заняли раньше нас

        if screen == 'preview_low_energy':
            # Присоединение бесплатное: энергию игра просит, только когда
            # штурм запускаешь сам. Увидели «Увеличить энергию» — значит наше
            # представление об игре разошлось с игрой. Склянку не тратим:
            # закрываем превью и отдаём наверх, пусть зовут человека.
            self.log("  превью просит энергию, хотя присоединение бесплатное")
            self.actions.close_preview()
            self.human.after_tap(0.6)
            return "low_energy"

        if self.cancel.stopped():
            return "stopped"
        send = self.vision.find_button(self.driver.screenshot(), "dispatch")
        if send is None:
            return self._abort("кнопка «Отправиться» пропала")
        self.driver.tap(send)
        self.human.after_tap(1.5)
        return "dispatched"
