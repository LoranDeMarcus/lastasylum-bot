# src/energy.py
import time
from src.cancel import Cancel
from src.human import Human

class EnergyRefill:
    """Окно «Восстановить энергию»: фиолетовая склянка +50 и остаток.

    Общая для всех режимов: окно открывается кнопкой «Увеличить энергию»,
    которая подменяет кнопку отправки на превью, когда энергии не хватает.

    Строк в окне 3 или 4 (при четырёх третья — зелёная +10), поэтому Y кнопки
    «Использовать» берётся от найденной строки фиолетовой склянки, а не из
    конфига: фиксированная координата промахнулась бы на другой вёрстке."""

    def __init__(self, driver, vision, cfg, log=print, sleep=time.sleep,
                 human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        self.cancel = cancel if cancel is not None else Cancel()
        self.flasks_used = 0
        self.last_flask_stock = None

    def use_flask(self):
        """С превью «Увеличить энергию» -> окно энергии -> «Использовать» у
        фиолетовой склянки +50 -> закрыть окно. True, если склянка применена."""
        if self.cancel.stopped():
            return False
        self.driver.tap(self.cfg.tap_box("corruption_boost_energy",
                                         self.cfg.corruption_boost_energy_xy))
        self.human.after_tap(1.2)
        img = self.driver.screenshot()
        if not self.vision.energy_window_open(img):
            self.log("  окно энергии не открылось")
            return False
        row_y = self.vision.flask_row_y(img)
        if row_y is None:
            self.log("  фиолетовая склянка +50 не найдена — склянку не тратим")
            self.close_window()
            return False

        # Счётчик показывает, сколько склянок ещё влезет по энергии. Один тап
        # тратит ровно одну (+50), поэтому тапаем не больше этого предела.
        limit = self.vision.flask_use_qty(img, row_y)
        taps = self.cfg.flask_use_taps if limit is None else min(self.cfg.flask_use_taps, limit)
        if taps < 1:
            self.log("  энергии уже достаточно, склянки не нужны")
            self.close_window()
            return False

        self.log(f"  применяю фиолетовую склянку +50 x{taps} (строка y={row_y})")
        for _ in range(taps):
            if self.cancel.stopped():
                return False
            self.driver.tap(self.cfg.tap_box("flask_use", (self.cfg.flask_use_x, row_y)))
            self.human.after_tap(1.0)
            self.flasks_used += 1

        # После применения счётчик исчезает и открывается «В наличии: N» —
        # это авторитетный остаток, точнее локального учёта.
        img = self.driver.screenshot()
        row_y = self.vision.flask_row_y(img) or row_y
        stock = self.vision.read_flask_stock(img, row_y)
        if stock is not None:
            self.last_flask_stock = stock
            self.log(f"  склянок в наличии: {stock}")
        self.close_window()
        return True

    def close_window(self):
        pos = self.vision.find_button(self.driver.screenshot(), "energy_close")
        self.driver.tap(pos if pos is not None
                        else self.cfg.tap_box("energy_window_close", self.cfg.energy_window_close_xy))
        self.human.after_tap(1.0)
