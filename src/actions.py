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
        self.last_flasks = None   # последнее прочитанное «В наличии: N» (движок берёт отсюда)

    def wait_for(self, name, timeout_s=8.0, poll_s=0.4):
        for _ in range(max(1, int(timeout_s / poll_s))):
            pos = self.vision.find_button(self.driver.screenshot(), name)
            if pos is not None:
                return pos
            self.sleep(poll_s)
        return None

    def _poll_panel(self):
        deadline = max(1, int(self.cfg.panel_verify_timeout_s / 0.3))
        for _ in range(deadline):
            act = self.vision.panel_action(self.driver.screenshot())
            if act is not None:
                return act
            self.sleep(0.3)
        return None

    def open_target_panel(self, target):
        """Тап по цели и ожидание панели ('attack'|'assault'|None).
        Двухтапно: у мобов маленький хитбокс — первый тап часто ПРОМАХ и
        карта зумит+центрирует цель; тогда второй тап по центру-спрайту
        открывает панель (босс крупный — обычно открывается с первого).
        None только если панель не открылась и после второго тапа."""
        self.driver.tap(target.x, target.y)
        act = self._poll_panel()
        if act is not None:
            return act
        # промах -> цель отзумлена в центр; тап по центру-спрайту
        self.driver.tap(self.cfg.screen_w // 2,
                        self.cfg.screen_h // 2 + self.cfg.zoom_center_tap_offset_y)
        return self._poll_panel()

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

    def _dispatch_mob_from_panel(self, refill=False, want_flasks=False):
        """С ОТКРЫТОЙ панели моба: «Атака» -> (опц. окно энергии) -> отряд 2
        -> «Отправиться». Окно энергии доступно ТОЛЬКО с превью, поэтому
        чтение склянок/рефилл делаем здесь, пиггибеком (см. _energy_side_trip)."""
        if not self._tap_action_button("attack"):
            return "failed"
        send = self.wait_for("dispatch")          # кнопка «Отправиться»
        if send is None:
            return "failed"
        if refill or want_flasks:
            self.last_flasks = self._energy_side_trip(use_flask=refill)
        self._select_squad(self.cfg.mob_squad)    # отряд 2
        send = self.wait_for("dispatch", timeout_s=3.0) or send
        self.driver.tap(*send)
        return "dispatched"

    def attack_mob(self, target, refill=False, want_flasks=False):
        act = self.open_target_panel(target)
        if act is None:
            self.log("  промах по мобу (панель не открылась -> вероятно зум)")
            return "missed"
        if act != "attack":
            self.log(f"  ожидал панель моба, открылась '{act}' -> отмена")
            self.close_preview()
            return "wrong_panel"
        return self._dispatch_mob_from_panel(refill=refill, want_flasks=want_flasks)

    def search_thief(self):
        """«Особое событие» -> «Поиск вора» -> «Поиск» -> тап найденного моба
        (центрируется у базы -> короткий марш). Возвращает 'attack' если
        открылась панель моба, иначе None. Координаты — фикс. вёрстка диалога."""
        self.driver.tap(*self.cfg.event_button_xy);      self.sleep(1.2)
        self.driver.tap(*self.cfg.search_thief_tab_xy);  self.sleep(0.6)
        self.driver.tap(*self.cfg.search_button_xy);     self.sleep(1.6)
        self.driver.tap(*self.cfg.search_result_xy);     self.sleep(1.0)
        act = self.vision.panel_action(self.driver.screenshot())
        if act is None:
            # диалог события мог остаться открытым (вора нет / вёрстка иная) —
            # закрываем BACK'ом, иначе следующая итерация тапает по меню вслепую
            self.driver.back()
            self.sleep(0.6)
        return act

    def search_and_attack_mob(self, refill=False, want_flasks=False):
        """Найти вора у базы и отправить отряд 2. Статусы как у attack_mob.
        refill — применить фиолетовую склянку в превью; want_flasks — просто
        прочитать остаток склянок там же (окно энергии только с превью)."""
        act = self.search_thief()
        if act is None:
            self.log("  «Поиск» не дал панели моба")
            return "no_thief"
        if act != "attack":
            self.log(f"  «Поиск» открыл '{act}' вместо моба -> отмена")
            self.close_preview()
            return "wrong_panel"
        return self._dispatch_mob_from_panel(refill=refill, want_flasks=want_flasks)

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

    # --- Энергия/склянки (окно «Восстановить энергию», откалибровано) ---
    def _open_energy(self):
        """«+» на превью -> окно энергии. True если окно открылось (видна
        кнопка «Использовать»). Две кнопки «Использовать» идентичны, поэтому
        тапаем не по матчу, а по фикс. координате нужной (фиолетовой) склянки."""
        self.driver.tap(*self.cfg.energy_open_xy)
        return self.wait_for("flask_use", timeout_s=3.0) is not None

    def _close_energy(self):
        x = self.vision.find_button(self.driver.screenshot(), "energy_close")
        self.driver.tap(*(x if x is not None else self.cfg.energy_close_xy))

    def _energy_side_trip(self, use_flask):
        """С ОТКРЫТОГО превью отправки: «+» -> окно энергии -> (опц.)
        «Использовать» фиолетовую +50 -> прочитать «В наличии: N» -> закрыть.
        None, если окно не открылось. ВАЖНО: с карты «+» тапнет кнопку дома,
        поэтому вызывать только когда превью на экране."""
        if not self._open_energy():
            self.log("  окно энергии не открылось (не превью?)")
            return None
        if use_flask:
            self.driver.tap(*self.cfg.flask_use_xy)   # фиолетовая +50 (фикс. координата)
            self.sleep(0.4)
        n = self.vision.read_flasks(self.driver.screenshot())
        self._close_energy()
        self.last_flasks = n
        return n

    def flasks_left(self):
        n = self._energy_side_trip(use_flask=False)
        return n if n is not None else -1

    def refill_energy(self):
        n = self._energy_side_trip(use_flask=True)
        return n if n is not None else -1
