# src/corruption.py
import time
from src.cancel import Cancel
from src.human import Human

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
        self.flasks_used = 0          # сколько склянок потрачено за сессию
        self.last_flask_stock = None  # «В наличии: N», прочитанное после применения

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
        """Системная «назад» + страховка. На ЧИСТОЙ карте «назад» открывает
        «Выйти из игры?» — если это проглядеть, следующий слепой тап может
        подтвердить выход. Поэтому сразу проверяем и жмём «Отмена»."""
        self.driver.back()
        self.human.after_tap(0.6)
        img = self.driver.screenshot()
        if self.vision.exit_dialog_open(img):
            pos = self.vision.find_button(img, "exit_cancel")
            self.log("  открылся диалог выхода из игры -> Отмена")
            self.driver.tap(pos if pos is not None else self.cfg.tap_box("exit_cancel", self.cfg.exit_cancel_xy))
            self.human.after_tap(0.6)

    def _abort(self, why):
        """Шаг не подтвердился: закрываем то, что открылось, чтобы следующая
        итерация не тапала вслепую по чужому меню."""
        self.log(f"  {why} -> BACK")
        self._safe_back()
        return "failed"

    def _use_flask(self):
        """С превью «Увеличить энергию» -> окно энергии -> «Использовать» у
        ФИОЛЕТОВОЙ склянки +50 -> закрыть окно. True, если склянка применена.

        Строк в окне 3 или 4 (при четырёх третья — зелёная +10), поэтому Y
        кнопки берём от найденной строки фиолетовой склянки, а не из конфига:
        фиксированная координата промахнулась бы на другой вёрстке."""
        if self.cancel.stopped():
            return False
        self.driver.tap(self.cfg.tap_box("corruption_boost_energy", self.cfg.corruption_boost_energy_xy))
        self.human.after_tap(1.2)
        img = self.driver.screenshot()
        if not self.vision.energy_window_open(img):
            self.log("  окно энергии не открылось")
            return False
        row_y = self.vision.flask_row_y(img)
        if row_y is None:
            self.log("  фиолетовая склянка +50 не найдена — склянку не тратим")
            self._close_energy_window()
            return False

        # Счётчик показывает, сколько склянок ещё влезет по энергии. Один тап
        # тратит ровно одну (+50), поэтому тапаем не больше этого предела —
        # лишний тап просто пропал бы впустую.
        limit = self.vision.flask_use_qty(img, row_y)
        taps = self.cfg.flask_use_taps if limit is None else min(self.cfg.flask_use_taps, limit)
        if taps < 1:
            self.log("  энергии уже достаточно, склянки не нужны")
            self._close_energy_window()
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
        self._close_energy_window()
        return True

    def _close_energy_window(self):
        pos = self.vision.find_button(self.driver.screenshot(), "energy_close")
        self.driver.tap(pos if pos is not None else self.cfg.tap_box("energy_window_close", self.cfg.energy_window_close_xy))
        self.human.after_tap(1.0)

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
