import time

class Actions:
    def __init__(self, driver, vision, cfg, sleep=time.sleep):
        self.driver = driver
        self.vision = vision
        self.cfg = cfg
        self.sleep = sleep

    def wait_for(self, name, timeout_s=8.0, poll_s=0.4):
        deadline_polls = max(1, int(timeout_s / poll_s))
        for _ in range(deadline_polls):
            img = self.driver.screenshot()
            pos = self.vision.find_button(img, name)
            if pos is not None:
                return pos
            self.sleep(poll_s)
        return None

    def attack_mob(self, target):
        self.driver.tap(target.x, target.y)
        pos = self.wait_for("attack")
        if pos is None:
            return False
        self.driver.tap(*pos)
        # превью боя: выбрать второй отряд, затем «Отправиться»
        sx, sy = self.vision.squad_slot(self.cfg.mob_squad)
        self.driver.tap(sx, sy)
        pos = self.wait_for("dispatch")
        if pos is None:
            return False
        self.driver.tap(*pos)
        return True

    def assault_boss(self, target):
        self.driver.tap(target.x, target.y)
        pos = self.wait_for("assault")
        if pos is None:
            return False
        self.driver.tap(*pos)
        # Штурм использует первый отряд. Если появится выбор отряда —
        # раскомментировать (уточняется на калибровке, см. CALIBRATION.md):
        # sx, sy = self.vision.squad_slot(self.cfg.boss_squad)
        # self.driver.tap(sx, sy)
        confirm = self.wait_for("dispatch")
        if confirm is not None:
            self.driver.tap(*confirm)
        return True

    def _open_energy(self):
        img = self.driver.screenshot()
        cross = self.vision.find_button(img, "energy_cross")
        if cross is None:
            return None
        self.driver.tap(*cross)
        return self.wait_for("flask_use")

    def _close_energy(self):
        img = self.driver.screenshot()
        x = self.vision.find_button(img, "energy_close")
        if x is not None:
            self.driver.tap(*x)

    def flasks_left(self):
        self._open_energy()
        img = self.driver.screenshot()
        n = self.vision.read_flasks(img)
        self._close_energy()
        return n if n is not None else -1

    def refill_energy(self):
        use_pos = self._open_energy()
        if use_pos is not None:
            self.driver.tap(*use_pos)
        img = self.driver.screenshot()
        n = self.vision.read_flasks(img)
        self._close_energy()
        return n if n is not None else -1

    def close_popups(self):
        img = self.driver.screenshot()
        x = self.vision.find_button(img, "reward_close")
        if x is not None:
            self.driver.tap(*x)
