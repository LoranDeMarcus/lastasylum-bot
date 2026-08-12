# src/thief.py
import time
from src.cancel import Cancel
from src.energy import EnergyRefill
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
        self.energy = EnergyRefill(driver, vision, cfg, log=log, sleep=sleep,
                                   human=self.human, cancel=self.cancel)

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

    @property
    def flasks_used(self):
        return self.energy.flasks_used

    @property
    def last_flask_stock(self):
        return self.energy.last_flask_stock

    def _select_squad(self):
        """Выбрать отряд 2 в превью.

        Своя копия, а не Actions._select_squad: лезть в приватный метод
        соседнего класса — способ намертво связать два режима. Координата
        слота одна и та же, она в cfg.squad_slots."""
        sx, sy = self.vision.squad_slot(self.cfg.mob_squad)
        self.driver.tap(self.cfg.tap_box("squad_slot", (sx, sy)))
        self.human.after_tap(0.4)

    def _open_panel(self, target):
        """Тап по цели и ожидание панели. Box кнопки «Атака» или None.

        Двухтапно, но ВТОРОЙ тап условный: замер §0.1 показал, что панель
        иногда открывается с первого раза, и безусловный второй тап закрыл бы
        уже открытую панель. Промах по мелкой иконке зумит карту и
        центрирует цель — тогда добиваем тапом по центру."""
        self.driver.tap(self.cfg.tap_box("target", (target.x, target.y)))
        self.human.after_tap(1.6)
        pos = self.vision.find_button(self.driver.screenshot(), "attack")
        if pos is not None:
            return pos
        if self.cancel.stopped():
            return None
        self.log("  панели нет -> карта зазумилась, добиваю тапом по центру")
        self.driver.tap(self.cfg.tap_box(
            "target", (self.cfg.screen_w // 2,
                       self.cfg.screen_h // 2 + self.cfg.zoom_center_tap_offset_y)))
        self.human.after_tap(1.6)
        return self.vision.find_button(self.driver.screenshot(), "attack")

    def attack(self, target, refill=False):
        """Один удар по цели: панель -> подтверждение вора -> «Атака» ->
        отряд 2 -> «Отправиться».

        refill — разрешено ли потратить фиолетовую склянку +50, если игра
        сказала, что энергии не хватает (решение принимает движок по порогу).

        'dispatched' | 'not_thief' | 'missed' | 'failed' | 'low_energy' | 'stopped'."""
        if self.cancel.stopped():
            return "stopped"
        pos = self._open_panel(target)
        if pos is None:
            return "stopped" if self.cancel.stopped() else "missed"

        # Цель подтверждается ЗДЕСЬ, а не по иконке: на отзуме Золотой вор и
        # рядовой моб ур.5 — один и тот же жёлтый череп с бейджем «5». Тап по
        # цели бесплатен, платит только «Отправиться», значит проверка ничего
        # не стоит, а ошибка стоила бы 10 энергии и пустого захода.
        if self.cfg.thief_require_title and not self.vision.thief_panel(self.driver.screenshot()):
            self.log("  это не Золотой вор, а обычный моб ур.5 -> пропускаю")
            self.actions.close_preview()
            self.human.after_tap(0.6)
            return "not_thief"

        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(pos)
        self.human.after_tap(2.0)

        img = self.driver.screenshot()
        send = self.vision.find_button(img, "dispatch")
        if send is None:
            if self.vision.find_button(img, "boost_energy") is not None:
                return self._low_energy(refill)
            # между тапом «Атака» и этим кадром была настоящая пауза (2 с) —
            # окно, где человек мог успеть нажать Стоп; не спутать с реальным
            # провалом открытия превью (см. предупреждение задачи о таком баге)
            return "stopped" if self.cancel.stopped() else self._abort("превью отправки не открылось")

        # Гейт «Лёгкая победа» выключен намеренно: замер показал, что игра
        # подменяет эту строку на «Ваши высокоуровневые солдаты еще не
        # достигли предела», и гейт пропустил бы заведомо проходимого вора
        # (мощь 13M против 670K).
        return self._dispatch(send)

    def _low_energy(self, refill):
        """Энергии меньше стоимости: игра подменила «Отправиться» на
        «Увеличить энергию». Она же — вход в окно энергии."""
        if not refill:
            self.log("  энергии не хватает (кнопка «Увеличить энергию»)")
            self.actions.close_preview()
            self.human.after_tap(0.6)
            return "low_energy"
        if not self.energy.use_flask():
            if self.cancel.stopped():
                return "stopped"
            self.actions.close_preview()
            self.human.after_tap(0.6)
            return "low_energy"
        send = self.vision.find_button(self.driver.screenshot(), "dispatch")
        if send is None:
            # use_flask() внутри тапал и спал — то же окно для Стопа, что и
            # выше: не спутать отмену с настоящим провалом возврата превью
            return "stopped" if self.cancel.stopped() else self._abort("после склянки превью не вернулось")
        return self._dispatch(send)

    def _dispatch(self, send):
        """Хвост отправки: выбрать отряд -> перечитать «Отправиться» -> тап.

        Общий для обычного пути и пути после склянки: раньше это были две
        похожие копии, и они уже разошлись — копия после склянки не
        перечитывала кнопку (вёрстка успевает перерисоваться дважды: окно
        энергии и выбор отряда) и не проверяла Стоп перед этим самым тапом,
        хотя пауза внутри use_flask() (несколько тапов, ~3 c) — самое
        широкое окно для Стопа во всём методе, а тап тратит 10 энергии."""
        self._select_squad()
        send = self.vision.find_button(self.driver.screenshot(), "dispatch") or send
        if self.cancel.stopped():
            return "stopped"
        self.driver.tap(send)
        self.human.after_tap(1.5)
        return "dispatched"
