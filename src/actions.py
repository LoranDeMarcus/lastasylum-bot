import time

class Actions:
    """Реальные действия в UI. Флоу (проверено вживую, reference/*.png):
    тап по иконке цели -> панель «Атака»(моб)/«Штурм»(босс) -> кнопка действия
    -> превью отправки (5 героев, карточки отрядов, «Отправиться») -> выбрать
    отряд -> «Отправиться» (тратит энергию, отряд уходит в «Перемещение»).

    Промах по иконке ЗУМИТ карту (панель не появляется) -> open_target_panel
    вернёт None, вызывающий должен восстановить вид и пере-детектить."""

    def __init__(self, driver, vision, cfg, log=print, sleep=time.sleep):
        self.driver = driver
        self.vision = vision
        self.cfg = cfg
        self.log = log
        self.sleep = sleep

    def wait_for(self, name, timeout_s=8.0, poll_s=0.4):
        for _ in range(max(1, int(timeout_s / poll_s))):
            pos = self.vision.find_button(self.driver.screenshot(), name)
            if pos is not None:
                return pos
            self.sleep(poll_s)
        return None

    def open_target_panel(self, target):
        """Тап по цели и ожидание панели. Возвращает 'attack'|'assault'|None.
        None -> промах (вероятно карта зумнулась), вид нужно восстановить."""
        self.driver.tap(target.x, target.y)
        deadline = max(1, int(self.cfg.panel_verify_timeout_s / 0.3))
        for _ in range(deadline):
            act = self.vision.panel_action(self.driver.screenshot())
            if act is not None:
                return act
            self.sleep(0.3)
        return None

    def _tap_action_button(self, name):
        """С открытой панели жмём кнопку действия («attack»/«assault»)."""
        pos = self.vision.find_button(self.driver.screenshot(), name)
        if pos is None:
            return False
        self.driver.tap(*pos)
        return True

    def _select_squad(self, squad_n):
        sx, sy = self.vision.squad_slot(squad_n)
        self.driver.tap(sx, sy)
        self.sleep(0.4)

    def close_preview(self):
        """Закрыть превью/панель без отправки (тап по затемнённой области)."""
        self.driver.tap(*self.cfg.preview_close_xy)

    def attack_mob(self, target):
        act = self.open_target_panel(target)
        if act is None:
            self.log("  промах по мобу (панель не открылась -> вероятно зум)")
            return "missed"
        if act != "attack":
            self.log(f"  ожидал панель моба, открылась '{act}' -> отмена")
            self.close_preview()
            return "wrong_panel"
        if not self._tap_action_button("attack"):
            return "failed"
        send = self.wait_for("dispatch")          # кнопка «Отправиться»
        if send is None:
            return "failed"
        self._select_squad(self.cfg.mob_squad)    # отряд 2
        send = self.wait_for("dispatch", timeout_s=3.0) or send
        self.driver.tap(*send)
        return "dispatched"

    def assault_boss(self, target):
        act = self.open_target_panel(target)
        if act is None:
            self.log("  промах по боссу (панель не открылась -> вероятно зум)")
            return "missed"
        if act != "assault":
            self.log(f"  ожидал панель босса, открылась '{act}' -> отмена")
            self.close_preview()
            return "wrong_panel"
        if not self._tap_action_button("assault"):
            return "failed"
        send = self.wait_for("start_assault")     # кнопка «Начать Штурм»
        if send is None:
            return "failed"
        # гейт: штурмуем только при явной победе (реком. мощь босса может быть >> нашей)
        pred = self.vision.win_prediction(self.driver.screenshot())
        if pred != "win":
            self.log(f"  прогноз боя '{pred}' != win -> пропускаем босса")
            self.close_preview()
            return "skip_unwinnable"
        self._select_squad(self.cfg.boss_squad)   # отряд 1
        send = self.wait_for("start_assault", timeout_s=3.0) or send
        self.driver.tap(*send)
        return "dispatched"

    # --- Энергия/склянки (координаты энергоокна требуют живой калибровки) ---
    def _open_energy(self):
        self.driver.tap(*self.cfg.energy_open_xy)   # «+» на экране отправки
        return self.wait_for("flask_use", timeout_s=3.0)

    def _close_energy(self):
        img = self.driver.screenshot()
        x = self.vision.find_button(img, "energy_close")
        if x is not None:
            self.driver.tap(*x)
        else:
            self.driver.tap(*self.cfg.energy_close_xy)

    def flasks_left(self):
        if self._open_energy() is None:
            return -1
        n = self.vision.read_flasks(self.driver.screenshot())
        self._close_energy()
        return n if n is not None else -1

    def refill_energy(self):
        use_pos = self._open_energy()
        if use_pos is not None:
            self.driver.tap(*use_pos)
            self.sleep(0.4)
        n = self.vision.read_flasks(self.driver.screenshot())
        self._close_energy()
        return n if n is not None else -1
