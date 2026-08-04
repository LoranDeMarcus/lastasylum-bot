# src/corruption.py
import time

class CorruptionActions:
    """Режим «Элитная скверна» (проверено вживую, reference/13..18):
    лупа -> вкладка «Элитная скверна» -> «Поиск» -> панель босса открывается
    САМА -> «Штурм» -> превью -> «Начать Штурм» (энергия −20).

    Тапа по иконке на карте нет, поэтому промахов и случайного зума не бывает —
    не нужны ни детекция черепов, ни guard вида, ни отзум щипком. Каждый шаг
    подтверждается шаблоном; не подтвердился -> BACK и заход провален
    (вызывающий считает провалы и после N подряд зовёт человека)."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep):
        self.driver = driver
        self.vision = vision
        self.actions = actions        # энергоокно/склянки переиспользуем
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.last_flasks = None       # последнее прочитанное «В наличии: N»

    def _wait_screen(self, want, timeout_s=None):
        t = self.cfg.panel_verify_timeout_s if timeout_s is None else timeout_s
        for _ in range(max(1, int(t / 0.3))):
            if self.vision.corruption_screen(self.driver.screenshot()) == want:
                return True
            self.sleep(0.3)
        return False

    def _wait_dialog(self):
        """Диалог поиска выезжает анимацией — одиночной проверки мало."""
        t = self.cfg.panel_verify_timeout_s
        for _ in range(max(1, int(t / 0.3))):
            if self.vision.search_dialog_open(self.driver.screenshot()):
                return True
            self.sleep(0.3)
        return False

    def _safe_back(self):
        """Системная «назад» + страховка. На ЧИСТОЙ карте «назад» открывает
        «Выйти из игры?» — если это проглядеть, следующий слепой тап может
        подтвердить выход. Поэтому сразу проверяем и жмём «Отмена»."""
        self.driver.back()
        self.sleep(0.6)
        img = self.driver.screenshot()
        if self.vision.exit_dialog_open(img):
            pos = self.vision.find_button(img, "exit_cancel")
            self.log("  открылся диалог выхода из игры -> Отмена")
            self.driver.tap(*(pos if pos is not None else self.cfg.exit_cancel_xy))
            self.sleep(0.6)

    def _abort(self, why):
        """Шаг не подтвердился: закрываем то, что открылось, чтобы следующая
        итерация не тапала вслепую по чужому меню."""
        self.log(f"  {why} -> BACK")
        self._safe_back()
        return "failed"

    def _side_trip(self, refill, want_flasks):
        """Склянки читаются/тратятся ТОЛЬКО с превью: с карты «+» тапнет кнопку
        дома. refill — применить фиолетовую +50; want_flasks — только прочитать
        остаток. Окно не открылось -> last_flasks остаётся неизвестным.
        Возвращает True, если в окно энергии реально ходили."""
        if refill:
            n = self.actions.refill_energy()
        elif want_flasks:
            n = self.actions.flasks_left()
        else:
            return False
        self.last_flasks = n if n is not None and n >= 0 else None
        return True

    def run_once(self, refill=False, want_flasks=False):
        """Один заход поиск->штурм. 'dispatched' | 'failed' | 'skip_unwinnable'."""
        self.driver.tap(*self.cfg.corruption_search_icon_xy)
        self.sleep(0.8)
        if not self._wait_dialog():
            return self._abort("диалог поиска не открылся")

        # вкладка может быть не выбрана -> тапаем ВСЕГДА, без проверки активности
        self.driver.tap(*self.cfg.corruption_tab_xy)
        self.sleep(0.8)
        if not self._wait_screen('dialog'):
            return self._abort("вкладка «Элитная скверна» не открылась")

        self.driver.tap(*self.cfg.corruption_search_xy)
        self.sleep(1.6)
        if not self._wait_screen('boss_panel'):
            return self._abort("«Поиск» не дал панель босса")

        pos = self.vision.find_button(self.driver.screenshot(), "assault")
        self.driver.tap(*(pos if pos is not None else self.cfg.corruption_assault_xy))
        if not self._wait_screen('preview'):
            return self._abort("превью штурма не открылось")

        # Гейт победы по умолчанию выключен: уровень скверны фиксирует человек,
        # значит босс заведомо проходим (см. спеку).
        if self.cfg.corruption_verdict_gate:
            pred = self.vision.win_prediction(self.driver.screenshot())
            if pred != 'win':
                self.log(f"  прогноз боя '{pred}' != win -> пропускаем босса")
                self.actions.close_preview()
                self.sleep(0.6)
                return "skip_unwinnable"

        if self._side_trip(refill, want_flasks):
            # окно энергии перекрывает превью и закрывается с анимацией —
            # без ожидания «Начать Штурм» ещё не виден и заход срывается
            if not self._wait_screen('preview'):
                return self._abort("превью не вернулось после окна энергии")

        send = self.vision.find_button(self.driver.screenshot(), "start_assault")
        if send is None:
            return self._abort("кнопка «Начать Штурм» пропала")
        self.driver.tap(*send)
        self.sleep(1.5)
        return "dispatched"
