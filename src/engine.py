# src/engine.py
import os
import time
import traceback
from src.models import GameState
from src.decide import decide

class BotEngine:
    """Цикл фарма. Один отряд-на-задачу за раз (v1 последовательный):
    отряд занят -> ждём; свободен/«Возвращение» -> шлём следующую цель.
    Приоритет: босс («Штурм», отр.1) -> моб («Атака», отр.2) -> explore.

    dry_run (cfg.dry_run): читаем экран и ЛОГИРУЕМ решение, но НЕ тапаем —
    для проверки детекции/логики на живой игре без действий."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep):
        self.driver = driver
        self.vision = vision
        self.actions = actions
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.flasks = None
        self.skip_targets = set()   # непроходимые боссы (по позиции) — не долбимся в них
        self._offmap_pinches = 0    # подряд попыток авто-отзума когда не на карте

    def start(self):
        if self.cfg.dry_run:
            self.flasks = 10 ** 9        # в dry-run не открываем энергоокно
            self.log("Старт (DRY-RUN: тапов не будет).")
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

    def one_iteration(self):
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
                self.sleep(1.5)
            else:
                self.log("Не на карте и щипок не помог (меню?) — жду человека.")
                self.sleep(2.0)
            return None
        self._offmap_pinches = 0     # снова на карте -> сброс счётчика

        squad = self.vision.squad_state(img)
        state = self.read_state(img)

        # отряд в походе и слать рано -> ждём
        if not self._squad_ready(squad):
            self.log(f"Отряд занят ({squad}), ждём.")
            self.sleep(2.0)
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
            self.sleep(0.5)
