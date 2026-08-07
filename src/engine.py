# src/engine.py
import os
import time
import traceback
from src.models import GameState, Action, nearest
from src.cancel import Cancel
from src.decide import decide
from src.human import Human

class BotEngine:
    """Цикл фарма. Один отряд-на-задачу за раз (v1 последовательный):
    отряд занят -> ждём; свободен/«Возвращение» -> шлём следующую цель.
    Приоритет: босс («Штурм», отр.1) -> моб («Атака», отр.2) -> explore.

    dry_run (cfg.dry_run): читаем экран и ЛОГИРУЕМ решение, но НЕ тапаем —
    для проверки детекции/логики на живой игре без действий."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep,
                 corruption=None, human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.actions = actions
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        # если human не передан — свой, но спящий через тот же sleep (тесты
        # подсовывают фейковый sleep и должны видеть паузы именно там)
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        # cancel всегда объект, а не None: точки проверки читаются
        # как `if self.cancel.stopped()`, без проверок на None в каждой
        self.cancel = cancel if cancel is not None else Cancel()
        self.corruption = corruption   # CorruptionActions для режима «Элитная скверна»
        self.flasks = None
        self.skip_targets = set()   # непроходимые боссы / фантомы (по позиции) — не выбираем
        self._offmap_pinches = 0    # подряд попыток авто-отзума когда не на карте
        self._no_progress = 0       # подряд итераций без отправки (сосед-промах / провал «Поиска»)

    def start(self):
        if self.cfg.dry_run:
            self.flasks = 10 ** 9        # в dry-run не открываем энергоокно
            self.log("Старт (DRY-RUN: тапов не будет).")
        elif self.cfg.strategy == "corruption":
            # «В наличии: N» в окне энергии перекрыт счётчиком количества и
            # читается только ПОСЛЕ применения склянок. Поэтому на старте
            # остаток неизвестен: первый рефилл разрешён и он же его покажет.
            self.flasks = None
            self.log("Старт («Элитная скверна»). Остаток склянок прочитаю "
                     "из игры после первого рефилла.")
        elif self.cfg.use_search_strategy:
            # окно энергии открывается только с превью отправки; с карты «+»
            # тапнет кнопку дома -> склянки прочитаем на первом же превью
            self.flasks = None
            self.log("Старт («Поиск вора»). Склянки прочитаем на первом превью.")
        else:
            self.flasks = self.actions.flasks_left()
            self.log(f"Старт. Склянок: {self.flasks}")

    def _squad_ready(self, state):
        """Готов ли слать следующую цель по состоянию отряда."""
        if state == 'idle':
            return True
        if state == 'returning' and self.cfg.send_next_on_return:
            return True
        return False

    def read_state(self, img):
        energy = self.vision.read_energy(img)
        targets = self.vision.find_targets(img)
        return GameState(
            flasks=self.flasks if self.flasks is not None else 10**9,
            energy=energy if energy is not None else 999,   # не прочли -> не рефиллим спекулятивно
            deployed=0, targets=targets,
            screen_w=self.cfg.screen_w, screen_h=self.cfg.screen_h,
        )

    @staticmethod
    def _target_key(t):
        return (t.kind, round(t.x / 20), round(t.y / 20))

    def _neighbor_mobs(self, img):
        """Мобы, видимые на текущем виде у базы (после «Поиска» камера там).
        Только kind=='mob' (рогатых боссов и ложные UI-иконки, что классятся
        как 'boss', не фармим), без помеченных skip_targets (фантомы/промахи)."""
        return [t for t in self.vision.find_targets(img)
                if t.kind == 'mob' and self._target_key(t) not in self.skip_targets]

    def _search_iteration(self):
        """Гибрид «Поиск вора» + фарм соседей: ждём свободный отряд по виджету
        -> если на текущем виде виден моб-сосед, шлём отряд 2 на ближайшего к
        центру (короткий марш); соседей нет -> «Поиск вора» центрирует нового у
        базы. Весь цикл в зум-ине (кнопка события видна, марши крошечные).

        Склянки/энергия — пиггибеком на превью отправки (окно энергии только
        оттуда: с карты «+» тапнет кнопку дома), поэтому refill/want_flasks
        прокидываются в оба пути отправки."""
        if self.flasks is not None and self.flasks < self.cfg.flask_stop_threshold:
            self.log(f"Склянок {self.flasks} < {self.cfg.flask_stop_threshold} — стоп.")
            return Action('stop')

        img = self.driver.screenshot()
        squad = self.vision.squad_state(img)
        if not self._squad_ready(squad):
            self.log(f"Отряд занят ({squad}), ждём.")
            self.sleep(self.human.idle_s(2.0))
            return None

        energy = self.vision.read_energy(img)
        refill = energy is not None and energy < self.cfg.energy_refill_threshold
        want_flasks = self.flasks is None          # ещё не читали -> прочитать на превью
        mobs = self._neighbor_mobs(img)
        head = (f"[отряд={squad}] энергия={energy} склянок={self.flasks}"
                + (" (+рефилл склянкой)" if refill else ""))

        if self.cfg.dry_run:
            self.log(head + (f" -> сосед-моб (видно {len(mobs)})" if mobs else " -> соседей нет, поиск вора"))
            self.sleep(1.0)
            return Action('attack_mob')

        if mobs:
            target = nearest(mobs, self.cfg.screen_w // 2, self.cfg.screen_h // 2)
            self.log(head + f" -> сосед-моб @({target.x},{target.y}) [видно {len(mobs)}]")
            res = self.actions.attack_mob(target, refill=refill, want_flasks=want_flasks)
            self.log(f"  Атака соседа -> {res}")
            if res != 'dispatched':
                self.skip_targets.add(self._target_key(target))   # фантом/промах -> не выбирать снова
        else:
            self.log(head + " -> соседей нет, поиск вора у базы")
            res = self.actions.search_and_attack_mob(refill=refill, want_flasks=want_flasks)
            self.log(f"  Поиск+атака -> {res}")

        if self.actions.last_flasks is not None:
            self.flasks = self.actions.last_flasks

        if res == 'dispatched':
            self._no_progress = 0
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('attack_mob')

    def _corruption_iteration(self):
        """Режим «Элитная скверна»: гейт по числу активных отрядов «Отряд N/4»,
        отправка штурма пока есть свободные слоты. Все отряды в походе -> ждём;
        энергии не хватает и склянки тратить нельзя -> стоп.

        Тапа по карте нет (панель босса открывает сам «Поиск»), поэтому guard
        вида и авто-отзум тут не нужны."""
        img = self.driver.screenshot()
        active = self.vision.active_squads(img)
        if active >= self.cfg.squad_total:
            self.log(f"Все отряды заняты ({active}/{self.cfg.squad_total}), ждём.")
            self.sleep(self.human.idle_s(self.cfg.corruption_poll_interval_s))
            return None

        energy = self.vision.read_energy(img)
        # Разрешаем тратить склянку, пока учтённый остаток выше порога.
        # Остаток «В наличии: N» читается только ПОСЛЕ применения склянок
        # (до этого его перекрывает счётчик количества). Поэтому пока остаток
        # неизвестен, разрешаем один рефилл — он же и покажет реальное число,
        # после чего порог начинает работать точно.
        refill = self.flasks is None or self.flasks > self.cfg.flask_stop_threshold
        if not refill:
            self.log(f"Склянок {self.flasks} <= порога "
                     f"{self.cfg.flask_stop_threshold} — склянки не тратим.")

        self.log(f"[отрядов={active}/{self.cfg.squad_total}] энергия={energy} "
                 f"склянок={self.flasks}" + (" (+рефилл разрешён)" if refill else "")
                 + " -> штурм скверны")
        if self.cfg.dry_run:
            self.sleep(1.0)
            return Action('assault_boss')

        used_before = self.corruption.flasks_used
        res = self.corruption.run_once(refill=refill)
        if res == 'stopped':
            # остановка по кнопке — не провал бота, счётчик провалов не трогаем
            self.log("  заход прерван по кнопке Стоп")
            return Action('stop')
        self.log(f"  Штурм скверны -> {res}")
        spent = self.corruption.flasks_used - used_before
        if self.corruption.last_flask_stock is not None:
            # прочитанное «В наличии: N» точнее локального учёта
            self.flasks = self.corruption.last_flask_stock
        elif spent and self.flasks is not None:
            self.flasks = max(0, self.flasks - spent)
        elif spent:
            # Вести остаток не от чего: ручного поля больше нет, а «В наличии»
            # не прочиталось. Молчать нельзя — порог сейчас не работает.
            self.log("  остаток склянок прочитать не удалось — порог не действует")
        if spent:
            self.log(f"  склянок потрачено {spent}, осталось {self.flasks}")

        if res == 'low_energy':
            # Превью — источник истины: игра сама сказала, что энергии мало.
            self.log("Энергии не хватает на штурм — стоп. Пополни энергию и запусти снова.")
            return Action('stop')

        if res == 'dispatched':
            self._no_progress = 0
            after = self.vision.active_squads(self.driver.screenshot())
            if after <= active:
                self.log(f"  внимание: отрядов было {active}, стало {after} — "
                         f"отправка могла не пройти")
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('assault_boss')

    def one_iteration(self):
        # Стоп мог прийти, пока движок спал между итерациями
        if self.cancel.stopped():
            return Action('stop')
        if self.cfg.strategy == "corruption":
            return self._corruption_iteration()
        if self.cfg.use_search_strategy:
            return self._search_iteration()

        img = self.driver.screenshot()

        # GUARD: действуем только на чистой отзум-карте. После отправки камера
        # зумит за армией; на зум-ине детекция ловит UI-кнопки как цели.
        # Пробуем авто-отзум щипком; если не помогло N раз (вероятно меню) —
        # ждём человека.
        if not self.vision.on_world_map(img):
            if self._offmap_pinches < self.cfg.max_pinch_recover:
                self._offmap_pinches += 1
                self.log(f"Не на карте — авто-отзум щипком ({self._offmap_pinches}/{self.cfg.max_pinch_recover}).")
                self.driver.zoom_out()
                self.human.after_tap(1.5)
            else:
                self.log("Не на карте и щипок не помог (меню?) — жду человека.")
                self.sleep(self.human.idle_s(2.0))
            return None
        self._offmap_pinches = 0     # снова на карте -> сброс счётчика

        squad = self.vision.squad_state(img)
        state = self.read_state(img)

        # отряд в походе и слать рано -> ждём
        if not self._squad_ready(squad):
            self.log(f"Отряд занят ({squad}), ждём.")
            self.sleep(self.human.idle_s(2.0))
            return None

        # исключаем непроходимых боссов, помеченных ранее
        if self.skip_targets:
            state.targets = [t for t in state.targets
                             if self._target_key(t) not in self.skip_targets]

        action = decide(state, self.cfg)
        n_mob = sum(1 for t in state.targets if t.kind == 'mob')
        n_boss = sum(1 for t in state.targets if t.kind == 'boss')
        self.log(f"[отряд={squad}] энергия={state.energy} склянок={self.flasks} "
                 f"цели: мобов={n_mob} боссов={n_boss} -> {action.type}"
                 + (f" @({action.target.x},{action.target.y})" if action.target else ""))

        if self.cfg.dry_run:
            self.sleep(1.0)
            return action

        if action.type == 'stop':
            self.log("Стоп: склянок меньше порога.")
        elif action.type == 'refill':
            self.flasks = self.actions.refill_energy()
            self.log(f"Рефилл. Склянок осталось: {self.flasks}")
        elif action.type == 'assault_boss':
            res = self.actions.assault_boss(action.target)
            self.log(f"  Штурм босса -> {res}")
            if res == 'skip_unwinnable':
                self.skip_targets.add(self._target_key(action.target))
        elif action.type == 'attack_mob':
            res = self.actions.attack_mob(action.target)
            self.log(f"  Атака моба -> {res}")
        elif action.type == 'explore':
            self.driver.swipe(self.cfg.screen_w // 2, self.cfg.screen_h * 2 // 3,
                              self.cfg.screen_w // 2, self.cfg.screen_h // 3, 400)
        return action

    def _log_error(self, where, exc):
        self.log(f"[ОШИБКА в {where}] {type(exc).__name__}: {exc}")
        self.log(traceback.format_exc())
        self.log("Бот остановлен. Исправь причину и запусти снова.")

    def run(self, stop_event):
        try:
            if self.flasks is None:
                self.start()
        except Exception as exc:
            self._log_error("start", exc)
            return 'error'
        while True:
            if stop_event.is_set():
                return 'stopped_by_user'
            if os.path.exists(self.cfg.stop_file):
                return 'stop_file'
            try:
                action = self.one_iteration()
            except Exception as exc:
                self._log_error("one_iteration", exc)
                return 'error'
            if action is not None and action.type == 'stop' and not self.cfg.dry_run:
                return 'stop'
            self.sleep(self.human.idle_s(0.5))
